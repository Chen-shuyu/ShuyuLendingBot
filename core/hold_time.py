# -*- coding: utf-8 -*-
"""實際持有時間的量測（見 DECISIONS.md D040）。

**這個模組只量測，不做任何決策。** `strategies/expected_value.py` 的
`hold_hours = self.offer_period * 24.0` 假設每一筆都借滿天期，而 2026-08-21 的
六筆部位裡只有一筆接近借滿。這裡負責把「實際上借了多久」算出來並講清楚，
**至於那個 48 要不要改、改成什麼，等回測工具（M2）用這些資料回答**——
先改參數再建量測正是 D036 記下的錯誤。

三個誠實度來源，每一個都會出現在輸出裡：

1. **仍在借出中的部位是右設限樣本**：只知道「至少借了這麼久」。丟掉它們會低估
   （長命的部位更容易還開著），把它們當成已結束也會低估（下界不是實際值）。
   做法與 `expected_value.py` 的等待估計一致：分開報，並給出 `censored_ratio`。
2. **`closed_at` 是我們偵測到的時間，不是交易所實際還款的時間**：巡檢每
   `interval` 秒一輪，所以每一筆的持有時間都被**高估** 0 到一個巡檢間隔。
   對中位數 6.9 小時的樣本，10 分鐘的間隔是 2.4%；但對只借了 2.3 小時的那筆是 7%。
3. **`opened_at` 可能是 None**：`_millis_to_iso()` 轉不動時會留空，這時只能退而
   用 `first_seen_at`（我們第一次看到它的時間），那同樣是高估後的近似值。
   退用的筆數會單獨報出來，不會混進去裝作精確。

「借滿」不做二分類。回報的是**完成率**（實際持有 ÷ 預定天期），分類門檻
（`matured_threshold`）跟著輸出一起印出來，讓看的人知道那條線畫在哪裡——
45.08 小時對 48 小時的預定到底算不算「借滿」，是門檻的選擇，不是事實。
"""

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from utils import clock

# 完成率達到這個比例就歸類為「借到期」。**這是一條人為的線**，所以它會被印出來。
DEFAULT_MATURED_THRESHOLD = 0.9

# 少於這個筆數就不要報中位數，直接把原始值列出來。
#
# **偶數筆的中位數會插值**，而插出來的是資料裡不存在的數。實例：便宜組只有
# 1.84h 與 45.08h 兩筆（差 25 倍），`statistics.median` 給出 23.46h——那個數字
# 沒有對應任何一筆真實的借貸，卻長得像個有代表性的統計量。兩筆原始值並排
# 反而讓人一眼看出「這組還看不出集中趨勢」。
#
# 這是 PROGRESS.md 2026-08-19 那句「真正的毛病不在用哪一種平均，而在取平均
# 這個動作本身」的直接應用。
MIN_SAMPLES_FOR_QUANTILE = 3

# 同一張掛單被交易所拆成多筆部位時，各筆的 `opened_at` 會差幾秒到幾十秒。
# 超過這個秒數就不再當成同一次放貸。**這是一條人為的線**，所以它會被印出來。
#
# 實測（2026-08-28）：一張 344.87 USD 的單被拆成 150.00／134.10／60.77 三筆，
# `opened_at` 分別是 02:07:35／02:07:46／02:07:49（相隔 14 秒），**同時結清**。
DEFAULT_SPLIT_WINDOW_SECONDS = 300.0


@dataclass(frozen=True)
class HoldRecord:
    """單一部位的持有時間。

    `hours` 對已結束的部位是實際值（仍受偵測延遲高估），對仍在借出中的部位
    是**下界**——`censored` 就是在講這件事，讀的人不該讓兩者混在同一個平均裡。
    """

    position_id: str
    rate: float
    amount: float
    period_hours: float
    hours: float
    censored: bool
    opened_at_approximate: bool

    @property
    def completion(self) -> float:
        """實際持有 ÷ 預定天期。1.0 代表借滿，0.05 代表借了不到 5% 就被還回來。"""
        return self.hours / self.period_hours if self.period_hours else 0.0

    @property
    def annual_rate(self) -> float:
        """日利率換算年化（百分比），與日誌其他地方的講法一致。"""
        return self.rate * 365 * 100


