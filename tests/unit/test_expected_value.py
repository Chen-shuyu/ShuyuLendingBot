# -*- coding: utf-8 -*-
"""`ExpectedValueStrategy` 的單元測試（見 DECISIONS.md D035）。

這個策略的主張只有一句：**掛在哪個價位，由「利率 × 借出期間 ÷ (等待 + 借出期間)」
最大的那一個決定**，而等待時間每輪從 K 線重新估。所以測試圍著三件事打轉：

1. 等待時間的估法對不對（陣發性、右設限、命中次數不足）
2. 期望值有沒有真的選到最高的那一個，而不是最高的**利率**
3. 那些「寧可不掛」的出口還在（K 線缺、樣本不足、低於年化 8% 地板）

**測試資料的形狀取自 2026-08-17 對 `/v2/candles/trade:1h:fUSD:p2/hist` 的實打**：
日利率 0.00015~0.00030 這個量級、單根振幅動輒 5 個百分點（年化）。
用真實量級而不是 1／2／3 這種漂亮數字，是 D027 的教訓——
測試看到的世界比真實世界乾淨時，bug 就從那道縫鑽過去。
"""

import pytest

from strategies.expected_value import ExpectedValueStrategy

# 年化百分比 → 日利率，反過來也有一個。測試裡用年化寫比較讀得懂。
def daily(annual_pct):
    return annual_pct / 365 / 100


def annual(daily_rate):
    return daily_rate * 365 * 100


T0_MS = 1_786_968_000_000  # 2026-08-17 20:00:00 +0800


def candle(index, high, low=None, close=None):
    """一根 1 小時 K。只有 `high` 參與定價，其餘欄位照真實回應的形狀補齊。"""
    low = daily(4.0) if low is None else low
    close = high if close is None else close
    return {
        "mts": T0_MS + index * 3_600_000,
        "open": close,
        "close": close,
        "high": high,
        "low": low,
        "volume": 4_000_000.0,
    }


def base_config(**overrides):
    strategy = {
        "min_required_usd": 150,
        "min_loan_size_usd": 150,
        "minimum_rate": 0.00021918,  # 年化 8.00%
        "spread_count": 1,
        "offer_period": 2,
        "market_floor_pct": 0.85,
        "min_trade_samples": 3,
        "trade_window_hours": 6,
        "ev_min_hits": 5,
        "ev_min_candles": 48,
        "ev_window_hours": 168,
        "candle_hours": 1.0,
    }
    strategy.update(overrides)
    return {"strategy": strategy}


def trades_at(rate, count=10):
    """一批同天期成交，用來餵 `market_rate()`（成交價下限那條防線）。"""
    return [
        {"mts": T0_MS + i * 1000, "amount": 50_000.0, "rate": rate, "period": 2}
        for i in range(count)
    ]


class TestEstimateWait:
    """等待時間的估法（D038 起改為「從任意時刻進場」）。"""

    def test_每根都命中時平均等待是半根(self):
        strategy = ExpectedValueStrategy(base_config())
        highs = [daily(10.0)] * 60
        estimate = strategy.estimate_wait(highs, daily(9.0))
        assert estimate.hits == 60
        assert estimate.mean_hours == pytest.approx(0.5)
        assert estimate.median_hours == pytest.approx(0.5)
        assert estimate.censored == 0

    def test_陣發與均勻的等待差距不是幾個百分點而是好幾倍(self):
        """**這個測試就是 D038 的證據。**

        兩組資料的命中率完全一樣（12/24），一組平均散開、一組全擠在後半段。

        舊算法（命中間隔取平均）分辨得出來，但只差 6%：1.417 vs 1.500。
        那個差距小到在期望值計算裡幾乎不影響選擇——**看起來有處理陣發性，
        實際上沒有**。從進場時刻起算的話差距是 3.75 倍，那才是掛單當下的真實處境。
        """
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=3))
        hi, lo = daily(10.0), daily(5.0)

        均勻 = [hi if i % 2 == 0 else lo for i in range(24)]
        陣發 = [lo] * 12 + [hi] * 12

        估_均勻 = strategy.estimate_wait(均勻, daily(9.0))
        估_陣發 = strategy.estimate_wait(陣發, daily(9.0))

        assert 估_均勻.hits == 估_陣發.hits == 12

        # 均勻：12 個偶數起點等 0.5、11 個奇數起點等 1.5，
        # 最後一個起點（index 23）之後再也沒有命中，右設限計 1 根。
        assert 估_均勻.mean_hours == pytest.approx((0.5 * 12 + 1.5 * 11 + 1.0) / 24)
        assert 估_均勻.censored == 1
        # 陣發：前 12 個起點分別等 12.5…1.5，後 12 個各等 0.5 → 平均 3.75
        assert 估_陣發.mean_hours == pytest.approx((sum(12.5 - i for i in range(12)) + 0.5 * 12) / 24)
        assert 估_陣發.mean_hours == pytest.approx(3.75)
        assert 估_陣發.censored == 0

        # **差距的量級才是重點**：舊算法在同一份資料上只差 6%（1.417 vs 1.500），
        # 新算法差將近 4 倍。
        assert 估_陣發.mean_hours / 估_均勻.mean_hours > 3.5

        # 中位數同樣看得出形狀差異：一半的起點在均勻下 0.75 小時內就中，陣發下要 1.0
        assert 估_均勻.median_hours == pytest.approx(0.75)
        assert 估_陣發.median_hours == pytest.approx(1.0)

    def test_右設限計入而不是丟棄(self):
        """尾端「等到資料結束還沒等到」的起點要計入，否則最長的等待整批消失。

        舊版把這些丟掉，於是 42 根裡只剩開頭兩次「等半根就中」，
        算出平均 0.5 小時——**而實際上有 40 個起點是永遠等不到的**。
        """
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=2))
        hi, lo = daily(10.0), daily(5.0)
        highs = [hi, hi] + [lo] * 40  # 末尾 40 根一直沒等到

        estimate = strategy.estimate_wait(highs, daily(9.0))
        assert estimate.hits == 2
        assert estimate.censored == 40
        assert estimate.censored_ratio == pytest.approx(40 / 42)
        # 起點 0 等 0.5、起點 1 等 0.5，其餘 40 個以「等到窗尾」計入
        expected = (0.5 + 0.5 + sum(42 - s for s in range(2, 42))) / 42
        assert estimate.mean_hours == pytest.approx(expected)
        # 遠大於舊版算出的 0.5，這正是修正的重點
        assert estimate.mean_hours > 10

    def test_命中次數不足回傳None(self):
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=5))
        highs = [daily(10.0)] * 4 + [daily(5.0)] * 50
        assert strategy.estimate_wait(highs, daily(9.0)) is None

    def test_candle_hours_會換算成小時(self):
        """K 線改成 4 小時一根時，等待也要跟著變成 4 倍。"""
        strategy = ExpectedValueStrategy(base_config(candle_hours=4.0))
        highs = [daily(10.0)] * 60
        estimate = strategy.estimate_wait(highs, daily(9.0))
        assert estimate.mean_hours == pytest.approx(2.0)  # 0.5 根 × 4 小時

    def test_p75_講的是壞情況而不是平均(self):
        """重尾分佈下平均會被少數極長值拉高，三個數字要能各自說話。"""
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=3))
        hi, lo = daily(10.0), daily(5.0)
        # 前 4 根連續命中，之後 20 根乾旱，最後再命中一次
        highs = [hi] * 4 + [lo] * 20 + [hi]

        estimate = strategy.estimate_wait(highs, daily(9.0))
        assert estimate.median_hours < estimate.mean_hours < estimate.p75_hours
        assert estimate.censored == 0  # 最後一根命中，沒有右設限


