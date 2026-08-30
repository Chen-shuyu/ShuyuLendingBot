# -*- coding: utf-8 -*-
"""成交模擬：那個價位掛出去之後，多久會被掃到、實得年化多少（M2 第 2 步）。

接在 `core/backtest.py`（第 1 步）後面。第 1 步只能說「模型會選什麼價」，
**這一步才說得出「那個選擇值多少」**——也就是 D1／D045／D047 那幾個問題
一直在等的東西。

## 成交規則，以及它憑什麼可信

規則只有一句：**從掛出那一刻往後走，第一根 `high >= 掛單利率` 的 K 線就是成交**，
成交時點取那根 K 的中點（掃單發生在該根之內，平均落在中點——與
`estimate_wait()` 同一個約定）。

**這條規則是被驗證過的，不是假設的。** 拿 `wait_report` 已經配對好的 12 筆
真實成交回頭跑一次（`validate_against_real_fills()`，2026-08-30）：

| | 值 |
|---|---|
| 實際等待合計 | 19.45h |
| **模擬等待合計** | **18.15h** |
| **總量比** | **0.93×** |
| 逐筆倍數中位數 | 0.92× |

對照組：策略自己的 `estimate_wait()` 在同一批樣本上是 **4.25 倍高估**（D045）。
**模擬器比模型自己的預測器準了一個數量級**，這是它能拿來當裁判的理由。

## 🔴 四條它做不到的事，每一條都會讓結果偏樂觀

1. **不看排隊位置與金額。** `high >= rate` 只說「有需求掃到這個價位」，
   沒說「掃掉的量足夠輪到我們那 345 USD」。**所以模擬的成交一定偏快**
   ——上面那個 0.93× 有一部分就是這個。
2. **K 線是一小時一根，解析度到此為止。** 12 筆樣本裡有 7 筆的實際等待
   **不到一小時**，那些筆的逐筆倍數（0.00×、inf×）是解析度雜訊，不是誤差。
   **總量比才是可讀的那個數字。**
3. **樣本全落在年化 5.47%～10.95%**——那正是模型自己選出來的帶。
   **帶外沒有驗證過，不能外推**（與 D045 同一條界線）。
4. **`P` 與 `r` 被當成獨立的。** D040 的「越貴借越短」如果成立，這個假設就錯了，
   而那件事至今**比不出來**（分組是 1 筆對 16 筆，且不會自己好）。
   所以 `HoldModel` 是個可換的東西，而不是寫死的一條曲線。

## 為什麼「沒等到成交」的時間一定要留在分母裡

`wait_report` 已經踩過一次：它印的 7.99% 實得年化**偏樂觀**，因為
「沒等到成交的期間不在分母裡」（最長的一段空掛 34.20 小時完全沒被算進去）。

**這裡不重蹈**：`run_policy()` 算的是**整段歷史的時間加權實得年化**，
空等的每一個小時都以 0% 報酬計入分母。這也是 M3 要的那個數字的雛形。
"""

import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from core import backtest


# 一小時有幾毫秒。K 線的 `mts` 是毫秒，而報告一律用小時。
_MS_PER_HOUR = 3_600_000.0


@dataclass(frozen=True)
class FillOutcome:
    """一次「掛出去之後發生什麼」。

    `censored=True` 時 `wait_hours` 是**下界**（走到資料尾端都沒被掃到），
    不是量測值——`realized_effective()` 因此拒絕替它算實得年化。
    """

    rate: float
    wait_hours: float
    censored: bool
    # 命中的是第幾根 K（`censored` 時是 None）。留著是為了讓對帳查得到那一根。
    hit_index: Optional[int] = None

    def realized_effective(self, hold_hours: float) -> Optional[float]:
        """`r × P ÷ (W + P)`——與策略、`wait_report` 完全同一條算式。

        **右設限時回傳 `None` 而不是一個數字**：那一段還沒有結果，
        給出數字等於宣告一個沒有發生的成交（`wait_time.py` 對仍在生息中的
        部位也是同樣的處置）。
        """
        if self.censored:
            return None
        total = self.wait_hours + hold_hours
        if total <= 0:
            return None
        return self.rate * hold_hours / total