@dataclass(frozen=True)
class HoldSummary:
    """一批部位的持有時間摘要。

    **平均／中位數／四分位一律只用已結束的部位算**：把下界混進去會讓數字看起來
    有根據，實際上是拿「還沒發生的事」充數。仍在借出中的那些只貢獻 `censored`
    這個計數，讓人看得出這份摘要蓋掉了多少樣本。
    """

    records: List[HoldRecord]
    settled_hours: List[float]
    censored: int
    approximate_opened: int
    unusable: int
    matured: int
    early: int
    matured_threshold: float
    detection_lag_hours: float

    @property
    def settled(self) -> int:
        return len(self.settled_hours)

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def censored_ratio(self) -> float:
        """有多少比例的部位還開著。比例越高，下面那些統計量蓋掉的就越多。"""
        return self.censored / self.total if self.total else 0.0

    @property
    def enough_for_quantile(self) -> bool:
        """樣本夠不夠報中位數／四分位，還是該直接把原始值攤開來看。"""
        return self.settled >= MIN_SAMPLES_FOR_QUANTILE

    def hours_listing(self) -> str:
        """已結束部位的持有時間，由小到大列出來，給小樣本用。"""
        return "、".join(f"{hours:.2f}h" for hours in sorted(self.settled_hours))

    @property
    def mean_hours(self) -> Optional[float]:
        return statistics.fmean(self.settled_hours) if self.settled_hours else None

    @property
    def median_hours(self) -> Optional[float]:
        return statistics.median(self.settled_hours) if self.settled_hours else None

    @property
    def p25_hours(self) -> Optional[float]:
        return self._quantile(0.25)

    @property
    def p75_hours(self) -> Optional[float]:
        return self._quantile(0.75)

    @property
    def mean_completion(self) -> Optional[float]:
        """已結束部位的平均完成率——直接對照 `hold_hours = period × 24` 那個假設。"""
        settled = [record for record in self.records if not record.censored]
        if not settled:
            return None
        return statistics.fmean(record.completion for record in settled)

    def _quantile(self, fraction: float) -> Optional[float]:
        """小樣本用「排序後取位置」而不是插值：n=5 時插值只是把雜訊算得更精緻。"""
        if not self.settled_hours:
            return None
        ordered = sorted(self.settled_hours)
        index = min(int(len(ordered) * fraction), len(ordered) - 1)
        return ordered[index]


def parse_moment(moment: Optional[str]) -> Optional[datetime]:
    """把 DB 裡的 ISO 字串轉回 datetime；轉不動回 None 而不是拋例外。

    **公開的（原本叫 `_parse`）**：`core/wait_time.py`（D045）要用同一條規則讀
    同一批時間戳。兩支模組各寫一份的話，「舊列帶 `+00:00`、新列帶 `+08:00`」
    這件事就會有兩個各自演化的答案——而時區不一致正是 `utils/clock.py` 存在的理由。

    舊列帶 `+00:00`、新列帶 `+08:00`，兩者都是 aware，相減得到的秒數正確
    （同 `db/repository.py` 的 `now_iso()` 說明）。
    """
    if not moment:
        return None
    try:
        parsed = datetime.fromisoformat(moment)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


@dataclass(frozen=True)
class PositionScreen:
    """篩過的部位，**以及被篩掉的是什麼**——兩者一起回傳。

    ## 為什麼篩選要有回傳值，不能只是少幾列

    `funding_positions` 同時記著**同一筆錢的兩個狀態**：`credit`（我們借出去的
    這一側）與 `loan`（交易所配對出去的那一側）。兩者的 `amount`／`rate`／
    `opened_at` 幾乎相同，於是把它們一起丟進統計，等於把同一筆生意數兩次
    ——這就是 **D057**：17 筆其實是 14 筆，平均持有 16.93h → 20.45h。

    篩掉它們很容易，**難的是不要靜靜地篩掉**。D026 那個家族的病不是「沒講」，
    是「講了一個不完整的樣本卻不說它不完整」。所以這裡回傳的不只是 `kept`，
    還有被排除的那些列本身，好讓報告能把它們印出來。

    ## `kind='loan'` 的列不刪、也不在 SQL 裡濾

    - **不刪**：它記錄真實發生過的狀態轉換，而且 B6 還缺 `funding_loans`
      的真實回應校正。**刪資料不是修法。**
    - **不在 `Repository.all_positions()` 裡濾**：那支的 docstring 已寫明
      「刻意不在 SQL 裡過濾，否則上層永遠不會發現自己只看到一部分」。
      在那裡加條件，正好犯它自己警告的錯。
    """

    kept: List[Dict[str, Any]]
    ghosts: List[Dict[str, Any]]
    split_groups: List[List[Dict[str, Any]]]
    split_window_seconds: float

    @property
    def episodes(self) -> int:
        """獨立放貸段數：`kept` 的筆數，但拆單只算一段。

        ⚠ **這個數字只用來報告，不用來加權統計**——理由見 `screen_positions()`。
        """
        merged = sum(len(group) - 1 for group in self.split_groups)
        return len(self.kept) - merged