class TestChooseRate:
    """期望值選價。"""

    def test_選的是實質年化最高而不是利率最高(self):
        """核心主張。最高的那一檔要等到把利差吃光，就不該選它。

        數字要夠極端才做得出這個對照，**這件事本身就是結論**：借出期間 48 小時
        是分母的大宗，等幾個小時稀釋不了多少。12% 要輸給 9.5%，平均得等上約 48 小時
        ——見 `test_借出期間夠長時等待幾小時幾乎不影響選擇`。
        """
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=5, ev_window_hours=300))
        # 300 根：每根都掃到 9.5%，但 12% 每 60 根才出現一次（平均等 47.7 小時）。
        highs = [daily(12.0) if i % 60 == 0 else daily(9.5) for i in range(300)]
        candles = [candle(i, high) for i, high in enumerate(highs)]

        chosen = strategy.choose_rate(candles)

        assert chosen == pytest.approx(daily(9.5), rel=1e-3)
        評估 = {round(annual(e["rate"]), 1): e for e in strategy.last_evaluation}
        # **命中規則時，進場等待反而比命中間隔短**（約為間隔的一半）：
        # 間隔是 60 根，但隨機進場平均落在間隔中間。舊算法在這裡算出 47.7 小時，
        # 新算法算出 29.9——**D038 的修正不是一律調高等待，是算對**。
        # 陣發時會算出更長（見 `test_陣發與均勻的等待差距不是幾個百分點而是好幾倍`），
        # 規則時會算出更短，兩邊都是同一條定義的結果。
        assert 評估[12.0]["wait_hours"] == pytest.approx(29.9, abs=0.1)
        assert 評估[9.5]["effective"] > 評估[12.0]["effective"]

    def test_借出期間夠長時等待幾小時幾乎不影響選擇(self):
        """把這個性質釘住，因為它反直覺、而且是策略敢掛高價的全部理由。

        `r × 48 ÷ (等待 + 48)`：等 8 小時只讓實質年化打 86 折，
        所以利率高兩成的價位就算要多等 8 小時仍然勝出。
        **這也是為什麼 `ev_min_hits` 是必要的**——沒有它，期望值會一路爬到
        一個只發生過一次、實際上等不到的價位。
        """
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=5))
        highs = [daily(20.0) if i % 10 == 0 else daily(9.0) for i in range(60)]
        candles = [candle(i, high) for i, high in enumerate(highs)]

        chosen = strategy.choose_rate(candles)

        評估 = {round(annual(e["rate"]), 1): e for e in strategy.last_evaluation}
        # 每 10 根命中一次 → 隨機進場平均等約半個間隔（4.9），不是一個間隔（舊版算 8.0）
        assert 評估[20.0]["wait_hours"] == pytest.approx(4.925)
        assert chosen == pytest.approx(daily(20.0), rel=1e-3)

    def test_等待很短時會往高價位走(self):
        """反向驗證：高價位若同樣常出現，就該選它。"""
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=5))
        candles = [candle(i, daily(20.0)) for i in range(60)]
        assert strategy.choose_rate(candles) == pytest.approx(daily(20.0), rel=1e-3)

    def test_只出現一次的尖端不會被選中(self):
        """`ev_min_hits` 擋的就是這個：一個不會再來的掃單。"""
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=5))
        highs = [daily(9.0)] * 59 + [daily(50.0)]
        candles = [candle(i, high) for i, high in enumerate(highs)]

        chosen = strategy.choose_rate(candles)

        assert chosen == pytest.approx(daily(9.0), rel=1e-3)
        assert all(annual(e["rate"]) < 50.0 for e in strategy.last_evaluation)

    def test_K線根數不足回傳None(self):
        strategy = ExpectedValueStrategy(base_config(ev_min_candles=48))
        candles = [candle(i, daily(9.0)) for i in range(47)]
        assert strategy.choose_rate(candles) is None

    def test_只採用窗內的K線(self):
        """窗外那段更高的行情不該影響現在的定價。"""
        strategy = ExpectedValueStrategy(base_config(ev_window_hours=60, ev_min_hits=5))
        舊的高價 = [candle(i, daily(30.0)) for i in range(100)]
        近期 = [candle(100 + i, daily(9.0)) for i in range(60)]

        chosen = strategy.choose_rate(舊的高價 + 近期)

        assert chosen == pytest.approx(daily(9.0), rel=1e-3)


class TestBuildOfferPlan:
    """整條定價鏈，含兩道防線與「寧可不掛」的出口。"""

    def _candles(self, annual_pct=10.0, count=60):
        return [candle(i, daily(annual_pct)) for i in range(count)]

    def test_正常情況掛出期望值最高的價位(self):
        strategy = ExpectedValueStrategy(base_config())
        plans = strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )
        assert len(plans) == 1
        assert plans[0].amount == pytest.approx(344.3)
        assert plans[0].duration == 2
        assert annual(plans[0].rate) == pytest.approx(10.0, abs=0.05)

    def test_沒有K線就整輪不掛而不是退回別的定價(self):
        """**刻意不設備援**：退回排隊定價等於自動切換到一個已知會賣在底部的策略。"""
        strategy = ExpectedValueStrategy(base_config())
        assert strategy.build_offer_plan(344.3, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=None) == []
        assert strategy.build_offer_plan(344.3, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=[]) == []

    def test_沒有成交紀錄就整輪不掛(self):
        strategy = ExpectedValueStrategy(base_config())
        assert strategy.build_offer_plan(344.3, 0.0002, book=[], trades=None, candles=self._candles()) == []

    def test_低於年化8趴地板就整輪不掛(self):
        """D035 決策三：這道地板維持不動，擋的是「賣在區間底部」。"""
        strategy = ExpectedValueStrategy(base_config())
        plans = strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=trades_at(daily(6.0)), candles=self._candles(annual_pct=7.0)
        )
        assert plans == []

    def test_成交價下限只往上拉不往下壓(self):
        """沿用 D033 的語意：期望值算出的價位若已高於下限，沒有理由砍掉它。"""
        strategy = ExpectedValueStrategy(base_config())
        plans = strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=trades_at(daily(9.0)), candles=self._candles(annual_pct=12.0)
        )
        assert annual(plans[0].rate) == pytest.approx(12.0, abs=0.05)

    def test_餘額低於門檻不掛(self):
        strategy = ExpectedValueStrategy(base_config())
        plans = strategy.build_offer_plan(
            100.0, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )
        assert plans == []

    def test_宣告了三份資料都要(self):
        """迴圈層靠這三個旗標決定要不要打對應的端點。"""
        strategy = ExpectedValueStrategy(base_config())
        assert strategy.requires_book is True
        assert strategy.requires_trades is True
        assert strategy.requires_candles is True


