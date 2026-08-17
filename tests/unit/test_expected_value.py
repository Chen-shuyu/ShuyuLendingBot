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


class TestEstimateWaitHours:
    """等待時間的估法。"""

    def test_每根都命中時平均等待是半根(self):
        strategy = ExpectedValueStrategy(base_config())
        highs = [daily(10.0)] * 60
        wait, hits = strategy.estimate_wait_hours(highs, daily(9.0))
        assert hits == 60
        assert wait == pytest.approx(0.5)

    def test_陣發與均勻分佈算出來的等待不同(self):
        """這正是不用「命中率取倒數」的理由。

        兩組資料的命中率完全一樣（12/24），但一組是平均散開、一組是擠在一起。
        倒數法會把兩者算成同一個數字，逐根走訪不會。
        """
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=3))
        hi, lo = daily(10.0), daily(5.0)

        均勻 = [hi if i % 2 == 0 else lo for i in range(24)]
        陣發 = [lo] * 12 + [hi] * 12

        wait_均勻, hits_均勻 = strategy.estimate_wait_hours(均勻, daily(9.0))
        wait_陣發, hits_陣發 = strategy.estimate_wait_hours(陣發, daily(9.0))

        assert hits_均勻 == hits_陣發 == 12
        # 均勻：第一根就中（0.5），之後每次都空一根（1.5）
        assert wait_均勻 == pytest.approx((0.5 + 1.5 * 11) / 12)
        # 陣發：先空 12 根才中（12.5），之後連中 11 次（0.5）
        assert wait_陣發 == pytest.approx((12.5 + 0.5 * 11) / 12)
        assert wait_陣發 > wait_均勻

    def test_尾端沒等到的那一段不計入(self):
        """右設限資料當成「等了 N 根就成交」會系統性低估等待。"""
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=2))
        hi, lo = daily(10.0), daily(5.0)
        highs = [hi, hi] + [lo] * 40  # 末尾 40 根一直沒等到

        wait, hits = strategy.estimate_wait_hours(highs, daily(9.0))
        assert hits == 2
        assert wait == pytest.approx(0.5)  # 只有兩次「等半根就中」，尾巴不算

    def test_命中次數不足回傳None(self):
        strategy = ExpectedValueStrategy(base_config(ev_min_hits=5))
        highs = [daily(10.0)] * 4 + [daily(5.0)] * 50
        assert strategy.estimate_wait_hours(highs, daily(9.0)) is None

    def test_candle_hours_會換算成小時(self):
        """K 線改成 4 小時一根時，等待也要跟著變成 4 倍。"""
        strategy = ExpectedValueStrategy(base_config(candle_hours=4.0))
        highs = [daily(10.0)] * 60
        wait, _ = strategy.estimate_wait_hours(highs, daily(9.0))
        assert wait == pytest.approx(2.0)  # 0.5 根 × 4 小時


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
        assert 評估[12.0]["wait_hours"] == pytest.approx(47.7, abs=0.1)
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
        assert 評估[20.0]["wait_hours"] == pytest.approx(8.0)
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