def screen_positions(
    positions: List[Dict[str, Any]],
    split_window_seconds: float = DEFAULT_SPLIT_WINDOW_SECONDS,
) -> PositionScreen:
    """篩掉 `kind='loan'` 的幽靈樣本（D057），並**標記**出被拆單的那幾組。

    ## 兩種重複，只處理其中一種

    | | 是什麼 | 這裡怎麼做 |
    |---|---|---|
    | `loan`／`credit` | **同一筆錢的兩個狀態** | **排除**（D057，已確認） |
    | 拆單 | 一張掛單被交易所配對成多筆部位 | **只標記，不合併** |

    ## 🔴 為什麼拆單只標記不合併

    **因為上一次做這種合併，它靜默吃掉了樣本。** `wait_report` 實作時
    （D045）把「三張各自成交過的 9.50%」併成一段，五個校準樣本剩兩個
    ——而那次也是拿「同利率、時間接近」當依據的。

    拆單與「三張各自成交的同價單」在資料上長得幾乎一樣，**分不開**：
    真正的差別在「它們是不是同一張掛單配對出來的」，而 `funding_positions`
    **沒有記下來源的 `offer_id`**。在那個欄位補上之前，任何合併規則都是猜的。

    所以這裡的選擇是：**把猜的部分交給讀報告的人**。統計照 17 筆算，
    旁邊印一行「其中 3 筆疑似同一張單的拆單，獨立段數約 15」。
    **少算幾筆是隱形的，多印一行不是。**
    """
    kept: List[Dict[str, Any]] = []
    ghosts: List[Dict[str, Any]] = []
    for position in positions:
        # `kind` 是 None 的舊列一律留著：不確定它是什麼，就不要替它決定。
        if str(position.get("kind") or "").lower() == "loan":
            ghosts.append(position)
        else:
            kept.append(position)

    groups: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []

    def flush() -> None:
        if len(current) > 1:
            groups.append(list(current))

    for position in kept:
        opened = parse_moment(position.get("opened_at")) or parse_moment(
            position.get("first_seen_at")
        )
        if opened is None:
            flush()
            current.clear()
            continue
        if current:
            previous = current[-1]
            previous_opened = parse_moment(previous.get("opened_at")) or parse_moment(
                previous.get("first_seen_at")
            )
            same_terms = (
                previous.get("rate") == position.get("rate")
                and previous.get("period") == position.get("period")
                # 同時結清是拆單最強的訊號：分開成交的單不會剛好一起被還。
                and previous.get("closed_at") == position.get("closed_at")
            )
            within = (
                previous_opened is not None
                and abs((opened - previous_opened).total_seconds())
                <= split_window_seconds
            )
            if same_terms and within:
                current.append(position)
                continue
        flush()
        current = [position]
    flush()

    return PositionScreen(
        kept=kept,
        ghosts=ghosts,
        split_groups=groups,
        split_window_seconds=split_window_seconds,
    )