class TestRegression:
    """把 2026-08-17 的實際情境釘住，避免改壞了沒人發現。"""

    def test_低價牆情境下新舊策略的行為相反(self):
        """D035 的核心對照。

        簿子底端一道 445 萬的低價牆（年化 5.47%），但 K 線顯示九成的小時都掃到
        年化 9% 以上。舊策略被牆押到 5.47%、再被 8% 地板擋掉而整輪不掛；
        新策略看的是「需求掃到多高」，所以照樣掛得出去。
        """
        from strategies.orderbook_depth import OrderBookDepthStrategy

        config = base_config()
        wall_book = [
            {"rate": daily(5.47), "period": 2, "amount": 4_450_000.0},
            {"rate": daily(9.5), "period": 2, "amount": 300_000.0},
        ]
        # 成交紀錄反映當下那個切片：大部分成交在牆價上。
        wall_trades = trades_at(daily(5.47), count=9) + trades_at(daily(9.5), count=1)
        # K 線反映的是七天的常態：九成的小時掃到 9% 以上。
        wall_candles = [
            candle(i, daily(9.5) if i % 10 != 0 else daily(5.47)) for i in range(60)
        ]

        old = OrderBookDepthStrategy(config).build_offer_plan(
            344.3, 0.0002, book=wall_book, trades=wall_trades
        )
        new = ExpectedValueStrategy(config).build_offer_plan(
            344.3, 0.0002, book=wall_book, trades=wall_trades, candles=wall_candles
        )

        assert old == []  # 排隊定價算出 5.47%，被 8% 地板擋下
        assert len(new) == 1
        assert annual(new[0].rate) == pytest.approx(9.5, abs=0.05)


class TestDecisionIsVisible:
    """定價決策要看得見（TASKS.md A1）。

    **這一組測試釘住的是 D033 的教訓**：那次用半價把 344 USD 借出去，
    事後翻日誌只有「掛出 344.30 USD，利率 0.000150」——沒有任何數字能看出那是半價。
    定價換成期望值之後，同樣的處境原封不動重現了一次。
    """

    def _candles(self, annual_pct=10.0, count=60):
        return [candle(i, daily(annual_pct)) for i in range(count)]

    def test_掛單時說得出這個價位是怎麼選出來的(self):
        strategy = ExpectedValueStrategy(base_config())
        strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )
        line = strategy.describe_decision()

        assert line is not None
        # 四個數字缺一不可：候選數、選中的價、等待、實質年化
        for 必要欄位 in ("候選價位", "選中年化", "平均等待", "實質年化"):
            assert 必要欄位 in line
        assert "10.00%" in line

    def test_沒評估過就不硬掰(self):
        """餘額不足在評估之前就出局，這時沒有東西可以講。"""
        strategy = ExpectedValueStrategy(base_config())
        strategy.build_offer_plan(
            10.0, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )
        assert strategy.describe_decision() is None

    def test_價格太低而不掛時_理由不可以說成沒錢(self):
        """**這是這次改動最重要的一項。**

        帳上有 344 USD、市場走弱到年化 8% 以下，舊版會寫
        「可放貸金額不足（目前 344.3 USD）」——自相矛盾，而且把人指向
        「錢為什麼不見了」這個完全錯誤的方向。
        """
        strategy = ExpectedValueStrategy(base_config())
        plans = strategy.build_offer_plan(
            344.3,
            0.0002,
            book=[],
            trades=trades_at(daily(6.0)),
            candles=self._candles(annual_pct=7.0),
        )

        assert plans == []
        reason = strategy.last_skip_reason
        assert reason is not None
        assert "地板" in reason and "8.00%" in reason
        # 絕對不能把「價格太低」講成「錢不夠」
        assert "餘額" not in reason and "金額不足" not in reason

    def test_每個不掛的出口都說得出自己的理由(self):
        """六個出口逐一走一遍，確認沒有任何一個是沉默的。"""
        strategy = ExpectedValueStrategy(base_config())
        good_trades = trades_at(daily(10.0))
        good_candles = self._candles()

        情境 = [
            ("低於下限", dict(balance_usd=10.0, trades=good_trades, candles=good_candles)),
            ("拿不到利率 K 線", dict(balance_usd=344.3, trades=good_trades, candles=None)),
            ("近期成交樣本不足", dict(balance_usd=344.3, trades=None, candles=good_candles)),
            ("K 線只有", dict(balance_usd=344.3, trades=good_trades, candles=self._candles(count=10))),
        ]
        for 關鍵字, kwargs in 情境:
            strategy.last_skip_reason = None
            plans = strategy.build_offer_plan(
                kwargs["balance_usd"], 0.0002, book=[],
                trades=kwargs["trades"], candles=kwargs["candles"],
            )
            assert plans == [], f"{關鍵字}：預期不掛單"
            assert strategy.last_skip_reason is not None, f"{關鍵字}：沒有留下原因"
            assert 關鍵字 in strategy.last_skip_reason, (
                f"預期理由含「{關鍵字}」，實際是「{strategy.last_skip_reason}」"
            )

    def test_掛得出去時不留下不掛的理由(self):
        """成功那一輪要把上一輪的理由清掉，否則日誌會沿用過期的說法。"""
        strategy = ExpectedValueStrategy(base_config())
        strategy.build_offer_plan(10.0, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles())
        assert strategy.last_skip_reason is not None

        plans = strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )
        assert len(plans) == 1
        assert strategy.last_skip_reason is None


class TestChosenForecast:
    """掛出去那一刻的預估要交得出來，否則事後無法校準（D038）。"""

    def test_回傳選中價位的三個統計量(self):
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=5, ev_window_hours=168))
        highs = [daily(20.0) if i % 10 == 0 else daily(9.0) for i in range(60)]
        candles = [candle(i, high) for i, high in enumerate(highs)]

        chosen = strategy.choose_rate(candles)
        forecast = strategy.chosen_forecast()

        assert forecast["rate"] == pytest.approx(chosen)
        assert forecast["window_hours"] == 168
        assert forecast["mean_hours"] == pytest.approx(4.925)
        # **三個都要在**：只留平均等於把「重尾」這件事再丟一次
        assert "median_hours" in forecast and "p75_hours" in forecast
        assert forecast["hits"] == 6

    def test_沒評估過就回None(self):
        strategy = ExpectedValueStrategy(base_config())
        assert strategy.chosen_forecast() is None

    def test_預估與日誌講的是同一個價位(self):
        """日誌說 A、存進 DB 的是 B 的話，事後校準會校到錯的東西上。"""
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=5))
        highs = [daily(20.0) if i % 10 == 0 else daily(9.0) for i in range(60)]
        strategy.choose_rate([candle(i, high) for i, high in enumerate(highs)])

        forecast = strategy.chosen_forecast()
        line = strategy.describe_decision()
        assert f"選中年化 {annual(forecast['rate']):.2f}%" in line
        assert f"平均 {forecast['mean_hours']:.1f}h" in line


