# -*- coding: utf-8 -*-
"""迴歸釘子：重播器在**一份真實的歷史**上必須算出**已知的答案**。

這是 M2 的驗收標準（PLAN.md 第 1 期）的可跑版本。與 `test_backtest.py` 的差別：
那份測的是「機制對不對」（用得出形狀就好的合成資料），**這份測的是
「數字對不對」，而且數字來自正式環境**。

## 三個釘子分別釘什麼

| 釘子 | 值 | 從哪裡來 |
|---|---|---|
| `P = 48h`（模型寫死的） | 選中 **10.91%**、實質 **9.46%**、`W` 平均 **7.33h** | **正式環境的 `pricing_decisions` 第 118 列**（2026-08-30 12:05:39） |
| `P = 16.93h`（實測平均持有） | 選中 **9.09%** | 2026-08-30 的離線試算 |
| 乾旱把估計拉好看（D047） | 窗尾往回退 16h → 實質 **8.95%**，往回 0h → **9.46%** | 同上，並與 DB 逐列吻合 |

**第一個釘子是關鍵的那一個**：它的期望值不是這份測試自己算出來的，
是機器人當時真的寫進 DB 的那一列。**對不上就代表重播器偏離了正式環境**，
而那正是 PLAN.md 說的「重現不出來就是工具不對，不是策略對」。

⚠ **這三個釘子不代表策略是對的。** 它們只說「同一份輸入算出同一個答案」。
10.91% 那個決定好不好，要等 M2 第 2 步（成交模擬）才答得出來。

⚠ **釘子會因為「刻意改了策略」而斷，那時候要改的是釘子不是策略**
——但改之前要先確定那是刻意的。這正是釘子的用途。
"""

import pytest

from core import backtest
from strategies.expected_value import ExpectedValueStrategy
from tests.unit.candles_2026_08_30 import (
    HIGHS_2026_08_30,
    SERIES_START_MTS,
    WINDOW_LATEST_MTS,
)

# 與 config.yaml 當時的值一致。**寫死在這裡而不是讀 config.yaml**：
# 釘子要釘的是一個不會再變的時刻，讀設定檔會讓它跟著設定一起漂。
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


def candles(highs=None):
    """把那 200 根 `high` 還原成 `choose_rate()` 吃的形狀（窗長由策略自己取最後 168 根）。"""
    highs = HIGHS_2026_08_30 if highs is None else highs
    return [
        {
            "mts": SERIES_START_MTS + index * 3_600_000,
            "open": high,
            "close": high,
            "high": high,
            "low": high,
            "volume": 1_000_000.0,
        }
        for index, high in enumerate(highs)
    ]


def strategy():
    return ExpectedValueStrategy(CONFIG)


class Test對得上正式環境:
    """期望值取自 `pricing_decisions` 第 118 列（2026-08-30 12:05:39 CST）。"""

    def test_窗尾那根K就是正式環境那一輪的窗尾(self):
        assert candles()[-1]["mts"] == WINDOW_LATEST_MTS

    def test_選中的價位(self):
        point = backtest.replay_at(strategy(), candles())
        # DB 存的 chosen_rate 是 0.00029879（年化 10.906…%）
        assert point.chosen_rate == pytest.approx(0.00029879, abs=1e-11)
        assert point.chosen_annual_pct == pytest.approx(10.91, abs=0.005)

    def test_選中價位的實質年化(self):
        point = backtest.replay_at(strategy(), candles())
        # DB 存的 chosen_effective 是 0.0002592192103281334
        assert point.chosen_effective == pytest.approx(0.0002592192103281334, rel=1e-9)
        assert point.effective_annual_pct == pytest.approx(9.46, abs=0.005)

    def test_選中價位的等待估計三個統計量(self):
        """DB 存的是 mean 7.3273809523809526／median 4.5／p75 11.5。"""
        point = backtest.replay_at(strategy(), candles())
        assert point.chosen_wait_mean == pytest.approx(7.3273809523809526, rel=1e-12)
        assert point.chosen_wait_median == pytest.approx(4.5)
        assert point.chosen_wait_p75 == pytest.approx(11.5)

    def test_候選集大小(self):
        """DB 存的 candidate_count 是 132。"""
        point = backtest.replay_at(strategy(), candles())
        assert point.candidate_count == 132