def simulate_fill(
    candles: Sequence[Dict[str, Any]],
    from_index: int,
    rate: float,
    *,
    candle_hours: float = 1.0,
) -> FillOutcome:
    """從第 `from_index` 根 K 起掛在 `rate`，模擬多久會被掃到。

    命中那根算等 `0.5` 根（掃單落在該根之內，平均在中點），與
    `ExpectedValueStrategy.estimate_wait()` 同一個約定——**兩邊的約定必須一致**，
    否則「預估 vs 實際」的比較會多出一個純粹來自記帳方式的偏差。

    走到尾端都沒命中就是**右設限**：`wait_hours` 是下界，`censored=True`。
    """
    if from_index < 0 or from_index >= len(candles):
        raise IndexError(f"from_index {from_index} 超出 {len(candles)} 根 K 線的範圍")

    for index in range(from_index, len(candles)):
        if candles[index]["high"] >= rate:
            return FillOutcome(
                rate=rate,
                wait_hours=(index - from_index + 0.5) * candle_hours,
                censored=False,
                hit_index=index,
            )
    return FillOutcome(
        rate=rate,
        wait_hours=(len(candles) - from_index) * candle_hours,
        censored=True,
        hit_index=None,
    )


# ----------------------------------------------------------------------
# 借出多久（`P`）
# ----------------------------------------------------------------------

# 2026-08-30 由 `scripts/hold_report.py` 量到的 17 筆已結束部位，單位小時。
# **寫在這裡是為了讓模擬跑得起來，不是為了宣告它是對的**——逐筆從 0.50h
# 到 48.56h，平均 16.93h、中位數 11.61h，而模型至今假設 48h（D1／D040）。
OBSERVED_HOLD_HOURS = (
    1.84, 45.08, 6.87, 20.97, 2.33, 48.56, 48.39, 48.26, 1.28,
    0.50, 11.62, 0.50, 11.61, 0.50, 11.61, 25.84, 1.98,
)

# `HoldModel` 拿到「掛出的利率」與「這是第幾次循環」，回答「這一筆會借多久」。
#
# 🔴 **簽章必須是無狀態的，這一點是踩到之後才寫下來的。**
# 第一版讓 `empirical_hold()` 回傳一個帶 `state["index"]` 的閉包，於是
# **同一個模型實例跑第二次會從序列中間接下去**——同一組設定先後跑出
# 7.26% 與 6.70%，而兩個數字看起來都很正常。
# 「依序循環」的重點本來就是**可重跑**，一個會累積狀態的實作正好毀掉那件事。
# 把「第幾次循環」變成參數之後，模型是純函式，重跑必然同值。
#
# **簽章刻意也收下 `rate`**，即使目前兩個實作都不看它：D040 的「越貴借越短」
# 一旦比得出來，換的是這個函式，不是所有呼叫端。
HoldModel = Callable[[float, int], float]


def fixed_hold(hours: float) -> HoldModel:
    """每一筆都借滿 `hours`。`fixed_hold(48)` 就是模型現在的假設。"""

    def model(rate: float, cycle_index: int) -> float:
        return hours

    return model


def empirical_hold(
    samples: Sequence[float] = OBSERVED_HOLD_HOURS,
) -> HoldModel:
    """依序循環使用實測到的持有時間，**第 `cycle_index` 次循環用第幾個樣本**。

    **為什麼是「依序循環」而不是隨機抽**：回測要能重跑出同一個數字，
    否則「這次比較好」永遠分不清是策略還是亂數種子——而這個專案已經有
    六個決策互相推翻的紀錄（D036）。

    ⚠ **它假設 `P` 與 `r` 無關**，而那件事至今比不出來（D040 的分組是
    1 筆對 16 筆）。真正的修法是換掉這個函式，不是調它的參數。

    ⚠ **它也假設樣本的順序不重要**，而那是為了可重跑才付的代價：
    真實的持有時間是隨市場走的，這裡只是把它們當成一袋固定的抽籤。
    """
    if not samples:
        raise ValueError("沒有持有時間樣本")
    ordered = list(samples)

    def model(rate: float, cycle_index: int) -> float:
        return ordered[cycle_index % len(ordered)]

    return model