class TestEvaluationDoesNotLeakAcrossRounds:
    """本輪沒評估過，就不可以拿上一輪的決策充數（D041）。

    **既有的 `test_沒評估過就不硬掰` 抓不到這件事**，因為它從一個全新的策略物件
    出發——而全新物件的 `last_evaluation` 本來就是空的。真實運作裡策略物件活得
    跟行程一樣久，一輪一輪重複用，**bug 只在第二次呼叫才現形**。
    這正是 D027 那句「測試看到的世界比真實世界乾淨」的又一次現身。

    現場代價：2026-08-21 22:34 資金借出、餘額掉到門檻以下之後，日誌連續 21 小時、
    87 輪以上印出位元組完全相同的一行「期望值定價：113 個候選價位，選中年化
    9.50%……」，而同一輪的鄰行寫著「可用餘額 0.01 USD 低於下限 150.00 USD」。
    **兩行互相矛盾，而錯的是前面那行。** 08-22 19:22 容器重啟後那行整個消失
    （新行程的清單是空的），反過來證明了先前那些全是舊資料。
    """

    def _candles(self, annual_pct=10.0, count=60):
        return [candle(i, daily(annual_pct)) for i in range(count)]

    def _evaluated_once(self, **overrides):
        """先跑一輪會真的評估的巡檢，讓策略手上留著一份決策。"""
        strategy = ExpectedValueStrategy(base_config(**overrides))
        strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )
        assert strategy.describe_decision() is not None, "前置條件：這一輪要真的評估過"
        return strategy

    def test_餘額掉到門檻以下的下一輪不再重播上一輪的決策(self):
        """真實情境：資金借出去了，餘額只剩零頭。"""
        strategy = self._evaluated_once()
        strategy.build_offer_plan(
            0.01, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )

        assert strategy.describe_decision() is None

    def test_落DB的那一半也不可以重播(self):
        """`chosen_forecast()` 與 `describe_decision()` 共用同一個清單。

        今天只有掛單成功那條路會呼叫它，所以 `offer_wait_forecasts` 沒被汙染過
        ——但那是呼叫順序的巧合，不是設計上的保證。校準資料一旦混進上一輪的預估，
        「預估 vs 實際」就再也對不起來，而那正是 D038 建起來的東西。
        """
        strategy = self._evaluated_once()
        strategy.build_offer_plan(
            0.01, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )

        assert strategy.chosen_forecast() is None

    def test_拿不到K線的那一輪也不重播(self):
        """另一個在 `choose_rate()` 之前就出局的出口。"""
        strategy = self._evaluated_once()
        strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=[]
        )

        assert strategy.describe_decision() is None

    def test_成交樣本不足的那一輪也不重播(self):
        """第三個出口：算不出常態成交價。"""
        strategy = self._evaluated_once()
        strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=[], candles=self._candles()
        )

        assert strategy.describe_decision() is None

    def test_反向斷言_不可以印出上一輪那一行的內容(self):
        """釘住的是「不重播」，不只是「回傳 None」。

        只斷言 `is None` 的話，把整個方法改成永遠回傳 `None` 也會過——
        那是把「偷偷講錯」換成「偷偷不講」。
        """
        strategy = self._evaluated_once()
        上一輪 = strategy.describe_decision()
        strategy.build_offer_plan(
            0.01, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )

        assert strategy.describe_decision() != 上一輪

    def test_下一輪重新評估後又講得出話來(self):
        """對照組：**不是把這個能力關掉**，只是不准跨輪沿用。"""
        strategy = self._evaluated_once()
        strategy.build_offer_plan(
            0.01, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )
        assert strategy.describe_decision() is None

        strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )
        assert strategy.describe_decision() is not None


class TestPricingDecisionRecord:
    """落 DB 的那一份決策紀錄（M1-b）。

    **這張表跟日誌不一樣的地方在於它會被當成事實**：M2 回測工具要拿它回答
    「如果當時跑的是另一個策略會怎樣」，而一列錯的決策沒有鄰行可以拆穿它
    ——D041 當初把 M1-b 擋在驗收後面，理由就是這個。所以這裡驗的是
    **「存下去的東西跟當時真的算出來的是同一個」**，而不只是欄位有值。
    """

    def _candles(self, annual_pct=10.0, count=60):
        return [candle(i, daily(annual_pct)) for i in range(count)]

    def _evaluated(self, **overrides):
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=5, **overrides))
        highs = [daily(20.0) if i % 10 == 0 else daily(9.0) for i in range(60)]
        strategy.choose_rate([candle(i, high) for i, high in enumerate(highs)])
        return strategy

    def test_沒評估過就回None(self):
        assert ExpectedValueStrategy(base_config()).pricing_decision() is None

    def test_選中的價位與日誌和預估講的是同一個(self):
        """三個出口（日誌、`offer_wait_forecasts`、`pricing_decisions`）
        讀的是同一份 `last_evaluation`。**其中一個講別的價位，事後就對不起來**
        ——而三份資料互相矛盾時，沒有人知道該相信哪一份。"""
        strategy = self._evaluated()

        decision = strategy.pricing_decision()
        forecast = strategy.chosen_forecast()
        line = strategy.describe_decision()

        assert decision["chosen_rate"] == pytest.approx(forecast["rate"])
        assert f"選中年化 {annual(decision['chosen_rate']):.2f}%" in line
        assert decision["chosen_mean_hours"] == pytest.approx(forecast["mean_hours"])

    def test_選中的是實質年化最高的那一個而不是利率最高的(self):
        """這是整個策略的主張本身（D035）。存錯了，M2 會以為當初選的是別的東西。

        **資料刻意選在兩者會分家的地方**：年化 10% 每 12 小時才掃到一次，
        而 9% 幾乎每小時都掃得到——等待成本吃掉那一個百分點之後，
        `利率 × 48 ÷ (等待 + 48)` 選的是 9% 那個。兩者不分家的資料驗不到東西。
        """
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=5))
        strategy.choose_rate(
            [candle(i, daily(10.0) if i % 12 == 0 else daily(9.0)) for i in range(60)]
        )
        decision = strategy.pricing_decision()

        best = max(strategy.last_evaluation, key=lambda item: item["effective"])
        assert decision["chosen_rate"] == pytest.approx(best["rate"])
        assert decision["chosen_effective"] == pytest.approx(best["effective"])
        assert annual(decision["chosen_rate"]) == pytest.approx(9.0, abs=0.05)
        assert decision["chosen_rate"] < max(
            item["rate"] for item in strategy.last_evaluation
        ), "前置條件：這組資料裡利率最高的不是實質年化最高的，否則這個測試沒在驗東西"

    def test_對照組是等最短的那一個(self):
        """`fastest` 就是舊策略會選的那一類價位。兩者並列才看得出取捨換到了什麼。"""
        strategy = self._evaluated()
        decision = strategy.pricing_decision()

        assert decision["fastest_mean_hours"] == pytest.approx(
            min(item["wait_hours"] for item in strategy.last_evaluation)
        )
        assert decision["fastest_rate"] < decision["chosen_rate"]

    def test_候選集依價位排序(self):
        """事後要比對兩輪「111 → 110 少了哪一個」，靠的就是這個順序（D3）。"""
        rates = self._evaluated().pricing_decision()["candidate_rates"]

        assert rates == sorted(rates)
        assert len(set(rates)) == len(rates), "候選價位量化過，不該有重複"

    def test_候選集兩排等長且對得起來(self):
        """價位與實質年化是兩排平行的陣列。長度一旦對不上，
        **事後每一個「這個價位當時算出多少」都會讀到隔壁那一個的值**。"""
        strategy = self._evaluated()
        decision = strategy.pricing_decision()

        assert len(decision["candidate_rates"]) == decision["candidate_count"]
        assert len(decision["candidate_effectives"]) == decision["candidate_count"]
        by_rate = {item["rate"]: item["effective"] for item in strategy.last_evaluation}
        for rate, effective in zip(
            decision["candidate_rates"], decision["candidate_effectives"]
        ):
            assert effective == pytest.approx(by_rate[rate])

    def test_選中的價位一定在候選集裡(self):
        decision = self._evaluated().pricing_decision()
        assert decision["chosen_rate"] in decision["candidate_rates"]

    def test_記下當時的窗長到哪一根K為止(self):
        """D3 問的是「哪一根 K 滾出窗」。少了這兩個座標，事後只能猜。"""
        # `ev_min_candles` 一起調小：窗比它短的話 `choose_rate()` 會在算窗之前
        # 就以「資料不足」出局，那樣驗到的是另一件事。
        strategy = ExpectedValueStrategy(
            base_config(ev_min_hits=5, ev_window_hours=20, ev_min_candles=20)
        )
        candles = [candle(i, daily(10.0)) for i in range(60)]
        strategy.choose_rate(candles)

        decision = strategy.pricing_decision()
        assert decision["candle_count"] == 20, "窗長就是 ev_window_hours，不是抓回來的根數"
        assert decision["candle_latest_mts"] == candles[-1]["mts"]
        assert decision["window_hours"] == 20

    def test_存下的是當時假設的持有時間而不是實測值(self):
        """`hold_hours_assumed` 存的是**假設**。這個 48 已知與現實不符
        （D040 實測完成率 43.6%），存它的理由是 M2 要拿它當「當時假設了什麼」
        ——改掉那個數字之後，舊決策才有辦法跟新決策比較。"""
        decision = self._evaluated().pricing_decision()
        assert decision["hold_hours_assumed"] == pytest.approx(48.0)

    def test_記下是哪一個策略算的(self):
        assert self._evaluated().pricing_decision()["strategy"] == "ExpectedValueStrategy"

    def test_餘額掉到門檻以下的下一輪不可以留下決策(self):
        """**D041 的保護要延伸到這個新出口**，否則 M1-b 就是把那個 bug
        從日誌搬進 DB——而 DB 那一份沒有鄰行會反駁它。"""
        strategy = ExpectedValueStrategy(base_config())
        strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )
        assert strategy.pricing_decision() is not None, "前置條件：這一輪要真的評估過"

        strategy.build_offer_plan(
            0.01, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )

        assert strategy.pricing_decision() is None

    def test_反向斷言_不可以留下上一輪那一列的內容(self):
        """只斷言 `is None` 的話，把方法改成永遠回傳 `None` 也會過。"""
        strategy = ExpectedValueStrategy(base_config())
        strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )
        上一輪 = strategy.pricing_decision()
        strategy.build_offer_plan(
            0.01, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )

        assert strategy.pricing_decision() != 上一輪

    def test_窗的座標也不可以跨輪殘留(self):
        """`last_window` 是跟著 M1-b 一起加進來的第三個「本輪狀態」。
        **每多一個都得在同一個地方重置**，漏掉的那一個不會有人發現（D041）。"""
        strategy = ExpectedValueStrategy(base_config())
        strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )
        assert strategy.last_window != {}

        strategy.build_offer_plan(
            0.01, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )

        assert strategy.last_window == {}

    def test_下一輪重新評估後又留得下來(self):
        """對照組：**不是把這個能力關掉**，只是不准跨輪沿用。"""
        strategy = ExpectedValueStrategy(base_config())
        strategy.build_offer_plan(
            0.01, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )
        assert strategy.pricing_decision() is None

        strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=self._candles()
        )
        assert strategy.pricing_decision() is not None


