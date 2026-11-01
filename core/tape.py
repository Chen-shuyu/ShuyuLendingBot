# -*- coding: utf-8 -*-
"""逐筆成交：哪些成交真的掃過簿子、一張掛單什麼時候會被吃到（D075）。

**這支模組只算，不碰網路也不碰 DB**：抓資料是 `scripts/weekly_report.py` 的事。

## 為什麼不用 K 線

K 線高點混著「FRR 管道」的成交：10-14 23:57 那根「高點 11.09%」其實是一筆 900 萬 USD、
利率剛好等於 FRR 的成交，而我們掛更便宜的 10.95% 沒被吃，那段期間 10.95% 也一筆成交都沒有
——**它們沒有掃過簿子，是另一個管道**。K 線規則因此在天期 30 把等待算快 1.6 倍，
換成逐筆之後，真金掛單的等待重播天期 2、天期 30 都是 1.00×。

## 公開成交的欄位 `[ID, MTS, AMOUNT, RATE, PERIOD]`

- **負號＝放款掛單被吃**：我們每一筆真實成交都能在這裡找到一模一樣的金額與利率，而且是負號。
- 正號＝有人拿掛單去吃借款人的買方掛單，跟我們的掛單無關。

## 成交規則

一張 `(r, N)` 的單，同天期 ≤ N、利率**高於** r 的真掃單累積金額 ≥ 掛單金額，就算成交：

- 掃單照價格由低往高吃，跨天期；借款人的掛單天期 B 只能吃天期 ≥ B 的放款單。
  所以天期 M ≤ N 的真掃單只要價格高過 r，就一定會先吃到它；天期 M > N 的成交不算證據。
- 只算「高於」不算「等於」：同價位的排隊順序看不到，保守算沒輪到。

⚠ **界線**：階梯落差 0.30pp 是看著 10-14 那一筆收緊的，其餘 40 段不管怎麼調都對；
「天期 ≤ N 都算證據」只在 N=30 驗過沒有提早成交。**每週對帳的判準 1 就是它的樣本外驗證**（D076）。

記憶體：機器只有 7GB、機器人也在上面跑，所以用 `array` 不用 list of tuple。
"""

import bisect
import statistics
from array import array
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from core import earnings

HOUR_MS = 3_600_000

# FRR 管道的判準（D075 第二節）。利率 x ≥ FRR − 帶寬的負號成交，若前 30 秒內同天期沒有
# 真掃單落在 [x − 落差, x]——也就是沒有一路爬上來的階梯——就算 FRR 管道，不算掃過簿子。
FRR_BAND_PP = 0.30
LADDER_GAP_PP = 0.30
LADDER_WINDOW_MS = 30_000

# 重掛門檻：每小時重算一次，新價與場上差超過 2% 才重掛，排隊累積歸零（同正式環境）。
REPOST_TOLERANCE_PCT = 2.0

# `array` 滑動視窗的修剪門檻，只是為了不讓階梯清單無限長。
_LADDER_TRIM_AT = 50_000

Trade = Tuple[int, int, float, float, int]  # (id, mts, 帶正負號的金額, 利率, 天期)


def _annual_to_daily(annual_pct: float) -> float:
    return annual_pct / 36500


class TradeSeries:
    """單一天期、單一類別的成交序列（依時間排序）。建每小時索引：掃的時候整小時跳過。"""

    __slots__ = ("period", "mts", "rate", "amount", "hour_max", "hour_index")

    def __init__(self, period: int):
        self.period = period
        self.mts = array("q")
        self.rate = array("d")
        self.amount = array("d")
        self.hour_max: Dict[int, float] = {}
        self.hour_index: Dict[int, int] = {}

    def append(self, moment: int, rate: float, amount: float) -> None:
        hour = moment // HOUR_MS
        if hour not in self.hour_index:
            self.hour_index[hour] = len(self.mts)
            self.hour_max[hour] = rate
        elif rate > self.hour_max[hour]:
            self.hour_max[hour] = rate
        self.mts.append(moment)
        self.rate.append(rate)
        self.amount.append(amount)

    def __len__(self) -> int:
        return len(self.mts)