# ----------------------------------------------------------------------
# 重掛政策（A2-b，見 DECISIONS.md D046）
# ----------------------------------------------------------------------
#
# **這一段只在模擬裡跑，機器人一行都沒有改。** 它存在的目的是先量出
# 「哪一種重掛政策比較好」，而不是把某個直覺直接送上正式環境
# ——直接拍一個「超過 N 小時就降價」正是 `target_queue_usd` 的死法（D032）。
#
# 🔴 **模擬不到的兩件事，而它們都讓重掛看起來比實際上划算**：
#
# 1. **排隊位置的成本。** 取消重掛會把排隊位置歸零，而 K 線看不到排隊。
#    模擬裡「改掛一個新價位」是免費的，真實世界不是。
# 2. **取消當下就成交的風險。** 2026-08-16 19:31 送出取消、25 秒後那張單
#    成交了（D031）——**用確定的利息去換估出來的速度**。模擬裡不存在這件事。
#
# 所以下面比出來的差距**是上界**：真實的重掛只會比模擬更不划算。


@dataclass(frozen=True)
class RepostContext:
    """要不要改掛時，政策看得到的東西。

    **刻意不給「未來」**：政策只拿得到當下的候選價位與已經等了多久，
    與策略在正式環境裡看得到的一樣多。
    """

    live_rate: float
    candidate_rate: Optional[float]
    idle_hours: float
    index: int


# 回傳新的利率代表「改掛」，回傳 `None` 代表「維持不動」。
RepostPolicy = Callable[[RepostContext], Optional[float]]


def never_repost() -> RepostPolicy:
    """掛出去就不再動。**這是對照組的下界**，不是誰真的在用的政策。"""

    def policy(context: RepostContext) -> Optional[float]:
        return None

    return policy


def rate_tolerance(tolerance_pct: float = 2.0) -> RepostPolicy:
    """**這是正式環境現在真正在跑的政策。**

    `_plans_match()` 的利率容差：候選價位與場上差超過 `tolerance_pct` 就重掛，
    **兩個方向都會**。往上沒有任何額外判準（D046 查證過），
    往下那道守門檻在簿子被截斷時一律棄權（A2／A2-a），於是也等於放行。

    所以「現況」不是「不重掛」，是「差超過 2% 就跟著走」
    ——只是 D047 的乾旱回饋圈讓候選價位一直等於場上價位，它從沒被觸發過。
    """

    def policy(context: RepostContext) -> Optional[float]:
        if context.candidate_rate is None or context.live_rate <= 0:
            return None
        drift_pct = abs(context.candidate_rate - context.live_rate) / context.live_rate * 100
        return context.candidate_rate if drift_pct > tolerance_pct else None

    return policy


def follow_candidate() -> RepostPolicy:
    """候選價位一變就跟著改。**對照組的上界**——重掛成本在模擬裡是零，
    所以這一條在模擬裡會被高估得最厲害。"""

    def policy(context: RepostContext) -> Optional[float]:
        if context.candidate_rate is None:
            return None
        return context.candidate_rate if context.candidate_rate != context.live_rate else None

    return policy


def down_only(tolerance_pct: float = 2.0) -> RepostPolicy:
    """只跟著往下，永遠不往上。**防的是棘輪**（D046）。

    市場連漲時一路追高會永遠不成交，而「等太久」這個訊號**支持降價、
    不支持漲價**——兩個訊號混在一起會在市場走弱時去漲價，正好是最糟的時機。
    """

    def policy(context: RepostContext) -> Optional[float]:
        if context.candidate_rate is None or context.live_rate <= 0:
            return None
        if context.candidate_rate >= context.live_rate:
            return None
        drift_pct = (context.live_rate - context.candidate_rate) / context.live_rate * 100
        return context.candidate_rate if drift_pct > tolerance_pct else None

    return policy