class TestEvaluateRate:
    """對**任意**利率重新評估（M1-c，D046）。

    這個方法存在的唯一理由是「兩邊要用同一把尺」：M1-c 要把「保住場上那張單」跟
    「改掛本輪候選」的實質年化並排比較，而**場上那張的利率通常不在候選集裡**
    ——它是更早某一輪選出來的，中間還經過成交價下限與 spread 的加工。

    所以這裡驗的是三件事：**同一把尺**（跟 `last_evaluation` 對得起來）、
    **算不出來時講得清楚**（命中不足要留下 `hits`，不是回一個空白）、
    以及**不准跨輪殘留**（D041 的那條規則，`last_highs` 是第四個成員）。
    """

    def _evaluated(self, **overrides):
        """跑一輪真的評估過的定價，讓策略手上留著本輪那一窗。"""
        strategy = ExpectedValueStrategy(base_config(**overrides))
        highs = [daily(20.0) if i % 10 == 0 else daily(9.0) for i in range(60)]
        strategy.choose_rate([candle(i, high) for i, high in enumerate(highs)])
        return strategy

    def test_沒評估過就回None(self):
        assert ExpectedValueStrategy(base_config()).evaluate_rate(daily(9.0)) is None

    def test_跟last_evaluation裡同一個利率算出來的完全相同(self):
        """**這是「同一把尺」的本體。** 候選價位的 `effective` 出自
        `choose_rate()`，場上那張的出自這裡；兩者只要有一絲不同，
        並排比出來的差額就有一部分是尺的差，而不是市場的差。
        """
        strategy = self._evaluated()
        item = strategy.last_evaluation[0]

        again = strategy.evaluate_rate(item["rate"])

        assert again["wait_hours"] == pytest.approx(item["wait_hours"])
        assert again["median_hours"] == pytest.approx(item["median_hours"])
        assert again["p75_hours"] == pytest.approx(item["p75_hours"])
        assert again["hits"] == item["hits"]
        assert again["censored_ratio"] == pytest.approx(item["censored_ratio"])
        assert again["effective"] == pytest.approx(item["effective"])

    def test_候選集以外的利率也算得出來(self):
        """場上那張單的利率不必是窗內出現過的 `high`。

        真實情境：`build_offer_plan()` 把選出來的價位經過成交價下限與 spread
        加工之後才掛出去，於是**實際掛在場上的利率通常不在候選集裡**。
        """
        strategy = self._evaluated()
        odd_rate = daily(9.37)  # 刻意不是任何一根 K 的 high
        assert odd_rate not in [item["rate"] for item in strategy.last_evaluation]

        result = strategy.evaluate_rate(odd_rate)

        assert result is not None
        assert result["rate"] == pytest.approx(odd_rate)
        assert result["effective"] > 0

    def test_命中不足時照樣回一列而且留下hits(self):
        """**這一條是 08-19 那張單的形狀**：掛 9.78% 在場 34.2 小時沒成交。

        回 `None` 的話，「窗裡一次都沒掃到這麼高」與「掃到了但只有三次」
        會被壓成同一個空白，而那兩件事在分析長尾時意義完全不同。
        """
        strategy = self._evaluated(ev_min_hits=5)
        too_high = daily(25.0)  # 窗內最高只到 20%

        result = strategy.evaluate_rate(too_high)

        assert result is not None, "算不出實質年化不等於不留紀錄"
        assert result["effective"] is None
        assert result["wait_hours"] is None
        assert result["hits"] == 0, "『一次都沒掃到』要看得出來"

    def test_掃到但次數不夠時hits講得出差多少(self):
        """對照組：跟上面那條是兩件事，而 `hits` 是唯一分得出來的欄位。

        窗內每 10 根有一根 20%，60 根共 **6 次**；把門檻拉到 10 次，
        於是「掃到過但不夠」與「從沒掃到」在 `effective` 上長得一模一樣，
        **只有 `hits` 分得出來**——6 對 0。
        """
        strategy = self._evaluated(ev_min_hits=10)

        scanned = strategy.evaluate_rate(daily(20.0))
        never = strategy.evaluate_rate(daily(25.0))

        assert scanned["effective"] is None and never["effective"] is None
        assert scanned["hits"] == 6, "掃到過六次"
        assert never["hits"] == 0, "一次都沒掃到"

    def test_不准跨輪殘留(self):
        """`last_highs` 是第四個「本輪的狀態」，重置點跟前三個是同一處（D041）。

        少了這條，資金借出去、餘額掉到門檻以下的那些輪次，會拿**上一輪的窗**
        去評估這一輪場上那張單——而那正是 D041 兩個 bug 的成因。
        """
        strategy = ExpectedValueStrategy(base_config())
        candles = [candle(i, daily(10.0)) for i in range(60)]
        strategy.build_offer_plan(
            344.3, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=candles
        )
        assert strategy.evaluate_rate(daily(9.0)) is not None, "前置條件：這一輪評估過"

        strategy.build_offer_plan(
            0.01, 0.0002, book=[], trades=trades_at(daily(10.0)), candles=candles
        )

        assert strategy.evaluate_rate(daily(9.0)) is None

    def test_利率為零或負數回None(self):
        """不是防禦性寫法：`live_rate` 來自交易所回應，而 D027 記的正是
        「測試看到的世界比真實世界乾淨」。"""
        strategy = self._evaluated()
        assert strategy.evaluate_rate(0) is None
        assert strategy.evaluate_rate(-0.0001) is None


