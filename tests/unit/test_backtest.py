# -*- coding: utf-8 -*-
"""`core/backtest.py` 的單元測試（M2 第 1 步）。

這個模組只做一件事：**把時間倒回去，問策略當時會選什麼**。所以測試分成三半：

1. **算得對不對**——重播點數、切窗、沒選出價位時的理由。
2. **會不會偷看未來**——這一半是重點。偷看未來的回測一定會很好看，
   而且看起來完全正常，所以它必須被**釘死**而不是被相信。
3. **旋鈕轉完有沒有還原**——`assumed_hold_hours()` 會把 `offer_period` 改成
   小數，而那個值在正式路徑上是要送給交易所的天期。沒還原就是把回測的
   假設漏進正式環境，而且不會有任何錯誤訊息。

**測試資料用真實量級**（2026-08-30 那 168 根 1 小時 K 線的形狀），
不用 1／2／3 這種漂亮數字——D027 的教訓。
"""

import pytest

from core import backtest
from strategies.expected_value import ExpectedValueStrategy


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


def candle(mts, high, low=0.00014999):
    """一根 `market_candles` 的形狀（只有 `high` 與 `mts` 會被策略讀到）。"""
    return {
        "mts": mts,
        "open": low,
        "close": low,
        "high": high,
        "low": low,
        "volume": 1_000_000.0,
    }


def build_candles(highs, start_mts=1_788_000_000_000):
    """由舊到新的 K 線序列，一小時一根。"""
    return [candle(start_mts + index * 3_600_000, high) for index, high in enumerate(highs)]


def strategy():
    return ExpectedValueStrategy(CONFIG)


# 一段有形狀的市場：低檔為主，偶爾被掃到高檔。
# 量級取自 2026-08 的實際 `high`（年化 5.5%～11.5% ≈ 日利率 0.00015～0.00031）。
BURSTY = ([0.00015] * 8 + [0.00029879] + [0.00016] * 5 + [0.00031416] + [0.000155] * 5) * 6


class Test重播的基本形狀:
    def test_每根K一個重播點(self):
        candles = build_candles(BURSTY)
        result = backtest.replay(strategy(), candles)
        assert len(result.points) == len(candles)
        assert result.candles_supplied == len(candles)

    def test_step跳著重播(self):
        candles = build_candles(BURSTY)
        result = backtest.replay(strategy(), candles, step=6)
        assert len(result.points) == (len(candles) + 5) // 6

    def test_step小於1直接拒絕(self):
        with pytest.raises(ValueError):
            backtest.replay(strategy(), build_candles(BURSTY), step=0)

    def test_K線不足時說出是哪個出口(self):
        """兩種「沒選出價位」的成因不可以共用一個 None（A1 修過的那個病）。"""
        result = backtest.replay(strategy(), build_candles(BURSTY[:60]))
        early = result.points[0]
        assert early.chosen_rate is None
        assert "ev_min_candles" in early.skip_reason

    def test_選出價位的點帶著完整的等待分佈(self):
        """三個統計量都要留著——D045 的問題正是「該用哪一個」。"""
        result = backtest.replay(strategy(), build_candles(BURSTY))
        point = result.decided[-1]
        assert point.chosen_rate is not None
        assert point.chosen_wait_mean is not None
        assert point.chosen_wait_median is not None
        assert point.chosen_wait_p75 is not None
        assert point.chosen_censored_ratio is not None

    def test_年化換算(self):
        result = backtest.replay(strategy(), build_candles(BURSTY))
        point = result.decided[-1]
        assert point.chosen_annual_pct == pytest.approx(point.chosen_rate * 365 * 100)


class Test不許偷看未來:
    """這一半是重點。偷看未來的回測會很好看，而且看起來完全正常。"""

    def test_每個重播點只看得到自己以前的K線(self):
        candles = build_candles(BURSTY)
        seen = []

        class 記錄看到幾根(ExpectedValueStrategy):
            def choose_rate(self, candles):
                seen.append(len(candles))
                return super().choose_rate(candles)

        backtest.replay(記錄看到幾根(CONFIG), candles)
        assert seen == list(range(1, len(candles) + 1))

    def test_後面的K線改掉不會影響前面的重播點(self):
        """真正的防線：把未來換掉，過去的答案必須一個字都不變。"""
        candles = build_candles(BURSTY)
        cut = 200

        前半 = backtest.replay(strategy(), candles[:cut])
        # 把 `cut` 之後全部換成一個從沒出現過的高價。能偷看未來的話，
        # 前半的選擇一定會被它拉走。
        動過手腳 = candles[:cut] + [candle(c["mts"], 0.00099) for c in candles[cut:]]
        全長 = backtest.replay(strategy(), 動過手腳)

        assert [p.chosen_rate for p in 全長.points[:cut]] == [
            p.chosen_rate for p in 前半.points
        ]

    def test_重播點的時間就是那根K的時間(self):
        candles = build_candles(BURSTY)
        result = backtest.replay(strategy(), candles)
        assert [p.mts for p in result.points] == [c["mts"] for c in candles]