def down_after_idle(idle_hours: float, tolerance_pct: float = 2.0) -> RepostPolicy:
    """躺超過 `idle_hours` 才准往下調，而且只往下。

    門檻候選來自 D045 的追記：躺超過 **12.6～18.9 小時**就輸給簿子底部。
    ⚠ **那個區間是推導出來的，不是量出來的**——這支存在正是為了量它。
    """

    def policy(context: RepostContext) -> Optional[float]:
        if context.idle_hours < idle_hours:
            return None
        return down_only(tolerance_pct)(context)

    return policy


# ----------------------------------------------------------------------
# 整段歷史跑一次
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Cycle:
    """一次完整的「掛出 → 成交 → 還回來」，或一段沒等到成交的空掛。"""

    decided_index: int
    rate: float
    wait_hours: float
    hold_hours: Optional[float]
    censored: bool
    realized_effective: Optional[float]
    # 這一段等待中間改掛了幾次。**`rate` 記的是最後成交的那個價位**，
    # 不是一開始掛出去的那個——兩者混在一起會讓「掛在哪裡」這個問題答錯。
    repost_count: int = 0
    initial_rate: Optional[float] = None

    @property
    def occupied_hours(self) -> float:
        """這一段佔掉資金多少時間。**空等也佔時間**，這正是它要進分母的理由。"""
        return self.wait_hours + (self.hold_hours or 0.0)

    @property
    def interest_hours(self) -> float:
        """`r × P`：這一段真正賺到的利息（以「日利率 × 小時」計）。"""
        if self.censored or self.hold_hours is None:
            return 0.0
        return self.rate * self.hold_hours


@dataclass(frozen=True)
class PolicyOutcome:
    """一整段歷史跑下來的結果，以及跑的時候用的是什麼假設。"""

    strategy_name: str
    hold_model_name: str
    repost_policy_name: str = "none"
    cycles: List[Cycle] = field(default_factory=list)
    # 沒有選出價位（`choose_rate()` 回 None）而空轉掉的小時數。
    # **它也佔時間**，所以一樣進分母。
    idle_hours: float = 0.0
    horizon_hours: float = 0.0

    @property
    def filled(self) -> List[Cycle]:
        return [cycle for cycle in self.cycles if not cycle.censored]

    @property
    def realized_annual_pct(self) -> Optional[float]:
        """時間加權實得年化：`Σ(r × P) ÷ Σ(W + P)`，再換成年化百分比。

        **分母含空等與空轉**——`wait_report` 的 7.99% 就是因為少了這一塊
        才偏樂觀，那個坑在這裡不再踩一次。
        """
        occupied = sum(cycle.occupied_hours for cycle in self.cycles) + self.idle_hours
        if occupied <= 0:
            return None
        interest = sum(cycle.interest_hours for cycle in self.cycles)
        return interest / occupied * 365 * 100

    @property
    def fill_rate(self) -> Optional[float]:
        """掛出去的單有幾成等到了成交。"""
        if not self.cycles:
            return None
        return len(self.filled) / len(self.cycles)

    @property
    def median_wait_hours(self) -> Optional[float]:
        waits = [cycle.wait_hours for cycle in self.filled]
        return statistics.median(waits) if waits else None

    @property
    def repost_count(self) -> int:
        """整段歷史改掛了幾次。**真實世界每一次都要付排隊位置的代價**，
        而模擬裡是免費的——所以這個數字越大，上面那個實得年化越樂觀。"""
        return sum(cycle.repost_count for cycle in self.cycles)