class TestD056假設與合約天期是兩件事:
    """🔴 **2026-08-30 拆開（D056）。這一族擋的是「它們又被綁回去」。**

    `offer_period` 是**送給交易所的合約天期**（Bitfinex 最短 2 天，而且是整數）；
    `assumed_hold_hours` 是**算式裡的 `P`**（借款人隨時可以提前還款，所以是期望值）。

    綁在一起的後果是：**想修正假設就得改合約條款，而那條路走不通。**
    """

    @staticmethod
    def _config(**strategy):
        base = {
            "ev_window_hours": 168,
            "ev_min_hits": 5,
            "ev_min_candles": 48,
            "candle_hours": 1.0,
            "offer_period": 2,
            "minimum_rate": 0.0001,
        }
        base.update(strategy)
        return {"strategy": base}

    def test_沒設就退回舊行為(self):
        """**沒設這個鍵的人行為完全不變**——這是拆開時刻意保留的退路。"""
        from strategies.expected_value import ExpectedValueStrategy

        strategy = ExpectedValueStrategy(self._config())
        assert strategy.assumed_hold_hours == 48.0
        assert strategy.offer_period == 2

    def test_設了就用設的值而且不動合約天期(self):
        from strategies.expected_value import ExpectedValueStrategy

        strategy = ExpectedValueStrategy(self._config(assumed_hold_hours=12))
        assert strategy.assumed_hold_hours == 12.0
        assert strategy.offer_period == 2, "合約天期不可以被假設值帶著跑"

    def test_可以是小數而合約天期仍是整數(self):
        """假設值是期望值，本來就可能不是整數天；合約天期則必須是整數。"""
        from strategies.expected_value import ExpectedValueStrategy

        strategy = ExpectedValueStrategy(self._config(assumed_hold_hours=11.61))
        assert strategy.assumed_hold_hours == pytest.approx(11.61)
        assert isinstance(strategy.offer_period, int)

    def test_假設值真的會改變選出來的價位(self):
        """不然這個設定就只是裝飾品。"""
        from strategies.expected_value import ExpectedValueStrategy

        candles = [
            {"mts": 1_788_000_000_000 + i * 3_600_000, "high": h}
            for i, h in enumerate(
                ([0.00015] * 8 + [0.00029879] + [0.00016] * 5 + [0.00031416] + [0.000155] * 5) * 6
            )
        ]
        寬鬆 = ExpectedValueStrategy(self._config(assumed_hold_hours=48)).choose_rate(candles)
        嚴格 = ExpectedValueStrategy(self._config(assumed_hold_hours=12)).choose_rate(candles)
        assert 寬鬆 is not None and 嚴格 is not None
        assert 嚴格 <= 寬鬆, "假設賺錢時間變短，就該更怕等待、選更便宜的價位"

    def test_落帳記的是假設值不是合約天期(self):
        """`pricing_decisions.hold_hours_assumed` 要記真正用在算式裡的那個數。"""
        from strategies.expected_value import ExpectedValueStrategy

        candles = [
            {"mts": 1_788_000_000_000 + i * 3_600_000, "high": h}
            for i, h in enumerate(
                ([0.00015] * 8 + [0.00029879] + [0.00016] * 5 + [0.00031416] + [0.000155] * 5) * 6
            )
        ]
        strategy = ExpectedValueStrategy(self._config(assumed_hold_hours=12))
        strategy.choose_rate(candles)
        assert strategy.pricing_decision()["hold_hours_assumed"] == 12.0


