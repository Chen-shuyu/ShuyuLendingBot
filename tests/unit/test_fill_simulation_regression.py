# -*- coding: utf-8 -*-
"""迴歸釘子：成交模擬在**真實歷史**上必須算出已知的答案（M2 第 2 步）。

與 `test_fill_simulation.py` 的分工同第 1 步：那份測「機制對不對」（合成資料），
**這份測「數字對不對」，資料是 403 根真實 K 線**（約 16.8 天）。

## 這份釘的三件事

1. **成交規則的驗收**——模擬的等待對得上真實成交（總量比 0.93×）。
   **這是整個第 2 步能不能被信任的地基**：規則若對不上，上面的實得年化全是假的。
2. **D1 的方向**——策略假設 `P=48` 的實得年化，低於假設 `P` 較小的那些。
3. 🔴 **以及「這個方向不夠強，不足以拿來改參數」**——切半之後前半的結論
   **反過來**。這一條同樣被釘住，**免得日後只記得第 2 條。**

## 為什麼要釘第 3 條

這個專案有六個決策互相推翻的紀錄（D036），而每一次的形狀都一樣：
**一個時間切片上的結論被當成了通則。** 第 2 條讀起來很像「答案找到了」，
所以第 3 條必須跟它綁在同一個檔案裡，紅燈時一起被看到。
"""

import pytest

from core import fill_simulation as fs
from strategies.expected_value import ExpectedValueStrategy
from tests.unit.candles_full_history import (
    HIGHS_FULL_HISTORY,
    HISTORY_START_MTS,
    REAL_FILLS,
)

CONFIG = {
    "strategy": {
        "ev_window_hours": 168,
        "ev_min_hits": 5,
        "ev_min_candles": 48,
        "candle_hours": 1.0,
        "offer_period": 2,
        "minimum_rate": 0.0001,
    }
}


def history(highs=None):
    highs = HIGHS_FULL_HISTORY if highs is None else highs
    return [
        {"mts": HISTORY_START_MTS + index * 3_600_000, "high": high}
        for index, high in enumerate(highs)
    ]


def run(candles, assumed, hold_model=None):
    """**每次都建新的策略實例**：`choose_rate()` 會把「本輪」的評估結果留在
    成員上（D041 的那四個），共用實例等於讓上一組設定的殘留參與下一組。"""
    return fs.run_policy(
        ExpectedValueStrategy(CONFIG),
        candles,
        hold_model=hold_model or fs.empirical_hold(),
        assumed_hold_hours=assumed,
    )


class Test歷史的形狀:
    def test_根數與長度(self):
        assert len(history()) == 403
        assert len(history()) / 24 == pytest.approx(16.8, abs=0.05)


class TestD1的方向:
    """策略假設借滿 48 小時，而實測完成率只有 47.1%（D040／D057 修正後）。

    🔴 **2026-09-05：這一整組的數字都動了，而動的原因不是策略改了。**
    `OBSERVED_HOLD_HOURS` 原本混進**三筆 `kind='loan'` 的幽靈樣本**（各 0.50h，
    見 D057），佔一袋抽籤的 18%。修掉之後同一段歷史的循環數 15 → 13，
    每個數字都跟著移動。**方向沒有翻**——那才是這一條在釘的東西。
    """

    def test_假設48比假設實測平均差(self):
        寬鬆 = run(history(), 48.0)
        嚴格 = run(history(), 16.93)
        # 修 D057 之前是 6.57 / 7.26。**釘子換值時要寫清楚為什麼**，
        # 否則下一個人只會看到「有人把期望值調成通過」。
        assert 寬鬆.realized_annual_pct == pytest.approx(6.89, abs=0.02)
        assert 嚴格.realized_annual_pct == pytest.approx(7.32, abs=0.02)
        assert 嚴格.realized_annual_pct > 寬鬆.realized_annual_pct

    def test_假設48的成交率比較低(self):
        """掛得太高的代價之一是空掛——而空掛的時間一樣進分母。"""
        寬鬆 = run(history(), 48.0)
        assert 寬鬆.fill_rate < 1.0
        assert run(history(), 16.93).fill_rate == pytest.approx(1.0)

    def test_四種持有模型下方向都一致(self):
        """換掉「實際借多久」的假設，結論不該翻——翻了就代表它只是巧合。"""
        for hold in (
            fs.empirical_hold(),
            fs.fixed_hold(48.0),
            fs.fixed_hold(16.93),
            fs.fixed_hold(11.61),
        ):
            寬鬆 = run(history(), 48.0, hold)
            嚴格 = run(history(), 16.93, hold)
            assert 嚴格.realized_annual_pct > 寬鬆.realized_annual_pct

    def test_就算實際持有真的是48假設48仍不是最好的(self):
        """**這一條是最違反直覺的那個**：即使模型的世界觀完全成立
        （每筆都借滿 48 小時），假設一個較小的 `P` 仍然比較好。

        機制：假設較小的 `P` 讓策略更怕等待，而那正好補償了 `W` 被低估
        （D047 的乾旱回饋圈）。**兩個錯誤部分互相抵銷**——
        所以「把 48 改成實測值」不是一個安全的動作，它會拆掉其中一半。
        """
        寬鬆 = run(history(), 48.0, fs.fixed_hold(48.0))
        嚴格 = run(history(), 16.93, fs.fixed_hold(48.0))
        assert 寬鬆.realized_annual_pct == pytest.approx(7.27, abs=0.02)
        assert 嚴格.realized_annual_pct == pytest.approx(7.61, abs=0.02)