def build_record(
    position: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Optional[HoldRecord]:
    """把一列 `funding_positions` 換算成 `HoldRecord`；算不出來回 None。

    **算不出來就回 None，不要猜**：起算時間兩個欄位都壞掉的列，與其塞一個
    捏造的持有時間進統計，不如讓它缺席並由上層報出「有幾筆算不出來」。
    """
    now = now or clock.now()

    opened = parse_moment(position.get("opened_at"))
    approximate = False
    if opened is None:
        # 退用「第一次看到它」的時間：同樣是高估，但比整筆丟掉有用。
        opened = parse_moment(position.get("first_seen_at"))
        approximate = opened is not None
    if opened is None:
        return None

    closed = parse_moment(position.get("closed_at"))
    censored = closed is None
    end = closed or now

    hours = (end - opened).total_seconds() / 3600
    if hours < 0:
        # 時鐘倒退或資料錯亂。負的持有時間沒有任何解讀方式，一律排除。
        return None

    period_days = position.get("period") or 0
    return HoldRecord(
        position_id=str(position.get("position_id", "")),
        rate=float(position.get("rate") or 0.0),
        amount=float(position.get("amount") or 0.0),
        period_hours=float(period_days) * 24.0,
        hours=hours,
        censored=censored,
        opened_at_approximate=approximate,
    )


def summarize(
    positions: List[Dict[str, Any]],
    now: Optional[datetime] = None,
    matured_threshold: float = DEFAULT_MATURED_THRESHOLD,
    detection_lag_hours: float = 0.0,
) -> HoldSummary:
    """把一批部位彙總成 `HoldSummary`。

    `detection_lag_hours` 傳巡檢間隔（小時）。它不參與計算，只是跟著摘要一起
    走，好讓輸出能講出「這些數字被高估的上界是多少」——量測值旁邊沒有誤差來源，
    下一個讀到它的人就會把它當成精確值。
    """
    built = [build_record(position, now=now) for position in positions]
    records = [record for record in built if record is not None]

    settled = [record for record in records if not record.censored]
    return HoldSummary(
        records=records,
        settled_hours=[record.hours for record in settled],
        censored=sum(1 for record in records if record.censored),
        approximate_opened=sum(1 for record in records if record.opened_at_approximate),
        # 起算時間壞掉、或算出負數而被排除的列。**要報出來**：靜靜地少算幾筆，
        # 就是 D026 那個家族的病——不是沒講，是講了一個不完整的樣本卻不說。
        unusable=len(built) - len(records),
        matured=sum(1 for record in settled if record.completion >= matured_threshold),
        early=sum(1 for record in settled if record.completion < matured_threshold),
        matured_threshold=matured_threshold,
        detection_lag_hours=detection_lag_hours,
    )


@dataclass(frozen=True)
class RateSplit:
    """以利率中位數切開的兩組持有時間，用來看「越貴借越短」這個假設。"""

    pivot_rate: float
    cheaper: HoldSummary
    pricier: HoldSummary

    @property
    def gap_hours(self) -> Optional[float]:
        """便宜組中位數 − 昂貴組中位數。正值代表「越貴借越短」的方向成立。

        **任一組少於 `MIN_SAMPLES_FOR_QUANTILE` 筆就回 None**：那時候的「中位數」
        是插值插出來的，相減得到的差距會繼承那個虛構的數字，而差距正是這裡
        唯一想看的東西。算不出來就說算不出來，不要給一個看起來有根據的數。

        **方向成立不等於假設成立**：兩組各只有幾筆的時候，這個差值本身
        也可能只是雜訊。它是用來決定「值不值得繼續蒐集」的，不是結論。
        """
        if not self.comparable:
            return None
        return self.cheaper.median_hours - self.pricier.median_hours

    @property
    def at_pivot(self) -> int:
        """已結束樣本裡「利率剛好等於分界」的筆數。

        分界取的是中位數，而中位數**可能同時是眾數**。真的發生時，
        `< pivot` 會把整叢同利率的樣本一次掃進昂貴組——見 `degenerate`。
        """
        return sum(
            1
            for record in self.pricier.records
            if not record.censored and record.rate == self.pivot_rate
        )

    @property
    def displayed_at_pivot(self) -> int:
        """已結束樣本裡「年化印出來跟分界一模一樣」的筆數。

        **跟 `at_pivot` 不是同一個數字**，而差別會騙人：2026-08-29 的資料裡
        `at_pivot` 是 9、這一個是 10——第 10 筆的日利率是 0.00024972，
        分界是 0.00024971，**只差第 8 位小數，但年化都印成 9.11%**。

        報告若拿 `at_pivot` 去講「有幾筆的利率就是 9.11%」，讀的人會照著
        逐筆那一段去數，數出 10 筆然後以為報告算錯了。**兩個數字都要拿得到，
        講的時候才能說清楚是哪一種相同。**
        """
        return sum(
            1
            for record in self.pricier.records
            if not record.censored
            and round(record.annual_rate, 2) == round(self.pivot_rate * 365 * 100, 2)
        )

    @property
    def degenerate(self) -> bool:
        """這個分界**分不出組，而且不會因為多蒐集樣本而變好**。

        2026-08-29 的實例：16 筆已結束部位裡有 10 筆同為年化 9.11%，
        於是中位數也是 9.11%，`<` 把那 10 筆全掃進昂貴組，
        得到便宜組 1 筆／昂貴組 15 筆。

        **關鍵在「不會自己好」**：模型連續選同一個價位時，每多一筆樣本
        都同時把中位數釘在原地、又落進昂貴組。這時候報告若只說
        「還比不出來，要兩組各 3 筆」，等於暗示再等幾筆就會好——
        而那是錯的，它暗示的是一件不會發生的事（D026 靜默失效的同一族：
        報告印得出來、數字也不離譜，只是講了一件沒查證過的事）。
        """
        return self.at_pivot >= MIN_SAMPLES_FOR_QUANTILE and (
            self.cheaper.settled < MIN_SAMPLES_FOR_QUANTILE
        )

    @property
    def comparable(self) -> bool:
        """兩組是否都有足夠的已結束樣本，可以拿中位數互相比較。"""
        return (
            self.cheaper.settled >= MIN_SAMPLES_FOR_QUANTILE
            and self.pricier.settled >= MIN_SAMPLES_FOR_QUANTILE
        )


def split_by_rate(summary: HoldSummary) -> Optional[RateSplit]:
    """以**已結束部位的利率中位數**為界分成兩組，用來看「越貴借越短」是否成立。

    **這是描述，不是檢定**：樣本數在十幾筆的量級，算相關係數只會把雜訊包裝成
    小數點後三位的權威感。分組後把兩邊的中位數並排，看得出差距就繼續蒐集，
    看不出就是看不出——D036 記的正是「結論寫死、原始資料丟掉」這個病。

    仍在借出中的部位不參與分界（它們的持有時間只是下界），但會依利率落入
    對應那一組，好讓每組的 `censored` 講出該組蓋掉了多少。
    """
    settled = [record for record in summary.records if not record.censored]
    if len(settled) < 2:
        # 一筆分不出兩組。回 None 而不是回一個空殼，上層才會說「還分不出來」
        # 而不是印出兩組都是零的表格。
        return None

    pivot = statistics.median(record.rate for record in settled)
    cheap = [record for record in summary.records if record.rate < pivot]
    pricey = [record for record in summary.records if record.rate >= pivot]

    def regroup(group: List[HoldRecord]) -> HoldSummary:
        group_settled = [record for record in group if not record.censored]
        return HoldSummary(
            records=group,
            settled_hours=[record.hours for record in group_settled],
            censored=sum(1 for record in group if record.censored),
            approximate_opened=sum(1 for record in group if record.opened_at_approximate),
            # 分組是從已經建好的 record 切出來的，不會再有算不出來的列。
            unusable=0,
            matured=sum(
                1
                for record in group_settled
                if record.completion >= summary.matured_threshold
            ),
            early=sum(
                1
                for record in group_settled
                if record.completion < summary.matured_threshold
            ),
            matured_threshold=summary.matured_threshold,
            detection_lag_hours=summary.detection_lag_hours,
        )

    return RateSplit(pivot_rate=pivot, cheaper=regroup(cheap), pricier=regroup(pricey))


def describe_record(record: HoldRecord) -> str:
    """單筆的一行敘述，給「部位收回」那一刻的日誌用。

    仍在借出中的部位改口說「至少」——與 D039 對排隊位置越界時的處理一致：
    **講得出下界就講下界，不要把下界說成量測值。**
    """
    if record.censored:
        return (
            f"部位 {record.position_id}（年化 {record.annual_rate:.2f}%）"
            f"已借出 至少 {record.hours:.2f} 小時"
            f"，佔預定 {record.period_hours:.0f} 小時的 {record.completion * 100:.0f}%（仍在生息中）"
        )

    verdict = "借到期" if record.completion >= DEFAULT_MATURED_THRESHOLD else "提前還款"
    return (
        f"部位 {record.position_id}（年化 {record.annual_rate:.2f}%）"
        f"實際借出 {record.hours:.2f} 小時"
        f"，佔預定 {record.period_hours:.0f} 小時的 {record.completion * 100:.0f}%——{verdict}"
    )