class TestD061高原容差:
    """實質年化曲線在高原上是平的，而原本的平手方向偏向便宜那一邊。

    **正式資料的形狀**（2026-09-05，552 根真實 K）：

        8.7600%  實質 = 7.695058824   <== 舊行為選中
        8.9279%  實質 = 7.695017700

    差 **4×10⁻⁵ 個百分點**，而同一份資料裡 `W` 的估計誤差是 **4～9 倍**。
    下面用一段合成的 K 線重現同一個形狀——**合成而不是抄那 552 根**，
    是因為這一條要釘的是「平手時往哪邊走」，不是那一天的數字。
    """

    @staticmethod
    def _plateau_candles():
        """造出一段 high 分佈，讓兩個相鄰價位的實質年化幾乎相同。

        手法是讓高價位只比低價位多等一點點：`high` 大部分落在低價，
        少數幾根探到高價，於是 `r × P ÷ (W + P)` 在兩者之間幾乎打平。
        """
        低 = daily(9.0)
        高 = daily(9.2)
        pattern = [低] * 11 + [高]
        return [candle(i, h) for i, h in enumerate(pattern * 16)]

    @staticmethod
    def _config(tolerance):
        return base_config(
            assumed_hold_hours=12,
            ev_min_hits=5,
            ev_plateau_tolerance_pct=tolerance,
        )

    def test_容差為零時退回舊行為取最便宜的那一個(self):
        """**退場鍵要真的能退回去。** 沒有辦法退回去的改動沒有辦法被比較。"""
        strategy = ExpectedValueStrategy(self._config(0.0))
        chosen = strategy.choose_rate(self._plateau_candles())
        best = max(item["effective"] for item in strategy.last_evaluation)
        同分 = [
            item["rate"]
            for item in strategy.last_evaluation
            if item["effective"] == best
        ]
        assert chosen == min(同分)

    def test_容差打開時在同分的那一群裡取最高價(self):
        strategy = ExpectedValueStrategy(self._config(0.5))
        chosen = strategy.choose_rate(self._plateau_candles())
        寬鬆 = ExpectedValueStrategy(self._config(0.0)).choose_rate(
            self._plateau_candles()
        )
        assert chosen is not None and 寬鬆 is not None
        assert chosen >= 寬鬆, "容差打開只可能往上，不可能往下"

    def test_容差越大選出的價位不會變便宜(self):
        """單調性：高原只會變寬，不會換一群人。**這一條擋的是實作寫反。**"""
        candles = self._plateau_candles()
        picks = [
            ExpectedValueStrategy(self._config(tol)).choose_rate(candles)
            for tol in (0.0, 0.5, 1.0, 2.0, 5.0)
        ]
        assert all(pick is not None for pick in picks)
        assert picks == sorted(picks)

    def test_容差不會讓它跳出候選集(self):
        """高原是從候選集裡切出來的，**不是憑空往上加一階**。"""
        candles = self._plateau_candles()
        strategy = ExpectedValueStrategy(self._config(5.0))
        chosen = strategy.choose_rate(candles)
        assert chosen in {item["rate"] for item in strategy.last_evaluation}

    def test_全部候選的實質年化都是零時不挑最貴的(self):
        """🔴 **這一條釘的是一個會靜默選到最貴價位的邊界。**

        `effective` 恆非負，所以最佳值若是 0，「最佳值 ×(1 − 容差)」也是 0，
        整個候選集都會被判定同分——然後挑出最貴的那一個。
        **在一份全是 0 的評估上挑最貴的，是最壞的猜。**
        """
        strategy = ExpectedValueStrategy(self._config(0.5))
        strategy.last_evaluation = []
        assert (
            strategy._pick_from_plateau(
                [
                    {"rate": daily(9.0), "effective": 0.0},
                    {"rate": daily(20.0), "effective": 0.0},
                ]
            )
            is None
        )

    def test_只有一個候選時容差不改變任何事(self):
        strategy = ExpectedValueStrategy(self._config(2.0))
        only = [{"rate": daily(9.11), "effective": 0.0002}]
        assert strategy._pick_from_plateau(only) == daily(9.11)

    def test_正式設定檔打開了這個旋鈕(self):
        """🔴 **類別預設是 0，正式環境的值寫在 `config.yaml`。**

        這一條釘的是「那個值真的有被載進去」——`assumed_hold_hours` 當初就是
        因為預設值與設定檔各講一套，才需要 D056 把兩件事拆開。
        """
        from pathlib import Path

        from config import settings

        root = Path(__file__).resolve().parent.parent.parent
        config = settings.load_config(str(root / "config.yaml"))
        assert config["strategy"]["ev_plateau_tolerance_pct"] == 0.5
        assert ExpectedValueStrategy(base_config()).ev_plateau_tolerance_pct == 0.0


class TestD061選中的是誰只能有一個來源:
    """🔴 **這一組釘的是一個真的被部署出去的缺陷。**

    D061 加上高原容差之後，選中的不再必然是 `max(effective)` 的那一個，而
    `describe_decision()`／`chosen_forecast()`／`pricing_decision()`
    **三處各自用 `max(...)` 重算了一次「誰被選中」**。於是機器人會掛 8.9279%，
    而日誌、`offer_wait_forecasts`、`pricing_decisions` 三處**一致地**說 8.76%
    ——**三個都錯成同一個值，看起來完全正常**。D026 那個家族的典型長相。

    上線時 879 條測試全綠，**一條都沒有比對過「報出來的」與「掛出去的」是不是
    同一個數字**——每一條都只驗其中一邊。這一組補的就是那個比對。
    """

    @staticmethod
    def _candles():
        低, 高 = daily(9.0), daily(9.2)
        return [candle(i, h) for i, h in enumerate(([低] * 11 + [高]) * 16)]

    @staticmethod
    def _evaluation(rate, effective):
        """一列 `last_evaluation`，欄位形狀照 `choose_rate()` 產生的樣子。"""
        return {
            "rate": rate,
            "wait_hours": 1.66,
            "median_hours": 0.5,
            "p75_hours": 1.5,
            "hits": 108,
            "censored_ratio": 0.0,
            "effective": effective,
        }

    @staticmethod
    def _strategy(tolerance):
        return ExpectedValueStrategy(
            base_config(
                assumed_hold_hours=12,
                ev_min_hits=5,
                ev_plateau_tolerance_pct=tolerance,
            )
        )

    @pytest.mark.parametrize("tolerance", [0.0, 0.5, 2.0, 5.0])
    def test_三個報告端講的都是真的掛出去那一個(self, tolerance):
        strategy = self._strategy(tolerance)
        chosen = strategy.choose_rate(self._candles())
        assert chosen is not None
        assert strategy.pricing_decision()["chosen_rate"] == chosen
        assert strategy.chosen_forecast()["rate"] == chosen
        assert f"{annual(chosen):.2f}%" in strategy.describe_decision()

    def test_選中的不是最高分那一個時三處仍然講對(self):
        """🔴 **這一條才是真的釘住那個 bug 的。**

        上一條在合成 K 線上跑，而合成 K 線造不出「選中的 ≠ 最高分的」那種高原
        ——那樣它就算實作寫錯也會通過。**這裡直接把那個狀態擺出來。**

        數字取自 2026-09-05 正式資料的形狀：兩個候選的實質年化差 4×10⁻⁵ 個
        百分點，而舊實作會報最高分的 8.76%，實際掛出去的是 8.93%。
        """
        strategy = self._strategy(0.5)
        便宜 = self._evaluation(daily(8.7600), 7.695058824 / 36500)
        貴 = self._evaluation(daily(8.9279), 7.695017700 / 36500)
        strategy.last_evaluation = [便宜, 貴]
        strategy.last_chosen = 貴  # `choose_rate()` 真的會選這一個

        assert 貴["effective"] < 便宜["effective"], "測資沒有重現那個平手"
        assert strategy.pricing_decision()["chosen_rate"] == 貴["rate"]
        assert strategy.chosen_forecast()["rate"] == 貴["rate"]
        # **比對「選中年化」那一段，不是整串**：8.76% 在同一行還會以
        # 「對照最快成交的候選」的身分合法出現，比對整串會誤判。
        assert "選中年化 8.93%" in strategy.describe_decision()
        assert "選中年化 8.76%" not in strategy.describe_decision()

    def test_容差真的會挑到不是最高分的那一個(self):
        """`_pick_from_plateau()` 本身：**同分那群裡取最高價**，不是取最高分。"""
        strategy = self._strategy(0.5)
        便宜 = self._evaluation(daily(8.76), 7.695058824 / 36500)
        貴 = self._evaluation(daily(8.93), 7.695017700 / 36500)
        assert strategy._pick_from_plateau([便宜, 貴]) == 貴["rate"]
        assert self._strategy(0.0)._pick_from_plateau([便宜, 貴]) == 便宜["rate"]

    def test_沒有選出價位時三個報告端一律回_None(self):
        """🔴 **守門條件是 `last_chosen` 不是 `last_evaluation`。**

        「評估過一輪」與「選出了價位」是兩件事：整組候選的實質年化都是 0 時，
        前者非空而後者是 None。報告端要講的是後者。
        """
        strategy = self._strategy(0.5)
        strategy.last_evaluation = [{"rate": daily(9.0), "effective": 0.0}]
        strategy.last_chosen = None
        assert strategy.pricing_decision() is None
        assert strategy.chosen_forecast() is None
        assert strategy.describe_decision() is None

    def test_新的一輪會把選中的那一列清掉(self):
        """D041 的同一條規矩：**每多一個「本輪的狀態」，就多一個會跨輪殘留的成員。**

        `last_chosen` 是第五個，重置點必須與另外四個在同一處。
        """
        strategy = self._strategy(0.5)
        strategy.choose_rate(self._candles())
        assert strategy.last_chosen is not None
        # 餘額不足會在 `choose_rate()` 之前就 return——正是 D041 那條路。
        strategy.build_offer_plan(1.0, daily(9.0))
        assert strategy.last_chosen is None
        assert strategy.describe_decision() is None