class Test旋鈕轉完要還原:
    def test_assumed_hold_hours離開後還原(self):
        s = strategy()
        原值 = s.assumed_hold_hours
        with backtest.assumed_hold_hours(s, 16.93):
            assert s.assumed_hold_hours == pytest.approx(16.93)
        assert s.assumed_hold_hours == 原值

    def test_不會動到送給交易所的合約天期(self):
        """🔴 **D056**：`offer_period` 是合約條款（交易所最短 2 天），
        `assumed_hold_hours` 是算式裡的估計。**重播只准動後者。**

        在 2026-08-30 拆開之前，這支會把合約天期一起改成小數
        ——重播時沒事，但那個耦合讓「把假設改成 12 小時」在正式環境做不到。
        """
        s = strategy()
        with backtest.assumed_hold_hours(s, 12.0):
            assert s.offer_period == 2
        assert s.offer_period == 2

    def test_中途爆掉也要還原(self):
        """`finally` 不是防禦性寫法，是這個設計成立的前提。"""
        s = strategy()
        原值 = s.assumed_hold_hours
        with pytest.raises(RuntimeError):
            with backtest.assumed_hold_hours(s, 11.61):
                raise RuntimeError("模擬策略在重播中途爆掉")
        assert s.assumed_hold_hours == 原值

    def test_None代表不轉這個旋鈕(self):
        s = strategy()
        原值 = s.assumed_hold_hours
        with backtest.assumed_hold_hours(s, None):
            assert s.assumed_hold_hours == 原值
        assert s.assumed_hold_hours == 原值

    def test_replay跑完不留痕跡(self):
        s = strategy()
        原值 = s.assumed_hold_hours
        backtest.replay(s, build_candles(BURSTY), hold_hours=16.93)
        assert s.assumed_hold_hours == 原值

    def test_每個重播點都記著當時的假設(self):
        result = backtest.replay(strategy(), build_candles(BURSTY), hold_hours=16.93)
        assert result.hold_hours == pytest.approx(16.93)
        assert all(p.hold_hours == pytest.approx(16.93) for p in result.points)