def run_policy(
    strategy: Any,
    candles: Sequence[Dict[str, Any]],
    *,
    hold_model: Optional[HoldModel] = None,
    hold_model_name: str = "",
    assumed_hold_hours: Optional[float] = None,
    start_index: Optional[int] = None,
    candle_hours: float = 1.0,
    repost_policy: Optional[RepostPolicy] = None,
    repost_policy_name: str = "",
) -> PolicyOutcome:
    """把整段歷史跑一次：選價 → 等成交 → 借出 → 資金回來 → 再選一次。

    `assumed_hold_hours` 是**策略在選價時以為**自己會借多久（也就是那個 48）；
    `hold_model` 是**模擬器認為實際上**會借多久。
    **這兩件事刻意分開**——D1 問的正是「模型的假設錯了會怎樣」，
    把它們綁在一起就問不出來了。

    沒選出價位的那一根 K 算 `idle_hours`，**一樣進分母**：
    策略不掛單的期間，錢一樣沒有在賺。
    """
    model = hold_model or empirical_hold()
    name = hold_model_name or getattr(model, "__name__", "empirical")

    minimum = int(getattr(strategy, "ev_min_candles", 0))
    index = start_index if start_index is not None else minimum
    index = max(index, 0)

    cycles: List[Cycle] = []
    idle = 0.0
    started_at = index

    with backtest.assumed_hold_hours(strategy, assumed_hold_hours):
        while index < len(candles):
            # 界線同第 1 步：這一刻只看得到自己以前的 K 線。
            chosen = strategy.choose_rate(list(candles[: index + 1]))
            if chosen is None:
                idle += candle_hours
                index += 1
                continue

            fill, final_rate, reposts = _wait_with_reposts(
                candles,
                index,
                chosen,
                strategy=strategy,
                policy=repost_policy,
                candle_hours=candle_hours,
            )
            hold = None if fill.censored else model(final_rate, len(cycles))
            cycles.append(
                Cycle(
                    decided_index=index,
                    rate=final_rate,
                    wait_hours=fill.wait_hours,
                    hold_hours=hold,
                    censored=fill.censored,
                    realized_effective=(
                        None if hold is None else fill.realized_effective(hold)
                    ),
                    repost_count=reposts,
                    initial_rate=chosen,
                )
            )
            if fill.censored:
                break

            # 資金回來的那一刻才重新選價。**往前跳的是「等待 + 借出」的整段**
            # ——每根 K 都重選一次會憑空多出很多次不可能發生的機會。
            advance = max(
                int(round((fill.wait_hours + (hold or 0.0)) / candle_hours)), 1
            )
            index += advance

    return PolicyOutcome(
        strategy_name=type(strategy).__name__,
        hold_model_name=name,
        repost_policy_name=repost_policy_name or ("none" if repost_policy is None else "custom"),
        cycles=cycles,
        idle_hours=idle,
        horizon_hours=max(len(candles) - started_at, 0) * candle_hours,
    )


def _wait_with_reposts(
    candles: Sequence[Dict[str, Any]],
    from_index: int,
    rate: float,
    *,
    strategy: Any,
    policy: Optional[RepostPolicy],
    candle_hours: float,
):
    """等成交，中間可以依 `policy` 改掛。回傳 `(結果, 最後掛的利率, 改掛次數)`。

    **`policy` 是 `None` 時必須與 `simulate_fill()` 逐位元相同**——否則
    「加了重掛政策之後變好了」會分不清是政策的功勞還是基準線被改掉了。
    有測試釘住這件事（`test_沒有政策時與simulate_fill完全相同`）。

    改掛之後**等待時間不歸零**：錢從掛出那一刻起就沒有在賺，
    換一個價位不會把已經等掉的時間變不見。
    **這是這個模擬最重要的一條記帳規則**——歸零的話，一個「每小時都改掛」
    的政策會顯示成永遠只等半小時。
    """
    if policy is None:
        return simulate_fill(candles, from_index, rate, candle_hours=candle_hours), rate, 0

    current = rate
    reposts = 0
    for index in range(from_index, len(candles)):
        if candles[index]["high"] >= current:
            return (
                FillOutcome(
                    rate=current,
                    wait_hours=(index - from_index + 0.5) * candle_hours,
                    censored=False,
                    hit_index=index,
                ),
                current,
                reposts,
            )
        # 這一根沒被掃到 → 走到下一根之前，讓政策看一次。
        # **候選價位用策略本尊重算**，看得到的 K 線同樣只到 `index` 為止。
        candidate = strategy.choose_rate(list(candles[: index + 1]))
        decision = policy(
            RepostContext(
                live_rate=current,
                candidate_rate=candidate,
                idle_hours=(index - from_index + 1) * candle_hours,
                index=index,
            )
        )
        if decision is not None and decision != current:
            current = decision
            reposts += 1

    return (
        FillOutcome(
            rate=current,
            wait_hours=(len(candles) - from_index) * candle_hours,
            censored=True,
            hit_index=None,
        ),
        current,
        reposts,
    )