class TestD066W的兩個旋鈕:
    """D045 第三則追記 ＋ D047。**預設值＝現行行為，行為零變化。**

    🔴 **量出來的答案跟 D045 追記說的相反**：`median` 是**更準的預測值**
    （12 個樣本每一個都比較準），**卻是更差的決策規則**（跨 114 個起跑點輸 1.0pp）。
    理由寫在 `test_median比較準卻比較差` 的 docstring 裡。
    """

    @staticmethod
    def _config(**overrides):
        overrides.setdefault("ev_min_hits", 5)
        return base_config(assumed_hold_hours=12, **overrides)

    @staticmethod
    def _candles():
        """真正的陣發：**連中三根，然後乾旱一整段**。

        🔴 **不能用規律的「每 10 根命中一次」**——那樣平均與中位數會完全相等
        （實測兩者都是 5.0h），於是這一組測試看起來會過，卻什麼都沒釘到。
        **平均與中位數只有在不規律的分佈上才分得開**，而這正是 D038 的主題。
        """
        低, 高 = daily(6.0), daily(9.5)
        一輪 = [高, 高, 高] + [低] * 37  # 連中三根 ＋ 37 根乾旱
        return [candle(i, h) for i, h in enumerate(一輪 * 5)]

    def test_預設是mean加window_tail等於現行行為(self):
        strategy = ExpectedValueStrategy(base_config())
        assert strategy.ev_wait_statistic == "mean"
        assert strategy.ev_censoring == "window_tail"

    def test_換統計量會換掉算式吃的那個數字(self):
        """🔴 **比對的是「選中那一列記下的等待」與「設定選的統計量」是否一致**，
        不是「換了旋鈕選價就會變」。

        兩者在多數窗上會選到同一個價位（高原很寬），
        **拿「選價變了」當斷言，就是一條大部分時候會誤紅的測試。**
        """
        candles = self._candles()
        highs = [c["high"] for c in candles]
        for stat in ("mean", "median", "p75"):
            strategy = ExpectedValueStrategy(self._config(ev_wait_statistic=stat))
            chosen = strategy.choose_rate(candles)
            assert chosen is not None
            估 = strategy.estimate_wait(highs, chosen)
            assert strategy.last_chosen["wait_hours"] == 估.statistic(stat)

    def test_陣發分佈上三個統計量真的不一樣(self):
        """**這一條是上一條的前提。** 三者相等的話，上一條就算實作寫錯也會過。"""
        strategy = ExpectedValueStrategy(self._config())
        highs = [c["high"] for c in self._candles()]
        估 = strategy.estimate_wait(highs, daily(9.5))
        assert 估.median_hours < 估.mean_hours < 估.p75_hours

    def test_報出來的與算式用的是同一個數字(self):
        """🔴 **PR #62 的教訓**：`wait_hours` 跟著選定的統計量走，
        於是日誌、`pricing_decisions`、M1-c 的比較全部講同一個數字。"""
        strategy = ExpectedValueStrategy(self._config(ev_wait_statistic="median"))
        strategy.choose_rate(self._candles())
        用出去的 = strategy.last_chosen["wait_hours"]
        assert strategy.pricing_decision()["chosen_mean_hours"] == 用出去的
        assert strategy.chosen_forecast()["mean_hours"] == 用出去的

    def test_認不得的統計量直接拋而不是默默退回mean(self):
        """🔴 **設定檔打錯一個字，後果會是「換了旋鈕但行為沒變」**
        ——而那看起來跟「換了沒有用」一模一樣（D064 的同一個形狀）。"""
        strategy = ExpectedValueStrategy(self._config(ev_wait_statistic="平均"))
        with pytest.raises(ValueError, match="ev_wait_statistic"):
            strategy.choose_rate(self._candles())

    def test_三種設限記帳的方向(self):
        """**三個都是錯的，只是錯的方向不同。**

        🔴 **而「drop 必定最短」是錯的，這是寫這一條時才發現的。**
        `window_tail` 把設限起點記成「等到窗尾」，而**設限起點必定落在窗的後段**
        ——於是它們拿到的是 1 到 N 根這種**很短**的等待，把平均往下拉。
        實測這一組資料：`drop` **46.41h** 對 `window_tail` **40.57h**，
        **現行的記帳法比丟掉還低估。**

        這是 D047「乾旱會讓等待估計自己變好看」的另一個面貌：
        **越晚的起點、越沒等到，記下來的等待反而越短。**

        唯一必然成立的是 `full_window ≥ window_tail`（`total ≥ total − start`）。
        """
        highs = [daily(6.0)] * 100 + [daily(9.5)] * 10 + [daily(6.0)] * 58
        rate = daily(9.5)
        估 = {}
        for cens in ("drop", "window_tail", "full_window"):
            strategy = ExpectedValueStrategy(self._config(ev_censoring=cens))
            估[cens] = strategy.estimate_wait(highs, rate).mean_hours
        assert 估["window_tail"] < 估["full_window"]
        # 🔴 現行記帳法比「整批丟掉」還低估——這一條就是釘住那件事。
        assert 估["window_tail"] < 估["drop"]

    def test_設限比例三種記帳都一樣(self):
        """**`censored` 數的是「有幾個起點沒等到」，那是事實，不是記帳選擇。**

        三種記帳只改變那些起點被記成多長，不改變有幾個。
        """
        highs = [daily(6.0)] * 100 + [daily(9.5)] * 10 + [daily(6.0)] * 58
        比例 = {
            cens: ExpectedValueStrategy(self._config(ev_censoring=cens))
            .estimate_wait(highs, daily(9.5))
            .censored
            for cens in ("drop", "window_tail", "full_window")
        }
        assert len(set(比例.values())) == 1

    def test_drop把整窗丟光時回None而不是零(self):
        """一次都沒命中又選 `drop`，就沒有估計值可給。
        **給 0 會讓那個價位看起來是「秒成交」，也就是最好的候選。**"""
        strategy = ExpectedValueStrategy(self._config(ev_censoring="drop", ev_min_hits=0))
        assert strategy.estimate_wait([daily(6.0)] * 60, daily(20.0)) is None

    def test_兩個旋鈕都在PRICING_KNOBS裡(self):
        """🔴 **D064 的規矩：加旋鈕要一起加進白名單**，
        漏掉的代價是 `--verify` 從那天起開始說謊。"""
        knobs = ExpectedValueStrategy(base_config()).PRICING_KNOBS
        assert "ev_wait_statistic" in knobs
        assert "ev_censoring" in knobs