class Tape:
    """分類好的逐筆成交。"""

    def __init__(self) -> None:
        self.clean: Dict[int, TradeSeries] = {}
        self.frr_channel: Dict[int, TradeSeries] = {}
        self.positive: Dict[int, TradeSeries] = {}
        # 全部成交照原樣留一份（不分類、金額取絕對值）：`market_rate()` 看的就是這個。
        self._mts = array("q")
        self._rate = array("d")
        self._amount = array("d")
        self._period = array("i")

    def __len__(self) -> int:
        return len(self._mts)

    def evidence(self, period: int) -> List[TradeSeries]:
        """一張天期 `period` 的單，哪些成交算證據：天期 ≤ `period` 的真掃單。"""
        return [series for held, series in sorted(self.clean.items()) if held <= period]

    def trades_before(self, moment_ms: int, limit: int = 10_000) -> List[Dict[str, float]]:
        """`moment_ms` 之前最新的 `limit` 筆，形狀同 `BitfinexClient.get_recent_trades()`。

        正式環境每輪就是抓最新 1 萬筆（所有天期）丟給 `market_rate()`，所以這裡照做，
        不要另外實作一份「前 6 小時同天期」——兩份語意遲早分岔。
        """
        stop = bisect.bisect_left(self._mts, moment_ms)
        start = max(stop - limit, 0)
        return [
            {
                "mts": self._mts[index],
                "amount": self._amount[index],
                "rate": self._rate[index],
                "period": self._period[index],
            }
            for index in range(start, stop)
        ]


class FrrSeries:
    """FRR 時間序列（日利率），來自機器人每輪的 `market_snapshots`。"""

    def __init__(self, rows: Iterable[Tuple[int, float]]):
        ordered = sorted(rows)
        self.moments = [moment for moment, _ in ordered]
        self.values = [value for _, value in ordered]

    def at(self, moment_ms: int) -> Optional[float]:
        """那一刻最新的 FRR；比第一筆還早就用第一筆；完全沒資料回 `None`。"""
        if not self.values:
            return None
        index = bisect.bisect_right(self.moments, moment_ms) - 1
        return self.values[max(index, 0)]

    def longest_gap_hours(self, start_ms: int, end_ms: int) -> float:
        """窗內 FRR 資料最久的空窗。機器人停過的那段，FRR 管道的判準用的是舊值。"""
        points = [start_ms]
        points.extend(moment for moment in self.moments if start_ms < moment < end_ms)
        points.append(end_ms)
        return max(later - earlier for earlier, later in zip(points, points[1:])) / HOUR_MS


def build_tape(
    trades: Iterable[Trade],
    frr_at: Callable[[int], Optional[float]],
) -> Tape:
    """把公開成交分類成真掃單／FRR 管道／正號。`frr_at` 給某一刻的 FRR（日利率），每小時讀一次。

    `frr_at` 回 `None`（沒有 FRR 資料）時無從分辨，負號成交全部當真掃單——呼叫端要把這件事講出來。
    """
    tape = Tape()
    band = _annual_to_daily(FRR_BAND_PP)
    gap = _annual_to_daily(LADDER_GAP_PP)
    # 只留高價成交的滑動視窗（同天期各一份）：冷市場時很少，查階梯才快。
    ladders: Dict[int, Tuple[array, array]] = {}
    last_hour = None
    frr: Optional[float] = None

    for _trade_id, moment, amount, rate, period in sorted(trades, key=lambda row: (row[1], row[0])):
        if rate <= 0:
            # 同 `get_recent_trades()`：非正的利率沒有意義，整筆略過。
            continue
        tape._mts.append(moment)
        tape._rate.append(rate)
        tape._amount.append(abs(amount))
        tape._period.append(period)

        hour = moment // HOUR_MS
        if hour != last_hour:
            frr, last_hour = frr_at(moment), hour

        if amount > 0:
            tape.positive.setdefault(period, TradeSeries(period)).append(moment, rate, amount)
            continue

        size = -amount
        floor = None if frr is None else frr - band
        ladder_moments, ladder_rates = ladders.setdefault(period, (array("q"), array("d")))
        is_clean = True
        if floor is not None and rate >= floor:
            # 階梯要連續：前 30 秒內要有同天期的真掃單落在 [x − 落差, x]。
            # FRR 管道不算進階梯，所以一批 FRR 大單接不起來。
            lowest = rate - gap
            is_clean = False
            for index in range(
                bisect.bisect_left(ladder_moments, moment - LADDER_WINDOW_MS), len(ladder_moments)
            ):
                if lowest <= ladder_rates[index] <= rate:
                    is_clean = True
                    break
        if not is_clean:
            tape.frr_channel.setdefault(period, TradeSeries(period)).append(moment, rate, size)
            continue

        tape.clean.setdefault(period, TradeSeries(period)).append(moment, rate, size)
        if floor is not None and rate >= floor - gap:
            ladder_moments.append(moment)
            ladder_rates.append(rate)
            if len(ladder_moments) > _LADDER_TRIM_AT:
                cut = bisect.bisect_left(ladder_moments, moment - LADDER_WINDOW_MS)
                del ladder_moments[:cut]
                del ladder_rates[:cut]
    return tape


