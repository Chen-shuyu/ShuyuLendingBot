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
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

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

# 2026-09-05 由 `scripts/hold_report.py` 量到的 17 筆已結束部位，單位小時。
# **寫在這裡是為了讓模擬跑得起來，不是為了宣告它是對的**——逐筆從 1.28h
# 到 48.56h，平均 22.60h、中位數 11.62h，而模型目前假設 12h（D056）。
#
# 🔴 **2026-09-05 換掉的那一版帶著 D057 的幽靈樣本。** 舊的 17 筆裡有
# **三個 0.50h 是 `kind='loan'` 的列**——它們與同一批 `credit` 是同一筆錢的
# 兩個狀態，於是這一袋抽籤裡有 18% 的籤在講一件根本沒發生過的事：
# 「借出去 30 分鐘就被還回來」。**回測用了它整整六天。**
#
# 換掉之後：平均 16.93h → **22.60h**（走了 5.67h），中位數 11.61 → **11.62h**
# （幾乎沒動）。**穩健的統計量會掩蓋缺陷**——這是同一個性質的第五次現身
# （D045 追記／D047／D057／D063）。
#
# **要重新量就跑**（不要手抄，抄過的數字會漂）：
#
#     BFX_DB_PATH=<正式 DB> python3 scripts/hold_report.py
#
# ⚠ **它是一袋固定的抽籤，不是一個分佈模型。** 這一袋現在有 6 筆借滿 48h、
# 5 筆不到 2.5h，**中間幾乎是空的**——用它的平均或中位數去代表「典型的一筆」，
# 描述的是一個不存在的中間狀態（D062）。
OBSERVED_HOLD_HOURS = (
    1.84, 45.08, 6.87, 20.97, 2.33, 48.56, 48.39, 48.26, 1.28,
    11.62, 11.61, 11.61, 25.84, 1.98, 48.33, 48.19, 1.43,
)