class TestD064整組旋鈕都要能還原:
    """🔴 **這一組釘的是一份靜默失效了六天的驗收工具。**

    2026-08-30 D056 把 `assumed_hold_hours` 從 48 改成 12 的當下，`--verify`
    就開始拿**今天的**設定去重跑**當初的**決策——40 列裡 34 列「不一致」，
    而那 34 列一列都沒錯。**它報的是「不一致」，跟「工具壞了」長得一模一樣**，
    所以六天沒有人發現（D064）。
    """

    def test_整組旋鈕轉完全部還原(self):
        s = strategy()
        原值 = {name: getattr(s, name) for name in s.PRICING_KNOBS}
        with backtest.pricing_knobs(
            s, {"assumed_hold_hours": 48.0, "ev_plateau_tolerance_pct": 3.0}
        ):
            assert s.assumed_hold_hours == pytest.approx(48.0)
            assert s.ev_plateau_tolerance_pct == pytest.approx(3.0)
        assert {name: getattr(s, name) for name in s.PRICING_KNOBS} == 原值

    def test_中途爆掉也要還原(self):
        s = strategy()
        原值 = s.ev_plateau_tolerance_pct
        with pytest.raises(RuntimeError):
            with backtest.pricing_knobs(s, {"ev_plateau_tolerance_pct": 3.0}):
                raise RuntimeError("模擬策略在重播中途爆掉")
        assert s.ev_plateau_tolerance_pct == 原值

    def test_白名單外的鍵不會被掛上去(self):
        """🔴 **那一列 JSON 是好幾週前寫的，不可以讓它往策略身上掛任何屬性。**"""
        s = strategy()
        with backtest.pricing_knobs(
            s, {"minimum_rate": 0.9, "任意屬性": 1, "assumed_hold_hours": 24.0}
        ):
            assert s.assumed_hold_hours == pytest.approx(24.0)
            assert s.minimum_rate != 0.9
            assert not hasattr(s, "任意屬性")

    def test_認不得的鍵要回報而不是吞掉(self):
        """**「重播對不上」與「重播還原不了」是兩件事**，而它們長得一樣。"""
        s = strategy()
        assert backtest.unknown_knobs(s, {"assumed_hold_hours": 12.0}) == []
        assert backtest.unknown_knobs(
            s, {"某個未來的旋鈕": 1, "另一個": 2}
        ) == ["另一個", "某個未來的旋鈕"]

    def test_空的或None都當作不轉(self):
        s = strategy()
        原值 = s.assumed_hold_hours
        for knobs in (None, {}):
            with backtest.pricing_knobs(s, knobs):
                assert s.assumed_hold_hours == 原值
            assert s.assumed_hold_hours == 原值

    def test_策略自己宣告的白名單涵蓋所有會改變答案的旋鈕(self):
        """🔴 **加旋鈕時漏掉這份清單，`--verify` 就從那天起開始說謊。**

        這一條擋不住「忘了加」，但它擋得住「加了一個名字打錯的」——
        清單上的每一個都必須真的是策略身上的屬性。
        """
        s = strategy()
        for name in s.PRICING_KNOBS:
            assert hasattr(s, name), name

    def test_類別預設等於那個旋鈕不存在時的行為(self):
        """🔴 **這是舊列還原的全部依據**（`_legacy_knobs()`）。

        `pricing_knobs_json` 是 2026-09-05 才加的欄位，比它更早的列只能靠
        「類別預設＝旋鈕不存在時的行為」這條慣例還原。**這一條把那條慣例
        變成會紅的測試**——哪天有人加了一個「預設值就改變行為」的旋鈕，
        這裡不會紅，但下面那一條會提醒他該做什麼。
        """
        預設 = ExpectedValueStrategy({}).pricing_knobs()
        # 容差預設 0 = 嚴格取最大、平手偏便宜 = D061 之前的行為。
        assert 預設["ev_plateau_tolerance_pct"] == 0.0
        # `assumed_hold_hours` 預設退回合約天期 = D056 之前的行為。
        assert 預設["assumed_hold_hours"] == pytest.approx(48.0)


class TestP掃描:
    def test_P越小越懲罰等待(self):
        """`eff = r × P ÷ (W + P)`：`P` 很大時等待幾乎不被懲罰（D047／D1）。

        **這是機制測試，不是門檻測試**——不釘死具體價位，只釘死方向。
        """
        candles = build_candles(BURSTY)
        rows = backtest.sweep_hold_hours(strategy(), candles, [48.0, 11.61])
        寬鬆, 嚴格 = rows
        assert 寬鬆.chosen_rate is not None and 嚴格.chosen_rate is not None
        assert 嚴格.chosen_rate <= 寬鬆.chosen_rate

    def test_掃描不改動策略(self):
        s = strategy()
        原值 = s.assumed_hold_hours
        backtest.sweep_hold_hours(s, build_candles(BURSTY), [48.0, 16.93, 11.61])
        assert s.assumed_hold_hours == 原值

    def test_每一列都記著自己的假設(self):
        rows = backtest.sweep_hold_hours(
            strategy(), build_candles(BURSTY), [48.0, 16.93]
        )
        assert [row.hold_hours for row in rows] == [48.0, 16.93]


class Test重播的是策略本尊:
    """M2 的驗收標準靠這件事成立：重播與正式環境跑的必須是同一條路徑。"""

    def test_重播的選擇與直接呼叫choose_rate相同(self):
        candles = build_candles(BURSTY)
        result = backtest.replay(strategy(), candles)

        直接算 = strategy().choose_rate(candles)
        assert result.points[-1].chosen_rate == 直接算

    def test_實質年化取自策略自己的候選集(self):
        """不在這裡重算 `r × P ÷ (W + P)`——重算一次就等於多一份會漂的實作。"""
        candles = build_candles(BURSTY)
        s = strategy()
        result = backtest.replay(s, candles)
        point = result.points[-1]

        s2 = strategy()
        s2.choose_rate(candles)
        對應 = [e for e in s2.last_evaluation if e["rate"] == point.chosen_rate][0]
        assert point.chosen_effective == 對應["effective"]
        assert point.chosen_wait_mean == 對應["wait_hours"]