def find_fill(
    evidence: Sequence[TradeSeries],
    rate: float,
    start_ms: int,
    end_ms: int,
    need: float,
    accumulated: float = 0.0,
    strict: bool = True,
) -> Tuple[Optional[int], float]:
    """`[start_ms, end_ms)` 內第一個讓累積金額 ≥ `need` 的時刻。回傳 `(時刻或 None, 累積金額)`。

    證據可以來自多個天期，所以同一小時內要合併排序後再累積。
    """
    if end_ms <= start_ms or not evidence:
        return None, accumulated
    threshold = rate * (1 + 1e-9) if strict else rate * (1 - 1e-9)
    hour, last_hour = start_ms // HOUR_MS, (end_ms - 1) // HOUR_MS
    while hour <= last_hour:
        low, high = max(start_ms, hour * HOUR_MS), min(end_ms, (hour + 1) * HOUR_MS)
        hits = None
        for series in evidence:
            hour_high = series.hour_max.get(hour)
            if hour_high is None or hour_high < threshold:
                continue
            index = series.hour_index[hour]
            if low > hour * HOUR_MS:
                index = bisect.bisect_left(series.mts, low)
            mts, rates, amounts, count = series.mts, series.rate, series.amount, len(series.mts)
            while index < count and mts[index] < high:
                if rates[index] >= threshold:
                    if hits is None:
                        hits = []
                    hits.append((mts[index], amounts[index]))
                index += 1
        if hits:
            hits.sort()
            for moment, amount in hits:
                accumulated += amount
                if accumulated >= need:
                    return moment, accumulated
        hour += 1
    return None, accumulated


@dataclass(frozen=True)
class Carried:
    """窗開始時還借著的部位：這是事實，不是模型的結果，路徑要從它還回來才開始走。

    `rate` 是折算到全部本金的日利率、`share` 是它佔本金的比例：部分資金借出（拆單）時才不會多算。
    """

    rate: float
    share: float
    until_ms: int


@dataclass
class PathResult:
    """一條路徑的成績。`net_pct` 已扣 15% 抽成，分母是窗內的曆日（含閒置）。"""

    net_pct: float
    utilization_pct: float
    nominal_pct: Optional[float]
    fills: int
    waits_hours: List[float] = field(default_factory=list)
    trades: List[Tuple[int, float, float]] = field(default_factory=list)