class Test這個方向還不足以拿來改參數:
    """🔴 **這一族與上一族同等重要，不要只記得上一族。**"""

    def test_切半之後前半的結論反過來(self):
        """前半說 48 比較好，後半說 16.93 比較好——**跨時段站不住**。"""
        前半 = history()[: len(HIGHS_FULL_HISTORY) // 2 + 168]
        後半 = history()[len(HIGHS_FULL_HISTORY) // 2 - 168 :]

        前半寬鬆 = run(前半, 48.0).realized_annual_pct
        前半嚴格 = run(前半, 16.93).realized_annual_pct
        後半寬鬆 = run(後半, 48.0).realized_annual_pct
        後半嚴格 = run(後半, 16.93).realized_annual_pct

        assert 前半寬鬆 > 前半嚴格, "前半應該是 48 較好——這正是不能拿去改參數的理由"
        assert 後半嚴格 > 後半寬鬆, "後半應該是 16.93 較好"

    def test_細掃出來的最佳值是雜訊(self):
        """相鄰幾列差 0.1～0.3 個百分點，而曲線不是單調的。

        **挑最高的那一列就是 `target_queue_usd` 的死法**（D032）：
        拿一個十幾天、十幾次循環的樣本去挑一個常數。
        """
        結果 = {
            假設: run(history(), float(假設)).realized_annual_pct
            for 假設 in (20, 18, 16, 14, 12, 10)
        }
        最佳 = max(結果, key=結果.get)
        最差 = min(結果, key=結果.get)
        # 整段區間的高低差很小——小到不足以在這個樣本數下分辨
        assert 結果[最佳] - 結果[最差] < 0.5
        # 而且不是單調的：14 比 16 好，但 12 又比 14 差
        assert 結果[14] > 結果[16]
        assert 結果[12] < 結果[14]

    def test_可重跑(self):
        """回測跑兩次必須同值，否則「這次比較好」永遠分不清是策略還是狀態殘留。

        第一版的 `empirical_hold()` 是有狀態的閉包，同一組設定先後跑出
        7.26% 與 6.70%——**兩個數字看起來都很正常**。
        """
        model = fs.empirical_hold()
        assert run(history(), 16.93, model).realized_annual_pct == pytest.approx(
            run(history(), 16.93, model).realized_annual_pct
        )


class Test成交規則對得上真實成交:
    """🔴 **這一族是整個第 2 步的地基。**

    上面每一個實得年化都站在「`high >= rate` 就會成交」這條規則上。
    規則若對不上真實成交，那些數字全部是假的——而它們看起來會完全正常。
    """

    @staticmethod
    def _spells():
        """把 fixture 還原成 `validate_against_real_fills()` 吃的形狀。"""
        from datetime import datetime

        class _期間:
            censored = False

            def __init__(self, started_at, rate, hours):
                self.started_at = datetime.fromisoformat(started_at)
                self.rate = rate
                self.hours = hours

        return [_期間(*row) for row in REAL_FILLS]

    def test_十二筆全部比對得到(self):
        validation = fs.validate_against_real_fills(self._spells(), history())
        assert len(validation.comparable) == 12

    def test_總量比(self):
        """**要讀的是這個數字**，不是逐筆倍數。

        對照組：策略自己的 `estimate_wait()` 在同一批樣本上是 4.25 倍高估
        （D045）。**模擬器準了一個數量級**，這是它能拿來當裁判的理由。
        """
        validation = fs.validate_against_real_fills(self._spells(), history())
        assert validation.total_ratio() == pytest.approx(0.93, abs=0.01)

    def test_扣掉解析度以下的樣本仍然對得上(self):
        """12 筆裡有 7 筆的實際等待不到一根 K，逐筆倍數在那裡讀不出意思。"""
        validation = fs.validate_against_real_fills(self._spells(), history())
        above = validation.above_resolution
        assert len(above) == 5
        assert validation.total_ratio(above) == pytest.approx(0.95, abs=0.01)

    def test_模擬的成交偏快而不是偏慢(self):
        """`high >= rate` 沒說掃掉的量足夠輪到我們那 345 USD，
        所以模擬一定偏樂觀。**方向要被釘住**——哪天它變成偏慢，
        代表規則或資料出了事。"""
        validation = fs.validate_against_real_fills(self._spells(), history())
        assert validation.total_ratio() < 1.0


class TestA2b重掛政策在這段歷史上分不出勝負:
    """A2-b（D046）的答案是**否定的**，而否定的答案同樣要被釘住。

    五種重掛政策在 403 根真實 K 線上跑出來的實得年化**幾乎完全相同**
    （6.56%～6.57%）。成因不是「沒有機會作用」——等待佔掉整段歷史的 30%
    ——而是**訊號本身太慢**：候選價位來自 168 小時的窗，一場十幾小時的乾旱
    幾乎推不動它（D050）。
    """

    POLICIES = (
        ("never", fs.never_repost()),
        ("tolerance2", fs.rate_tolerance(2.0)),
        ("down_only", fs.down_only(2.0)),
        ("down_after_12.6h", fs.down_after_idle(12.6)),
        ("down_after_18.9h", fs.down_after_idle(18.9)),
    )

    def _run(self, policy):
        return fs.run_policy(
            ExpectedValueStrategy(CONFIG),
            history(),
            hold_model=fs.empirical_hold(),
            assumed_hold_hours=48.0,
            repost_policy=policy,
        )

    def test_五種政策的實得年化幾乎相同(self):
        結果 = [self._run(policy).realized_annual_pct for _, policy in self.POLICIES]
        assert max(結果) - min(結果) < 0.05, f"分得出勝負了，要回頭看 D050：{結果}"

    def test_不是因為沒有機會作用(self):
        """等待佔整段歷史的 27%，其中最長的那一段是 38.5h。

        **「沒機會」與「有機會但訊號太慢」的處置完全不同**，
        所以這一條要跟上一條綁在一起。

        🔴 修 D057 之前是 30%。**幽靈樣本讓每一筆看起來借得比較短，
        於是等待在分母裡的佔比被推高**——那三筆 0.50h 的假持有，
        正好是「等待佔比」這個量最敏感的方向。
        """
        outcome = self._run(None)
        等待 = sum(cycle.wait_hours for cycle in outcome.cycles)
        持有 = sum(cycle.hold_hours or 0.0 for cycle in outcome.cycles)
        assert 等待 / (等待 + 持有 + outcome.idle_hours) == pytest.approx(0.27, abs=0.02)
        assert max(cycle.wait_hours for cycle in outcome.cycles) == pytest.approx(
            38.5, abs=0.1
        )

    def test_訊號太慢是因為窗太長(self):
        """最長那段空掛裡，候選價位**前 32 小時完全沒動**，
        直到第 163 根才掉到差 2.88%（剛好越過 2% 容差）——
        而那時候那段等待已經走完 83%。
        """
        from core import backtest

        起點 = 131
        掛著 = backtest.replay_at(ExpectedValueStrategy(CONFIG), history()[: 起點 + 1])
        assert 掛著.chosen_annual_pct == pytest.approx(9.78, abs=0.01)

        # 32 小時之後才第一次有差距
        第32小時 = backtest.replay_at(
            ExpectedValueStrategy(CONFIG), history()[: 起點 + 32 + 1]
        )
        漂移 = abs(第32小時.chosen_rate - 掛著.chosen_rate) / 掛著.chosen_rate * 100
        assert 漂移 > 2.0

        # 而在那之前（第 28 小時）還是一動也不動
        第28小時 = backtest.replay_at(
            ExpectedValueStrategy(CONFIG), history()[: 起點 + 28 + 1]
        )
        assert 第28小時.chosen_rate == 掛著.chosen_rate


class TestD047的機制不是永遠同一個方向:
    """🔴 **D047 的追記**：乾旱把估計拉好看，**只在乾旱還短的時候成立**。

    兩段空掛，方向相反：

    | 空掛 | 典型等待 | 乾旱長度 | `W` 平均怎麼走 |
    |---|---|---|---|
    | 第 387 根起（D047 記的那段） | ~10h | 16h | **10.52 → 7.33，變好看** |
    | 第 131 根起（38.5h 那段） | ~5.9h | 33h | **5.88 → 8.14，變難看** |

    機制：設限的起點記「至少等到窗尾」，最後 `k` 根貢獻的是 `k, k-1, …, 1`，
    平均約 `k/2`。**`k/2` 小於典型等待時把平均拉低，大於時把平均拉高。**
    D047 觀察到的是前者，而它不是通則。
    """

    @staticmethod
    def _wait_mean(end_index, rate):
        import statistics

        highs = [candle["high"] for candle in history()[: end_index + 1]][-168:]
        total = len(highs)
        nxt, upcoming = [None] * total, None
        for i in range(total - 1, -1, -1):
            if highs[i] >= rate:
                upcoming = i
            nxt[i] = upcoming
        waits = [
            (total - s) if nxt[s] is None else (nxt[s] - s + 0.5) for s in range(total)
        ]
        return statistics.fmean(waits)

    def test_長乾旱反而把估計推難看(self):
        from core import backtest

        rate = backtest.replay_at(
            ExpectedValueStrategy(CONFIG), history()[:132]
        ).chosen_rate
        開頭 = self._wait_mean(131, rate)
        乾旱32小時後 = self._wait_mean(163, rate)
        assert 開頭 == pytest.approx(5.88, abs=0.02)
        assert 乾旱32小時後 == pytest.approx(8.14, abs=0.02)
        assert 乾旱32小時後 > 開頭, "這一段的方向與 D047 相反，追記講的就是這件事"


class TestD054訊號偵測得很好:
    """D054 上半場：`stale_ratio` 分得開「長等待」與「快速成交」。

    🔴 **2026-09-05：修掉 D057 的幽靈樣本之後，「零誤報」不成立了。**
    舊的一袋抽籤裡有三筆假的 0.50h 持有，讓同一段歷史多跑出兩個循環，
    而那兩個都是安靜的快速成交。拿掉之後：

    | | 修 D057 之前 | 修 D057 之後 |
    |---|---|---|
    | 長等待／快速成交 | 5／10 | **4／9** |
    | 命中 | 5/5 | **4/4** |
    | 誤報 | **0/10** | **1/9** |

    **門檻不敏感這一半仍然成立**（1.5× 到 4× 完全同一組結果），
    但「零誤報」要改成「一次誤報」——**而那一次在每個門檻上都發生**，
    所以它不是門檻挑錯，是訊號本身就會在那一段亮燈。

    ⚠ **D054 的下半場（拿它降價賠 1.97pp）不受影響**，那才是它的結論。
    這裡動到的是「偵測得多好」，不是「該不該用」。
    """

    @staticmethod
    def _cycles():
        return fs.run_policy(
            ExpectedValueStrategy(CONFIG),
            history(),
            hold_model=fs.empirical_hold(),
            assumed_hold_hours=48.0,
        ).cycles

    @staticmethod
    def _fires(cycle, threshold):
        highs = [candle["high"] for candle in history()]
        for hour in range(0, int(cycle.wait_hours) + 1):
            ratio = fs.stale_ratio(highs, cycle.decided_index + hour, cycle.rate)
            if ratio is not None and ratio >= threshold:
                return hour
        return None

    def test_四段長等待全部發話而快速成交誤報一次(self):
        """**改名了，因為它釘的事實變了**（見類別 docstring）。

        留著「誤報一次」而不是把它放寬成「誤報 ≤ 1」：**釘子要釘住現況，
        不是釘住一個容忍區間**——變成 2 次的時候要有人被吵醒。
        """
        cycles = self._cycles()
        長 = [c for c in cycles if c.wait_hours >= 6]
        短 = [c for c in cycles if c.wait_hours < 6]
        assert len(長) == 4 and len(短) == 9
        assert all(self._fires(c, 3.0) is not None for c in 長)
        assert sum(1 for c in 短 if self._fires(c, 3.0) is not None) == 1

    def test_門檻不敏感(self):
        """🔴 **這一條是它與 `target_queue_usd` 的差別**：
        1.5× 到 4× 都是 4/4 命中、1/9 誤報，**不是挑出來的一個點**。

        **誤報那一次在五個門檻上完全一致**——所以它不是門檻挑錯，
        是訊號本身就會在那一段亮燈（見類別 docstring）。
        """
        cycles = self._cycles()
        長 = [c for c in cycles if c.wait_hours >= 6]
        短 = [c for c in cycles if c.wait_hours < 6]
        for threshold in (1.5, 2.0, 2.5, 3.0, 4.0):
            assert all(self._fires(c, threshold) is not None for c in 長), threshold
            誤報 = sum(1 for c in 短 if self._fires(c, threshold) is not None)
            assert 誤報 == 1, (threshold, 誤報)

    def test_比候選價位快得多(self):
        """對照組：候選價位在 5 段長等待裡**只有 1 段發話，而且在第 30 小時**。"""
        from core import backtest

        cycles = [c for c in self._cycles() if c.wait_hours >= 6]
        候選發話 = 0
        for cycle in cycles:
            for hour in range(0, int(cycle.wait_hours) + 1):
                point = backtest.replay_at(
                    ExpectedValueStrategy(CONFIG),
                    history()[: cycle.decided_index + hour + 1],
                )
                if point.chosen_rate and (
                    (cycle.rate - point.chosen_rate) / cycle.rate * 100 > 2
                ):
                    候選發話 += 1
                    break
        assert 候選發話 == 1
        assert all(self._fires(c, 3.0) <= 11 for c in cycles)

    def test_命中次數為零時不給數字(self):
        """這個價位在窗內從沒被掃到過，就沒有「常態」可以比。"""
        highs = [0.00015] * 168
        assert fs.stale_ratio(highs, 167, 0.00099) is None


class TestD054但拿它降價是賠錢的:
    """D054 下半場。🔴 **與上半場同等重要，不要只記得上半場。**

    偵測得好 ≠ 知道該做什麼。降價會把一個較差的利率**鎖住最多 48 小時**，
    而省下來的只是一段等待——**贏很多次、輸很大次**。
    """

    STARTS = tuple(range(48, 220, 8))

    def _run(self, policy):
        highs = [candle["high"] for candle in history()]
        return fs.run_policy_across_starts(
            lambda: ExpectedValueStrategy(CONFIG),
            history(),
            self.STARTS,
            hold_model=fs.empirical_hold(),
            assumed_hold_hours=48.0,
            repost_policy=policy(highs) if policy else None,
        )

    def test_平均起來比不重掛差(self):
        baseline = self._run(None)
        candidate = self._run(lambda highs: fs.down_when_stale(highs, 3.0, 24))
        result = fs.compare_across_starts(baseline, candidate)
        assert result["difference"] < 0, result

    def test_單一起跑點會給出相反的答案(self):
        """🔴 **這一條是這一族存在的理由。**

        同一個政策，單一起跑點看起來**贏**，平均掉相位運氣之後**輸**。
        D049 與 D050 都是拿單一起跑點跑出來的。
        """
        highs = [candle["high"] for candle in history()]
        single_base = fs.run_policy(
            ExpectedValueStrategy(CONFIG), history(),
            hold_model=fs.empirical_hold(), assumed_hold_hours=48.0,
        ).realized_annual_pct
        single_cand = fs.run_policy(
            ExpectedValueStrategy(CONFIG), history(),
            hold_model=fs.empirical_hold(), assumed_hold_hours=48.0,
            repost_policy=fs.down_when_stale(highs, 3.0, 24),
        ).realized_annual_pct
        assert single_cand > single_base, "單一起跑點上它是贏的"

        result = fs.compare_across_starts(
            self._run(None), self._run(lambda h: fs.down_when_stale(h, 3.0, 24))
        )
        assert result["difference"] < 0, "平均掉相位之後它是輸的"

    def test_勝率與平均會給出相反的結論(self):
        """`lookback=12` 贏過半數的起跑點，但平均仍然輸——**只看勝率會看錯**。"""
        result = fs.compare_across_starts(
            self._run(None), self._run(lambda h: fs.down_when_stale(h, 3.0, 12))
        )
        assert result["candidate_wins"] > result["samples"] / 2
        assert result["difference"] < 0


class TestD055跨起跑點重做D049:
    """🔴 **D049 的兩條「不能改」的理由，在正確的方法下都不成立。**

    D049 用單一起跑點得到兩個結論，而 D054 證明單一起跑點會被相位運氣主導：

    | D049 說的（單跑一次） | 跨起跑點重做的結果 |
    |---|---|
    | 切半之後**前半的結論反過來** | **三段全部同向** |
    | 細掃是雜訊、曲線不單調 | **從 48h 往下單調上升，8～20h 是一片高原** |

    **一片高原正是 `target_queue_usd` 失敗模式的反面**：那次是一個手算出來、
    沒有高原的常數；這次是任何落在 8～20h 的值都給幾乎一樣的結果，
    **而實測持有的平均（16.93h）與中位數（11.61h）都在高原裡**。
    """

    STARTS = tuple(range(48, 220, 16))

    def _mean(self, assumed, series=None, starts=None):
        import statistics

        outcomes = fs.run_policy_across_starts(
            lambda: ExpectedValueStrategy(CONFIG),
            series if series is not None else history(),
            starts if starts is not None else self.STARTS,
            hold_model=fs.empirical_hold(),
            assumed_hold_hours=assumed,
        )
        values = [o.realized_annual_pct for o in outcomes if o.realized_annual_pct is not None]
        return statistics.fmean(values)

    def test_假設較小的P比較好(self):
        assert self._mean(11.61) > self._mean(48.0)

    def test_切半之後兩半同向(self):
        """🔴 **這一條推翻 D049 的第一個「不能改」的理由。**"""
        half = len(HIGHS_FULL_HISTORY) // 2
        starts = tuple(range(48, 150, 12))
        前半, 後半 = history()[: half + 168], history()[half - 168 :]
        assert self._mean(11.61, 前半, starts) > self._mean(48.0, 前半, starts)
        assert self._mean(11.61, 後半, starts) > self._mean(48.0, 後半, starts)

    def test_從48往下是單調的不是雜訊(self):
        """🔴 **這一條推翻 D049 的第二個理由。**"""
        序列 = [self._mean(float(a)) for a in (48, 32, 24, 20, 16)]
        assert 序列 == sorted(序列), 序列

    def test_有一片高原而不是一個尖點(self):
        """8～20h 之間差不到 0.2 個百分點——**任何落在裡面的值都一樣好**。"""
        高原 = [self._mean(float(a)) for a in (8, 12, 16, 20)]
        assert max(高原) - min(高原) < 0.2, 高原

    def test_實測持有落在高原裡(self):
        """平均 16.93h 與中位數 11.61h **都在 8～20h 之間**
        ——所以「換成實測值」不再是憑空拍一個常數。"""
        assert 8 <= 16.93 <= 20
        assert 8 <= 11.61 <= 20


class TestD055任何往下走的機制不是都賠錢:
    """🔴 **D054 下半場的推論範圍要收窄。**

    D054 量到兩個「因為等太久就降價」的機制都賠錢，我當時差點寫成
    「任何往下走的機制都賠錢」。**對照組推翻了那個推論**：
    不看任何訊號、單純把價位往下平移 5～20%，是**賺**的。

    **輸的不是方向，是那兩個機制**——它們反應的是「已經等很久」，
    於是在燒掉一段等待之後才降，而且降的幅度由乾旱深度決定（可能過頭）。
    """

    STARTS = tuple(range(48, 220, 16))

    def _shifted(self, pct):
        import statistics

        class _平移(ExpectedValueStrategy):
            def choose_rate(self, candles):
                rate = super().choose_rate(candles)
                return rate * (1 + pct / 100) if rate else rate

        outcomes = fs.run_policy_across_starts(
            lambda: _平移(CONFIG),
            history(),
            self.STARTS,
            hold_model=fs.empirical_hold(),
            assumed_hold_hours=48.0,
        )
        return statistics.fmean(
            [o.realized_annual_pct for o in outcomes if o.realized_annual_pct is not None]
        )

    def test_往下平移是賺的(self):
        基準 = self._shifted(0)
        assert self._shifted(-10) > 基準
        assert self._shifted(-5) > 基準

    def test_往上平移是賠的(self):
        """方向確實是「現在掛太貴」，不是「隨便動都會變好」。"""
        assert self._shifted(+10) < self._shifted(0)

    def test_兩條獨立的路徑指向同一個幅度(self):
        """純平移的最佳點在 −10% 附近；把 `P` 換成實測值讓選中價位下移約 16%。
        **兩條完全獨立的路徑指向同一個量級**——這是這次最強的一組證據。"""
        assert self._shifted(-10) > self._shifted(-30)
        assert self._shifted(-10) > self._shifted(0)


class TestD062換掉裁判之後結論沒有翻:
    """🔴 **這一組釘的是一個「否定」的結果，而否定的結果一樣會漂。**

    D062 說回測不能當裁判，因為 `empirical_hold()` 假設 `P ⊥ r`，
    而漲價正好是 `P(r)` 會影響的那件事——**用一個假設 `P ⊥ r` 的模擬器
    去檢驗「`P` 是不是 `r` 的函式」，是用結論證明結論**。

    修好之後兩個裁判並排跑，**結論沒有翻**：兩邊都指向同一個方向、
    最佳的假設 `P` 也是同一個。**這一組把那件事釘住**，
    因為將來換樣本、換分界線時它可能就翻了，而那時候要有人被吵醒。
    """

    @staticmethod
    def _run(hold_model, assumed):
        return run(history(), assumed, hold_model=hold_model)

    @pytest.mark.parametrize("assumed", [12.0, 16.93])
    def test_兩個裁判都說假設48比較差(self, assumed):
        for model in (fs.empirical_hold(), fs.rate_dependent_hold()):
            寬鬆 = self._run(model, 48.0).realized_annual_pct
            嚴格 = self._run(model, assumed).realized_annual_pct
            assert 嚴格 > 寬鬆, (model, assumed)

    def test_兩個裁判的差距小於它們與48的差距(self):
        """**換裁判動的量，比它要回答的那個問題小一個量級。**

        這一條講的是「為什麼結論沒翻」：不是兩個裁判剛好同分，
        是它們的分歧遠小於 `P=12` 與 `P=48` 之間的差距。

        🔴 **一定要跨起跑點**（D054 的硬規矩）。這一條第一次寫成單一起跑點時
        量到「換裁判 0.24pp、換假設 0.36pp」——**看起來兩者同一個量級**，
        而跨 22 個起跑點平均掉之後是 **0.03pp 對 1.84pp**。
        **單一起跑點的相位運氣就足以讓這個結論反過來。**
        """
        import statistics

        candles = history()
        starts = list(range(168, len(candles) - 48, 8))
        assert len(starts) >= 20, "起跑點太少，這一條會被相位運氣主導"

        def mean_for(model, assumed):
            outcomes = fs.run_policy_across_starts(
                lambda: ExpectedValueStrategy(CONFIG),
                candles,
                starts,
                hold_model=model,
                assumed_hold_hours=assumed,
            )
            return statistics.fmean(
                o.realized_annual_pct
                for o in outcomes
                if o.realized_annual_pct is not None
            )

        emp12 = mean_for(fs.empirical_hold(), 12.0)
        rdh12 = mean_for(fs.rate_dependent_hold(), 12.0)
        emp48 = mean_for(fs.empirical_hold(), 48.0)
        換裁判 = abs(rdh12 - emp12)
        換假設 = abs(emp12 - emp48)
        assert 換裁判 < 換假設 / 3, (換裁判, 換假設)