class TestP換掉之後模型會被推到哪裡:
    """D1 的問題。**這張表回答「會選什麼」，不回答「哪個賺比較多」。**"""

    def test_P換成實測平均持有(self):
        rows = backtest.sweep_hold_hours(strategy(), candles(), [16.93])
        assert rows[0].chosen_annual_pct == pytest.approx(9.09, abs=0.005)

    def test_P從48一路縮下來選中價位單調不上升(self):
        """機制：`P` 很大時 `P/(W+P)` → 1，等待幾乎不被懲罰（D047 的算式那段）。"""
        rows = backtest.sweep_hold_hours(
            strategy(), candles(), [48.0, 25.84, 16.93, 11.61, 1.84]
        )
        選中 = [row.chosen_rate for row in rows]
        assert all(值 is not None for 值 in 選中)
        assert 選中 == sorted(選中, reverse=True)

    def test_寫死48讓模型多掛了將近兩個百分點(self):
        rows = backtest.sweep_hold_hours(strategy(), candles(), [48.0, 16.93])
        寬鬆, 嚴格 = rows
        assert 寬鬆.chosen_annual_pct - 嚴格.chosen_annual_pct == pytest.approx(
            1.82, abs=0.02
        )


class Test乾旱期會讓估計自己變好看:
    """D047 的迴歸釘子。**這個機制目前還在，測試釘住的是「它還在」。**

    ⚠ 修掉它的時候這一族測試會整批變紅——**那是預期的**，不是壞掉。
    到那一天要做的是把期望值換成新的行為，並在 D047 補一則追記說明換了什麼。
    """

    def test_乾旱越久同一個價位算起來越好(self):
        s = strategy()
        全窗 = candles()
        # ⚠ **窗長要維持 168**。序列有 200 根，所以 `[:-16]` 之後仍有 184 根，
        # `choose_rate()` 取最後 168 根 → 這才是「同樣長的窗往回滑 16 小時」。
        # 在只有 168 根的序列上做同一件事會變成「把窗縮短」，答案差半個百分點。
        往回16 = backtest.replay_at(s, 全窗[:-16])
        往回0 = backtest.replay_at(s, 全窗)

        # 選中的價位一路沒變……
        assert 往回16.chosen_rate == 往回0.chosen_rate
        # ……但實質年化被乾旱推上去了。
        assert 往回16.effective_annual_pct == pytest.approx(8.95, abs=0.01)
        assert 往回0.effective_annual_pct == pytest.approx(9.46, abs=0.01)
        assert 往回0.effective_annual_pct > 往回16.effective_annual_pct

    def test_命中次數全程沒變只有設限在變(self):
        """成因就在這一行：變的不是市場有多常掃到，是設限那一段怎麼被記帳。"""
        s = strategy()
        全窗 = candles()
        # ⚠ **窗長要維持 168**。序列有 200 根，所以 `[:-16]` 之後仍有 184 根，
        # `choose_rate()` 取最後 168 根 → 這才是「同樣長的窗往回滑 16 小時」。
        # 在只有 168 根的序列上做同一件事會變成「把窗縮短」，答案差半個百分點。
        往回16 = backtest.replay_at(s, 全窗[:-16])
        往回0 = backtest.replay_at(s, 全窗)

        assert 往回16.chosen_censored_ratio == pytest.approx(0.0)
        assert 往回0.chosen_censored_ratio > 0
        assert 往回0.chosen_wait_mean < 往回16.chosen_wait_mean

    def test_中位數對窗尾的補值幾乎免疫(self):
        """D045「該用哪個統計量」的第三個獨立論據（D047）。"""
        s = strategy()
        全窗 = candles()
        # ⚠ **窗長要維持 168**。序列有 200 根，所以 `[:-16]` 之後仍有 184 根，
        # `choose_rate()` 取最後 168 根 → 這才是「同樣長的窗往回滑 16 小時」。
        # 在只有 168 根的序列上做同一件事會變成「把窗縮短」，答案差半個百分點。
        往回16 = backtest.replay_at(s, 全窗[:-16])
        往回0 = backtest.replay_at(s, 全窗)

        平均走了 = 往回16.chosen_wait_mean - 往回0.chosen_wait_mean
        中位走了 = 往回16.chosen_wait_median - 往回0.chosen_wait_median
        assert 平均走了 == pytest.approx(3.19, abs=0.02)
        assert 中位走了 == pytest.approx(1.0, abs=0.01)
        assert 平均走了 > 中位走了 * 3