# ----------------------------------------------------------------------
# 驗收：這條成交規則對得上真實成交嗎
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class FillValidationRow:
    """一筆真實成交與模擬結果的對照。"""

    started_at: Any
    rate: float
    actual_hours: float
    simulated_hours: Optional[float]
    note: Optional[str] = None

    @property
    def ratio(self) -> Optional[float]:
        if self.simulated_hours is None or self.actual_hours <= 0:
            return None
        return self.simulated_hours / self.actual_hours


@dataclass(frozen=True)
class FillValidation:
    """成交規則的驗收結果。**這是模擬器的驗收，不是策略的驗收。**"""

    rows: List[FillValidationRow] = field(default_factory=list)
    # 解析度門檻：實際等待短於這個值的樣本，逐筆倍數是雜訊而不是誤差。
    resolution_hours: float = 1.0

    @property
    def comparable(self) -> List[FillValidationRow]:
        return [row for row in self.rows if row.simulated_hours is not None]

    @property
    def above_resolution(self) -> List[FillValidationRow]:
        """實際等待長於一根 K 的那些——逐筆倍數在這裡才讀得出意思。"""
        return [
            row for row in self.comparable if row.actual_hours >= self.resolution_hours
        ]

    def total_ratio(self, rows: Optional[Sequence[FillValidationRow]] = None):
        """總量比：模擬合計 ÷ 實際合計。**這是可讀的那個數字。**"""
        rows = self.comparable if rows is None else rows
        actual = sum(row.actual_hours for row in rows)
        simulated = sum(row.simulated_hours or 0.0 for row in rows)
        return simulated / actual if actual > 0 else None


def validate_against_real_fills(
    spells: Sequence[Any],
    candles: Sequence[Dict[str, Any]],
    *,
    candle_hours: float = 1.0,
    resolution_hours: float = 1.0,
) -> FillValidation:
    """拿 `wait_time` 配對出來的真實成交，回頭檢驗這條成交規則。

    `spells` 是 `wait_time.summarize().spells`——**已經處理過合併、右設限與
    偵測延遲的那份**，不要自己再從 `loan_offers` 配一次（D045 的實作就是在
    那一步被一個靜默吃掉樣本的合併 bug 咬過）。

    **只拿等到成交的那些期間**：右設限的期間沒有「實際等待」可以對照，
    把它們的下界當量測值正是 D026 那一族的長相。

    模擬的起點是**掛單當下那一刻**，不是那根 K 的開頭——掛在 18:10 的單
    不該被算成從 18:00 就開始等。
    """
    rows: List[FillValidationRow] = []
    for spell in spells:
        if getattr(spell, "censored", False):
            continue
        started = spell.started_at
        start_ms = started.timestamp() * 1000

        index = next(
            (
                position
                for position, candle in enumerate(candles)
                if candle["mts"] + candle_hours * _MS_PER_HOUR > start_ms
            ),
            None,
        )
        if index is None:
            rows.append(
                FillValidationRow(
                    started_at=started,
                    rate=spell.rate,
                    actual_hours=spell.hours,
                    simulated_hours=None,
                    note="掛單時間落在 K 線範圍之外",
                )
            )
            continue

        outcome = simulate_fill(candles, index, spell.rate, candle_hours=candle_hours)
        if outcome.censored:
            rows.append(
                FillValidationRow(
                    started_at=started,
                    rate=spell.rate,
                    actual_hours=spell.hours,
                    simulated_hours=None,
                    note="模擬走到資料尾端都沒命中（右設限）",
                )
            )
            continue

        # 命中那根的中點減掉掛單當下——**第一根要扣掉已經過去的那一段**，
        # 否則掛在 18:50 的單會被算成等了一整根 K。
        hit = candles[outcome.hit_index]
        hit_mid_ms = hit["mts"] + candle_hours * _MS_PER_HOUR / 2
        rows.append(
            FillValidationRow(
                started_at=started,
                rate=spell.rate,
                actual_hours=spell.hours,
                simulated_hours=max((hit_mid_ms - start_ms) / _MS_PER_HOUR, 0.0),
            )
        )

    return FillValidation(rows=rows, resolution_hours=resolution_hours)