# 同一批樣本，**帶著它們當初的掛單利率**（日利率，與 `HoldModel` 收到的單位一致）。
#
# 🔴 **為什麼要多一份帶利率的**：`OBSERVED_HOLD_HOURS` 把利率丟掉了，
# 於是任何用它的模擬都**內建了「持有時間與利率無關」這個假設**——
# 而那正是 D058／D062 要檢驗的那件事。**用一袋丟掉利率的抽籤去檢驗
# 「持有是不是利率的函式」，是用結論證明結論。**
#
# 年化對照（`日利率 × 365 × 100`）：
#   5.47%→45.08h  8.76%→1.43h  8.93%→48.19h  9.00%→48.33h
#   9.11%→48.39／48.26／1.28／11.62／11.61／11.61／25.84h
#   9.12%→1.84h  9.50%→20.97／2.33／48.56h  9.96%→6.87h  10.95%→1.98h
#
# ⚠ **9.11% 那一個價位內部就從 1.28h 到 48.39h，差 38 倍。**
# 組間的訊號比組內的變異小得多——這件事在下面的 `rate_dependent_hold()`
# 裡會再講一次，因為它決定了那個函式能宣稱什麼。
OBSERVED_HOLD_SAMPLES = (
    (0.00024986, 1.84),
    (0.00014986, 45.08),
    (0.00027288, 6.87),
    (0.00026027, 20.97),
    (0.00026027, 2.33),
    (0.00026027, 48.56),
    (0.00024959, 48.39),
    (0.00024959, 48.26),
    (0.00024959, 1.28),
    (0.00024959, 11.62),
    (0.00024959, 11.61),
    (0.00024959, 11.61),
    (0.00024959, 25.84),
    (0.00030000, 1.98),
    (0.00024657, 48.33),
    (0.00024466, 48.19),
    (0.00024000, 1.43),
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


# 🔴 **切開便宜組與昂貴組的分界線。**
#
# **不能用利率中位數**，而這件事是量出來的：17 筆樣本的利率中位數是年化 9.11%，
# **而其中 7 筆剛好就等於 9.11%**（同一批資金被連續重掛出去的那一段）。
# 以中位數切，那 7 筆會整團落進同一側，變成 4 筆對 13 筆——
# **`hold_time.RateSplit.degenerate` 早就在講這件事**（「中位數同時是眾數」）。
#
# 這裡改切在 **9.12% 與 9.50% 之間**：它是候選價位分佈裡一道真的空隙，
# 而不是一個被樣本堆疊出來的點。切出來是 12 筆對 5 筆。
DEFAULT_HOLD_PIVOT_RATE = 0.00025500  # 年化 9.31%


def rate_dependent_hold(
    samples: Sequence[Tuple[float, float]] = OBSERVED_HOLD_SAMPLES,
    pivot_rate: float = DEFAULT_HOLD_PIVOT_RATE,
) -> HoldModel:
    """持有時間**隨掛單利率而不同**：便宜的抽便宜組，貴的抽昂貴組（D058／D062）。

    ## 它換掉的是 `empirical_hold()` 的哪一個假設

    `empirical_hold()` 的 docstring 自己寫著「⚠ 它假設 `P` 與 `r` 無關……
    **真正的修法是換掉這個函式，不是調它的參數**」。**這就是那個函式。**

    量到的方向（2026-09-05，17 筆已結束部位）：`rho(利率, 持有) = −0.383`。
    機制也說得通：融資是可替換的商品，借款人拿到便宜的錢就抱著，
    拿到貴的錢一有更便宜的就換掉。**貴的單被提前還款是市場在做它該做的事。**

    ## 🔴 它**不**宣稱自己找到了一條曲線

    | | 便宜組（< 9.31%） | 昂貴組（≥ 9.31%） |
    |---|---|---|
    | 筆數 | 12 | **5** |
    | 中位持有 | 18.73h | 6.87h |
    | 平均持有 | 25.29h | 16.14h |

    **組內的變異比組間的差距大得多**：光是 9.11% 那一個價位，內部就從
    1.28h 到 48.39h，**差 38 倍**。所以這個函式做的是**分佈的位移**，
    不是「利率 r 對應持有 P(r)」——**兩組各自仍然是一袋很散的抽籤**。

    ⚠ **昂貴組只有 5 筆**，而且其中一筆是 9.50% 借滿 48.56h。
    **拿它去下結論會踩到 D058 已經警告過的那個坑**（分組前要先數相異值）。
    它現在的用途是**讓「該不該漲價」這個問題第一次算得出來**，不是回答它。

    ## 依序循環，理由同 `empirical_hold()`

    **可重跑**：否則「這次比較好」永遠分不清是模型還是亂數種子。
    `cycle_index` 在兩組之間**共用**（不各自計數），這樣同一個起跑點
    換掉 `pivot_rate` 之後，抽到的序列仍然可以逐項對照。

    某一組是空的就退回整袋——**空組要出聲**（`ValueError`）才對，
    但那會讓一個掃描到極端 `pivot_rate` 的報告整支掛掉，
    所以這裡選擇退回並在 docstring 講明。**退回的那一刻，它就退化成
    `empirical_hold()`**，也就是它本來要換掉的那個假設。
    """
    if not samples:
        raise ValueError("沒有持有時間樣本")
    cheap = [hours for rate, hours in samples if rate < pivot_rate]
    pricey = [hours for rate, hours in samples if rate >= pivot_rate]
    everything = [hours for _, hours in samples]

    def model(rate: float, cycle_index: int) -> float:
        group = cheap if rate < pivot_rate else pricey
        if not group:
            group = everything
        return group[cycle_index % len(group)]

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


# ----------------------------------------------------------------------
# 「我的單躺太久了」這個訊號（D054）
# ----------------------------------------------------------------------


def stale_ratio(
    highs: Sequence[float],
    index: int,
    rate: float,
    *,
    window: int = 168,
) -> Optional[float]:
    """到 `index` 為止，這個價位「已經多久沒被掃到」是常態間隔的幾倍。

    `gap ÷ (窗長 ÷ 命中次數)`——分子是距離上一次命中的小時數，
    分母是這個價位在窗內的平均間隔。

    **為什麼要正規化，而不是直接用閒置小時數**：D046 警告過「不要用閒置時間」，
    而那個警告是對的——**對「往上調價」而言**。往下調價的方向它自己也寫了
    「等太久是成交比預期慢的證據，**它支持降價**」。
    但光看小時數仍然不夠：同樣躺 10 小時，在一個常態間隔 2 小時的價位上是異常，
    在常態間隔 12 小時的價位上是正常。**除以常態間隔才問得出「這算久嗎」。**

    命中次數是 0 就回 `None`（這個價位在窗內從沒被掃到過，沒有常態可比）。
    """
    end = min(index, len(highs) - 1)
    if end < 0:
        return None
    view = highs[max(0, end - window + 1) : end + 1]
    hits = sum(1 for high in view if high >= rate)
    if hits == 0:
        return None
    gap = 0
    for position in range(end, -1, -1):
        if highs[position] >= rate:
            break
        gap += 1
    return gap / (len(view) / hits)


def down_when_stale(
    highs: Sequence[float],
    threshold: float = 3.0,
    lookback: int = 24,
    floor: float = 0.0001,
) -> RepostPolicy:
    """躺太久就改掛「最近 `lookback` 小時**真的被掃到過**的最高價」。

    🔴 **這支的偵測很好，但拿它去降價是賠錢的**（D054）。留在程式庫裡是為了
    讓那個結論可以被重跑、被推翻，**不是給正式環境用的**。

    - **偵測**：`stale_ratio >= threshold` 在 5 段長等待上 5/5 命中、
      10 段快速成交上 0/10 誤報，而且門檻從 1.5× 到 4× 都是同一個結果。
    - **獲利**：把相位運氣平均掉之後（43 個起跑點），它比「不重掛」**低 2.16 個百分點**。
      43 個起跑點裡只贏 13 個。

    **贏很多次、輸很大次**——降價會把一個較差的利率鎖住最多 48 小時，
    而省下來的只是一段等待。
    """

    def policy(context: RepostContext) -> Optional[float]:
        ratio = stale_ratio(highs, context.index, context.live_rate)
        if ratio is None or ratio < threshold:
            return None
        end = min(context.index, len(highs) - 1)
        recent = highs[max(0, end - lookback + 1) : end + 1]
        if not recent:
            return None
        target = max(recent)
        if target >= context.live_rate or target < floor:
            return None
        return target

    return policy


def run_policy_across_starts(
    strategy_factory: Callable[[], Any],
    candles: Sequence[Dict[str, Any]],
    starts: Sequence[int],
    **kwargs: Any,
) -> List[PolicyOutcome]:
    """同一個政策，從許多個不同的起跑點各跑一次。

    🔴 **這支是 D054 最重要的產出，比那個訊號本身重要。**

    D050 與 D049 都是拿**單一起跑點**跑出來的，而在只有十幾次循環的歷史上，
    **改掛一次就會把後面每一次循環的進場時點整個推移**——於是比較到的
    有很大一部分是「誰運氣好，剛好踏在好的進場點上」，不是政策本身的好壞。

    實測：`down_when_stale` 在單一起跑點上比基準**高 0.70 個百分點**，
    把 43 個起跑點平均掉之後變成**低 2.16 個百分點**。**符號是反的。**

    **所以此後比較政策一律要用這支，不要用單一次 `run_policy()`。**
    `strategy_factory` 收的是工廠不是實例：策略會把「本輪」的評估結果留在
    成員上（D041 的那四個），跨起跑點共用一個實例等於讓殘留參與下一次。
    """
    outcomes: List[PolicyOutcome] = []
    for start in starts:
        outcomes.append(
            run_policy(strategy_factory(), candles, start_index=start, **kwargs)
        )
    return outcomes


def compare_across_starts(
    baseline: Sequence[PolicyOutcome], candidate: Sequence[PolicyOutcome]
) -> Dict[str, Any]:
    """兩組跨起跑點的結果並排。**平均與勝率要一起看。**

    `down_when_stale(3.0, 12)` 在 43 個起跑點裡**贏 29 個**，
    但平均**輸 0.37 個百分點**——**贏很多次、輸很大次**。
    只看勝率會得到相反的結論。
    """
    pairs = [
        (b.realized_annual_pct, c.realized_annual_pct)
        for b, c in zip(baseline, candidate)
        if b.realized_annual_pct is not None and c.realized_annual_pct is not None
    ]
    if not pairs:
        return {"samples": 0}
    base_values = [b for b, _ in pairs]
    cand_values = [c for _, c in pairs]
    return {
        "samples": len(pairs),
        "baseline_mean": statistics.fmean(base_values),
        "candidate_mean": statistics.fmean(cand_values),
        "difference": statistics.fmean(cand_values) - statistics.fmean(base_values),
        "candidate_wins": sum(1 for b, c in pairs if c > b),
        "worst_loss": min(c - b for b, c in pairs),
        "best_gain": max(c - b for b, c in pairs),
    }
