# -*- coding: utf-8 -*-
"""歷史重播：把時間倒回去，問「當時這個策略會掛什麼價」（M2 第 1 步）。

這是 PLAN.md 第 1 期 **M2 回測工具**的第一塊。M2 完整要回答三件事——
掛什麼價、多久成交、實質年化多少——**這個模組只負責第一件**。
成交模擬與實質年化是第 2 步，還沒做；在那之前，**不要拿這裡的輸出去講「賺多少」**。

## 為什麼要有它

`hold_report`（D040）與 `wait_report`（D045）量的是「已經發生的事」，
而排隊等答案的四個問題全部是「**如果當時不一樣會怎樣**」：

| 問題 | 出處 |
|---|---|
| `P` 寫死 48，該換成什麼 | D1／D040 |
| `W` 該用 `mean` 還是 `median` | D045 第三則追記 |
| 右設限該怎麼補值 | **D047** |
| `ev_window_hours` 168 小時是不是對的 | D036 唯一還沒過關的旋鈕 |

**這四個問題都不可以拿單筆成交當依據**（D040／D044 各踩過一次），
也都不可以靠「改參數上線看看」——那正是 D036 記下的錯誤。
它們需要的是同一件事：**在同一份歷史上，把假設換掉再跑一次。**

## 三條刻意的界線

1. **重播呼叫的是策略本尊，不是它的副本。**
   `replay()` 直接呼叫 `strategy.choose_rate()`。D035 那次回測是手寫的一次性
   腳本，於是「回測說會選 A、正式環境選了 B」永遠分不清是策略不同還是回測寫錯。
   **驗收標準因此才成立**：同一份 K 線餵進去，重播選出來的價位必須與
   當時正式日誌那一行相同。對不上就是工具壞了，不是策略錯了。

2. **重播點看不到未來。** 每個重播點只拿到 `candles[:index + 1]`，
   而且是在這裡切好才交出去的——不是靠呼叫端自律。
   **偷看未來的回測一定會很好看**，而且看起來完全正常。

3. **唯一被轉動的旋鈕是 `P`，而且轉的是策略自己在讀的那個屬性。**
   `assumed_hold_hours()` 暫時改寫 `strategy.assumed_hold_hours` 再還原，
   **不重寫 `r × P ÷ (W + P)` 那條算式**。
   一旦這裡自己算一次期望值，上面第 1 條就沒了。

## 重播點不是巡檢輪次

K 線一小時一根，機器人 600 秒巡檢一輪。**所以重播是「每小時一次」，
不是「每輪一次」**——同一小時內的六輪巡檢在這裡是同一個重播點。
這對「當時會選什麼價」沒有影響（策略每輪看到的是同一根 K 線窗），
但**不要拿重播點的數量去談「機器人跑了幾輪」**。
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Sequence

from utils import clock


@dataclass(frozen=True)
class ReplayPoint:
    """在歷史上的某一刻重播一次，得到策略當時會選的價位。

    `chosen_rate` 是 `None` 時**一定有 `skip_reason`**——「沒選出價位」有好幾種
    成因（K 線不足、候選全被 `ev_min_hits` 擋掉），混成同一個 `None`
    正是 A1 修過的那個病（六個出口共用一句寫死的理由）。
    """

    mts: int
    at: datetime
    # 這一刻策略看得到幾根 K。**不是窗長**——窗長是策略自己從這裡面切的。
    visible_candles: int
    chosen_rate: Optional[float]
    # 選中價位的實質年化（日利率）。`chosen_rate` 是 None 時同為 None。
    chosen_effective: Optional[float]
    # 選中價位的等待估計，三個統計量都留著——D045 的問題正是「該用哪一個」，
    # 只存策略當下用的那個，等於把問題的答案先刪掉了。
    chosen_wait_mean: Optional[float]
    chosen_wait_median: Optional[float]
    chosen_wait_p75: Optional[float]
    chosen_censored_ratio: Optional[float]
    candidate_count: int
    # 這一次重播假設借出多久（小時）。**每個點都存**，因為掃描 `P` 的時候
    # 這是唯一的自變數，而「哪一列是哪個假設」不能靠讀的人記得。
    hold_hours: float
    skip_reason: Optional[str] = None

    @property
    def chosen_annual_pct(self) -> Optional[float]:
        """選中價位的年化百分比。日誌與報告一律用年化，因為人只看得懂那個。"""
        return None if self.chosen_rate is None else self.chosen_rate * 365 * 100

    @property
    def effective_annual_pct(self) -> Optional[float]:
        return None if self.chosen_effective is None else self.chosen_effective * 365 * 100


@dataclass(frozen=True)
class ReplayResult:
    """一次重播的完整結果，以及跑的時候用的是什麼假設。

    **假設要跟結果存在一起。** 一張只有數字的表，隔天就沒有人記得它是用
    `P=48` 還是 `P=16.93` 跑出來的——D036 記的正是這個病。
    """

    strategy_name: str
    hold_hours: float
    window_hours: int
    candle_hours: float
    points: List[ReplayPoint] = field(default_factory=list)
    # 餵進來的 K 線總數與實際重播了幾點。兩者不同是正常的（前面幾根不夠開窗），
    # 但差多少要看得見。
    candles_supplied: int = 0

    @property
    def decided(self) -> List[ReplayPoint]:
        """真的選出價位的那些點。"""
        return [point for point in self.points if point.chosen_rate is not None]

    @property
    def skipped(self) -> List[ReplayPoint]:
        return [point for point in self.points if point.chosen_rate is None]


@contextmanager
def assumed_hold_hours(strategy: Any, hours: Optional[float]) -> Iterator[None]:
    """暫時把策略假設的借出時間換成 `hours`，離開時還原。

    **為什麼是改屬性而不是傳參數進去**：`choose_rate()` 讀的是
    `self.assumed_hold_hours`，而重播的目的正是要驗證「策略在別的假設下會選什麼」。
    傳參數就得改策略的簽章，改完之後重播跑的就不再是正式環境跑的那條路徑，
    上面界線 1 立刻失效。

    🔴 **2026-08-30 起改動的是 `assumed_hold_hours`，不再是 `offer_period`**（D056）。
    在那之前兩者是同一個值，於是這支會把**送給交易所的合約天期**也一起改掉
    ——重播時無所謂（不會真的下單），但那個耦合本身是錯的，而且它讓
    「把假設改成 12 小時」這件事在正式環境變成做不到（整數、且低於交易所下限）。

    **一定要還原**——`finally` 不是防禦性寫法，是這個設計成立的前提。
    """
    if hours is None:
        yield
        return
    original = strategy.assumed_hold_hours
    strategy.assumed_hold_hours = float(hours)
    try:
        yield
    finally:
        strategy.assumed_hold_hours = original


def _evaluation_for(strategy: Any, rate: Optional[float]) -> Optional[Dict[str, Any]]:
    """從策略留下的候選集裡找出選中的那一列。

    **用等值比對而不是「取最大」**：兩者在正常情況下同一列，但只要
    `choose_rate()` 的挑選規則改了（例如加上一道下限），「取最大」就會靜靜地
    報出另一列——D026 那個家族的典型長相。
    """
    if rate is None:
        return None
    for entry in strategy.last_evaluation or []:
        if entry.get("rate") == rate:
            return entry
    return None


def replay(
    strategy: Any,
    candles: Sequence[Dict[str, Any]],
    *,
    hold_hours: Optional[float] = None,
    step: int = 1,
    timezone_name: Optional[str] = None,
) -> ReplayResult:
    """把 `candles` 從頭走一遍，每 `step` 根重播一次策略的定價決策。

    `candles` 必須**已依 `mts` 由舊到新排序**（`market_candles` 的查詢負責這件事）。
    `hold_hours` 是 `None` 就用策略自己的設定值，也就是正式環境跑的那個。

    每個重播點只看得到 `candles[:index + 1]`——這件事在這裡做，不在呼叫端做。
    """
    if step < 1:
        raise ValueError("step 必須至少是 1")

    tz = clock.get_timezone(timezone_name)
    points: List[ReplayPoint] = []

    with assumed_hold_hours(strategy, hold_hours):
        effective_hold = float(strategy.assumed_hold_hours)
        for index in range(0, len(candles), step):
            # 界線 2：切窗在這裡發生。`visible` 之後的每一根對策略都不存在。
            visible = list(candles[: index + 1])
            chosen = strategy.choose_rate(visible)
            entry = _evaluation_for(strategy, chosen)
            candle = candles[index]
            points.append(
                ReplayPoint(
                    mts=int(candle["mts"]),
                    at=datetime.fromtimestamp(int(candle["mts"]) / 1000, tz),
                    visible_candles=len(visible),
                    chosen_rate=chosen,
                    chosen_effective=(entry or {}).get("effective"),
                    chosen_wait_mean=(entry or {}).get("wait_hours"),
                    chosen_wait_median=(entry or {}).get("median_hours"),
                    chosen_wait_p75=(entry or {}).get("p75_hours"),
                    chosen_censored_ratio=(entry or {}).get("censored_ratio"),
                    candidate_count=len(strategy.last_evaluation or []),
                    hold_hours=effective_hold,
                    skip_reason=_skip_reason(strategy, chosen, visible),
                )
            )

    return ReplayResult(
        strategy_name=type(strategy).__name__,
        hold_hours=effective_hold,
        window_hours=int(getattr(strategy, "ev_window_hours", 0)),
        candle_hours=float(getattr(strategy, "candle_hours", 1.0)),
        points=points,
        candles_supplied=len(candles),
    )


def replay_at(
    strategy: Any,
    candles: Sequence[Dict[str, Any]],
    *,
    index: int = -1,
    hold_hours: Optional[float] = None,
    timezone_name: Optional[str] = None,
) -> ReplayPoint:
    """只重播**一個**時間點，回傳那一點的 `ReplayPoint`。

    `index` 支援負數（`-1` = 最後一根 K），語意與 list 索引一致。

    **為什麼要有它**：拿 `replay(..., step=len(candles))` 去取單點是錯的
    ——`range(0, n, n)` 只會產生 `[0]`，也就是**第一**根而不是最後一根。
    那個錯誤不會拋例外，只會安靜地回答另一個時間點的答案，
    正是 D026 那個家族的長相：**看起來完全正常的錯答案。**
    """
    if not candles:
        raise ValueError("沒有 K 線可以重播")
    resolved = index if index >= 0 else len(candles) + index
    if not 0 <= resolved < len(candles):
        raise IndexError(f"index {index} 超出 {len(candles)} 根 K 線的範圍")
    result = replay(
        strategy,
        candles[: resolved + 1],
        hold_hours=hold_hours,
        step=max(resolved, 1),
        timezone_name=timezone_name,
    )
    return result.points[-1]


def _skip_reason(
    strategy: Any, chosen: Optional[float], visible: Sequence[Dict[str, Any]]
) -> Optional[str]:
    """沒選出價位時，講出是哪一個出口——不要讓兩種成因共用一個 `None`。

    `choose_rate()` 只有兩條回傳 `None` 的路：K 線根數不足，或所有候選價位
    的命中次數都低於 `ev_min_hits`。**兩者的意思完全不同**：前者是資料還不夠，
    後者是這段市場沒有任何價位被掃到過那麼多次。
    """
    if chosen is not None:
        return None
    minimum = int(getattr(strategy, "ev_min_candles", 0))
    if len(visible) < minimum:
        return f"K 線只有 {len(visible)} 根，低於 ev_min_candles={minimum}"
    hits = int(getattr(strategy, "ev_min_hits", 0))
    return f"沒有任何候選價位的命中次數達到 ev_min_hits={hits}"


@dataclass(frozen=True)
class HoldSweepRow:
    """`P` 掃描表的一列：換一個借出時間假設，策略會選到哪裡去。"""

    hold_hours: float
    chosen_rate: Optional[float]
    chosen_effective: Optional[float]
    wait_mean: Optional[float]
    wait_median: Optional[float]
    skip_reason: Optional[str] = None

    @property
    def chosen_annual_pct(self) -> Optional[float]:
        return None if self.chosen_rate is None else self.chosen_rate * 365 * 100

    @property
    def effective_annual_pct(self) -> Optional[float]:
        return None if self.chosen_effective is None else self.chosen_effective * 365 * 100


def sweep_hold_hours(
    strategy: Any,
    candles: Sequence[Dict[str, Any]],
    hold_hours_values: Sequence[float],
    *,
    at_index: int = -1,
) -> List[HoldSweepRow]:
    """在**同一個時間點**上，把 `P` 換過一輪，看選中的價位往哪裡走。

    這是 D1 那個問題的量化版本，也是 D045「開獎」那一節手算過一次的東西
    ——差別在那次是一次性腳本，這次是常設能力。

    ⚠ **這張表回答的是「模型會選什麼」，不是「哪個假設賺比較多」。**
    三個假設下的 `effective` 分母不同，**數字不可以直接比大小**
    ——同一個陷阱在 `wait_report` 的統計量對照表上已經標過一次。
    要回答「哪個賺比較多」得等 M2 第 2 步（成交模擬）。
    """
    visible = list(candles[: len(candles) + at_index + 1] if at_index < 0 else candles[: at_index + 1])
    rows: List[HoldSweepRow] = []
    for hours in hold_hours_values:
        with assumed_hold_hours(strategy, hours):
            chosen = strategy.choose_rate(visible)
            entry = _evaluation_for(strategy, chosen)
            rows.append(
                HoldSweepRow(
                    hold_hours=hours,
                    chosen_rate=chosen,
                    chosen_effective=(entry or {}).get("effective"),
                    wait_mean=(entry or {}).get("wait_hours"),
                    wait_median=(entry or {}).get("median_hours"),
                    skip_reason=_skip_reason(strategy, chosen, visible),
                )
            )
    return rows