def simulate_path(
    evidence: Sequence[TradeSeries],
    prices: Dict[int, Optional[float]],
    holds: Sequence[float],
    start_ms: int,
    end_ms: int,
    capital: float,
    cap_hours: Optional[float] = None,
    rotate: int = 0,
    strict: bool = True,
    tolerance_pct: float = REPOST_TOLERANCE_PCT,
    carried: Optional[Carried] = None,
) -> PathResult:
    """從 `start_ms` 走到 `end_ms`：掛單 → 等成交 → 持有 → 再掛（只有一張單、全部資金）。

    `prices`：`{小時編號: 日利率或 None}`。`None` 表示那一小時正式環境不會出計畫：
    手上沒單就空等，場上有單就留著（同 `bot_engine`「本輪無新計畫，維持場上既有掛單」）。
    `holds`：持有時數的樣本，依序輪流取，`rotate` 決定從第幾個開始。
    """
    if not holds:
        raise ValueError("持有樣本是空的，模擬不出來")
    fee = (100 - earnings.FUNDING_FEE_PCT) / 100
    interest = lent = 0.0
    fills = 0
    waits: List[float] = []
    trades: List[Tuple[int, float, float]] = []
    moment, cycle = start_ms, rotate
    if carried is not None:
        hours = (min(carried.until_ms, end_ms) - start_ms) / HOUR_MS
        if hours > 0:
            interest += carried.rate * hours
            lent += carried.share * hours
        moment = max(carried.until_ms, start_ms)
    while moment < end_ms:
        hour = moment // HOUR_MS
        rate = prices.get(hour)
        if rate is None:
            moment = (hour + 1) * HOUR_MS
            continue
        live, accumulated, cursor, filled = rate, 0.0, moment, None
        while cursor < end_ms:
            next_hour = (cursor // HOUR_MS + 1) * HOUR_MS
            fill, accumulated = find_fill(
                evidence, live, cursor, min(next_hour, end_ms), capital, accumulated, strict
            )
            if fill is not None:
                filled = fill
                break
            cursor = next_hour
            if cursor >= end_ms:
                break
            repriced = prices.get(cursor // HOUR_MS)
            if repriced is not None and abs(repriced - live) / repriced * 100 > tolerance_pct:
                live, accumulated = repriced, 0.0
        if filled is None:
            break
        waits.append((filled - moment) / HOUR_MS)
        hold = holds[cycle % len(holds)]
        cycle += 1
        if cap_hours:
            hold = min(hold, cap_hours)
        trades.append((filled, live, hold))
        released = filled + int(hold * HOUR_MS)
        hours = (min(released, end_ms) - filled) / HOUR_MS
        if hours > 0:
            interest += live * hours
            lent += hours
        fills += 1
        moment = released
    window_hours = (end_ms - start_ms) / HOUR_MS
    return PathResult(
        net_pct=interest / window_hours * 365 * 100 * fee,
        utilization_pct=lent / window_hours * 100,
        nominal_pct=interest / lent * 365 * 100 if lent else None,
        fills=fills,
        waits_hours=waits,
        trades=trades,
    )


@dataclass
class PathSummary:
    """跨起跑點的平均（D054）：單一條路徑的運氣太大，所以一律看跨起跑點。"""

    net_pct: float
    low_pct: float
    high_pct: float
    utilization_pct: float
    nominal_pct: Optional[float]
    fills: float


def across_starts(
    evidence: Sequence[TradeSeries],
    prices: Dict[int, Optional[float]],
    holds: Sequence[float],
    start_ms: int,
    end_ms: int,
    capital: float,
    cap_hours: Optional[float] = None,
    offsets_hours: Iterable[int] = range(0, 24),
    carried: Optional[Carried] = None,
    rotate_holds: bool = True,
) -> PathSummary:
    """不同起跑點各跑一次（順便輪替持有序列），回傳平均與範圍。

    有 `carried` 時起跑點是固定的（它還回來的那一刻），只輪替持有序列。
    `rotate_holds=False` 給「照實際持有順序走」用：每條路徑都從第一筆開始。
    """
    runs = [
        simulate_path(
            evidence,
            prices,
            holds,
            start_ms if carried is not None else start_ms + offset * HOUR_MS,
            end_ms,
            capital,
            cap_hours=cap_hours,
            rotate=index if rotate_holds else 0,
            carried=carried,
        )
        for index, offset in enumerate(offsets_hours)
    ]
    nets = [run.net_pct for run in runs]
    nominals = [run.nominal_pct for run in runs if run.nominal_pct is not None]
    return PathSummary(
        net_pct=statistics.fmean(nets),
        low_pct=min(nets),
        high_pct=max(nets),
        utilization_pct=statistics.fmean(run.utilization_pct for run in runs),
        nominal_pct=statistics.fmean(nominals) if nominals else None,
        fills=statistics.fmean(run.fills for run in runs),
    )


def collect_pages(
    fetch_page: Callable[[int, int, int], List[Trade]],
    start_ms: int,
    end_ms: int,
    page_size: int = 10_000,
    pause: Callable[[], None] = lambda: None,
) -> List[Trade]:
    """分頁抓完 `[start_ms, end_ms]` 的成交，去掉換頁時重複的那幾筆。

    下一頁從上一頁最後一筆的時刻開始，所以那一毫秒的成交會出現兩次。
    同一毫秒超過一整頁（幾乎不可能）就往前跳 1ms，免得卡死。
    `pause` 在兩頁之間呼叫：公開端點跟機器人共用 IP，要慢慢抓。
    """
    rows: List[Trade] = []
    cursor = start_ms
    seen_at_cursor: set = set()
    while cursor < end_ms:
        page = fetch_page(cursor, end_ms, page_size)
        if not page:
            break
        rows.extend(row for row in page if row[0] not in seen_at_cursor)
        if len(page) < page_size:
            break
        last = page[-1][1]
        if last > cursor:
            cursor = last
            seen_at_cursor = {row[0] for row in page if row[1] == last}
        else:
            cursor += 1
            seen_at_cursor = set()
        pause()
    return rows
