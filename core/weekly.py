# -*- coding: utf-8 -*-
"""每週對帳：實際 vs 模擬（D076 第二節）。

**這支模組只算，不碰網路也不寫 DB**：抓資料、推 LINE 是 `scripts/weekly_report.py` 的事。

## 為什麼要有它

D074 上線時說好每週對帳，但第一週（10-25～10-31）是另寫腳本手算的。
D069 那個錯了一週的數字教過：**手算不會留下它用了什麼分母**。而沒有人看的判準等於沒有判準，
所以這裡一條指令算完，每週自動推一則 LINE。

## 三個判準（寫死在 D076 第二節，方向都驗過）

| # | 比什麼 | 通過 | 沒過 |
|---|---|---|---|
| 1 | 部位推算 vs 照實際掛價 ＋ 實際持有重播 | 差 ≤ 0.5pp | 🔴 成交規則可能走鐘了 |
| 2 | 帳本實得 vs 現行設定的模擬 | 差 ≤ 1pp | 🟡 先查（可能只是持有時間的運氣） |
| 3 | 帳本實得 vs 上一版設定的模擬 | 輸不到 0.3pp 算打平 | **連續兩週**輸才回頭檢討 |

判準 3 只比較「改了」對「沒改」，所以不會懲罰市場本身變冷（D071／D072 的教訓）。

## 判準 2 的「先查」由工具自己做（D076 追記）

過去十週照字面算，有六週沒過，主要是模擬沒算週初帶進來的部位；算進去之後剩兩週，
再換成實際持有重跑，十週全部在 1pp 以內。所以：**模擬從真實的週初狀態開始**，
沒過就自動用實際持有重跑一次，那一次也對不上才要人看。
一個每週都在響的判準，跟沒有判準一樣（D023）。

## 定價一律走正式環境的程式

模擬用的掛價直接呼叫 `ExpectedValueStrategy.build_offer_plan()`，餵它當時看得到的 K 線與最新 1 萬筆成交。
**不另外實作一份定價**：兩份語意遲早分岔，而分岔之後對帳對的就不是線上那支程式了。
"""

import bisect
import copy
from collections import deque
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, time, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from core import earnings, hold_time, tape as tape_module
from core.tape import HOUR_MS, PathSummary, Tape
from strategies.base import FRR_OFFER_TYPES, OFFER_TYPE_LIMIT
from strategies.expected_value import ExpectedValueStrategy
from utils import clock

# 週日 18:30 之後才算上一週：要等週日那筆入帳（07:40～11:40）與帳本同步（每 6 小時）。
WEEK_READY_AT = time(18, 30)

REPLAY_TOLERANCE_PP = 0.5
CURRENT_TOLERANCE_PP = 1.0
PREVIOUS_TIE_PP = 0.3
# 帳本與部位是兩條獨立的路，差太多就有一邊出事（D072 第五節）。D072 的 0.3pp 是講整月的窗；
# 7 天的窗上入帳時刻本身就會造成落差，過去十週最大 0.30pp，所以這裡用 0.5pp。
# 缺一列入帳（約 0.05 USD）大約差 0.75pp，還是抓得到。
LEDGER_GAP_PP = 0.5
BACKUP_STALE_HOURS = 48.0

# 持有樣本少於這個筆數就借別的天期的（同時講出來）。
MIN_OWN_HOLD_SAMPLES = 10

# 事後看最好的固定價（M3）：4%～12%，每 0.5pp 一格。格子切太細只是把運氣算得更精緻。
FIXED_GRID_ANNUAL = tuple(x / 2 for x in range(8, 25))
REFERENCE_FIXED_ANNUAL = 8.0

LEVEL_OK = "ok"
LEVEL_WARNING = "warning"
LEVEL_CRITICAL = "critical"


@dataclass(frozen=True)
class Setting:
    """會影響掛單的三個旋鈕。地板用日利率，跟 `config.yaml` 同一個值，不要換算兩次。"""

    label: str
    offer_period: int
    assumed_hold_hours: float
    minimum_rate: float


def make_setting(period: int, hold_hours: float, minimum_rate: float) -> Setting:
    """組一個講得出來的設定。地板是日利率，年化四捨五入到小數兩位才不會印出 5.00014%。"""
    floor = round(minimum_rate * 36500, 2)
    return Setting(f"天期 {period}、P{hold_hours:g}、地板 {floor:g}%", period, hold_hours, minimum_rate)


# 上一版設定（判準 3）。**換設定時要跟著改**：這次的現行設定就是下次的上一版。
PREVIOUS_SETTING = Setting("天期 2、P12、地板 5%", 2, 12.0, 0.00013699)
# D074 的對照組：11-01～11-07 那週是最後一次算（它要連續兩週才算數，D076 第二節）。
LEGACY_SETTING = Setting("天期 2、P12、地板 8%", 2, 12.0, 0.00021918)
LEGACY_LAST_WEEK = Date(2026, 11, 1)


def midnight(day: Date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=clock.get_timezone())


def to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def latest_completed_week(now: datetime) -> Date:
    """現在可以算的最新一週的週日。週的定義：週日 00:00～週六 24:00（看哪天賺的，D072）。

    週日 18:30 之前，上一週還不算完成（入帳還沒同步），所以往前再退一週。
    """
    local = now.astimezone(clock.get_timezone())
    today = local.date()
    this_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    if today == this_sunday and local.time() < WEEK_READY_AT:
        this_sunday -= timedelta(days=7)
    return this_sunday - timedelta(days=7)


# --- 實際 ---------------------------------------------------------------------


@dataclass
class Actual:
    """這一週實際賺多少。兩條彼此獨立的路：一條讀帳本，一條讀部位。"""

    first: Date
    last: Date
    days: int
    capital: float
    earned_usd: float
    earned_pct: float  # ② 帳本，看哪天賺的（正式數字，D072）
    position_pct: float  # ③ 部位推算（交叉驗證）
    utilization_pct: float
    nominal_pct: Optional[float]
    ledger_rows: int


def _capital_for(earning_rows: Iterable[Dict[str, Any]], first: Date, last: Date) -> float:
    """分母：窗內已部署資金的平均；窗內一列都沒有（整週閒著）就退回最近一筆。"""
    dated = sorted(
        (row["date"], float(row["principal_avg"]))
        for row in earning_rows
        if row.get("principal_avg")
    )
    within = [value for day, value in dated if first.isoformat() <= day <= last.isoformat()]
    if within:
        return sum(within) / len(within)
    earlier = [value for day, value in dated if day <= last.isoformat()]
    if earlier:
        return earlier[-1]
    raise ValueError("`earnings_daily` 沒有任何已部署資金的紀錄，算不出實得年化（不猜分母，D051）")


def actual_numbers(
    earning_rows: Sequence[Dict[str, Any]],
    positions: Sequence[Dict[str, Any]],
    first: Date,
    last: Date,
    now: datetime,
) -> Actual:
    ledger_first, ledger_last = earnings.ledger_dates_for_earned(first, last)
    rows = [
        row
        for row in earning_rows
        if ledger_first.isoformat() <= row["date"] <= ledger_last.isoformat()
    ]
    earned_usd = sum(float(row["interest"]) for row in rows)
    capital = _capital_for(earning_rows, ledger_first, ledger_last)
    days = (last - first).days + 1

    start = midnight(first)
    end = min(midnight(last) + timedelta(days=1), now)
    covered_days = (end - start).total_seconds() / 86400
    fee = (100 - earnings.FUNDING_FEE_PCT) / 100
    gross = earnings.expected_gross_interest(positions, now=now, start=start, end=end)
    split = earnings.capital_utilization(positions, capital, start, end, now=now)
    return Actual(
        first=first,
        last=last,
        days=days,
        capital=capital,
        earned_usd=earned_usd,
        earned_pct=earned_usd / capital * 365 / days * 100,
        position_pct=gross * fee / capital * 365 / covered_days * 100 if covered_days > 0 else 0.0,
        utilization_pct=split["utilization_pct"] if split else 0.0,
        nominal_pct=split["nominal_annual_pct"] if split else None,
        ledger_rows=len(rows),
    )


# --- 持有樣本 -----------------------------------------------------------------


def hold_samples(
    screen: hold_time.PositionScreen,
    before: datetime,
) -> Dict[int, List[float]]:
    """各天期已結束部位的持有時數（依開倉時間排序）。**拆單只算一筆**，只看 `before` 之前開倉的。"""
    repeated = {
        id(position) for group in screen.split_groups for position in group[1:]
    }
    rows = []
    for position in screen.kept:
        if id(position) in repeated:
            continue
        record = hold_time.build_record(position, now=before)
        if record is None or record.censored:
            continue
        opened = hold_time.parse_moment(position.get("opened_at")) or hold_time.parse_moment(
            position.get("first_seen_at")
        )
        if opened >= before:
            continue
        rows.append((opened, int(position.get("period") or 0), record.hours))
    samples: Dict[int, List[float]] = {}
    for _, period, hours in sorted(rows, key=lambda row: row[0]):
        samples.setdefault(period, []).append(hours)
    return samples


def pick_holds(samples: Dict[int, List[float]], period: int) -> Tuple[List[float], str]:
    """這個天期的模擬要用哪一袋持有樣本，以及一句講得出來的來源。

    自己的樣本不夠就先借**比較長的天期**（D075 的「中」假設）：借款人可以提前還，
    所以長天期的持有時數在短天期也可能出現，上限由 `cap_hours` 裁掉。
    """
    own = samples.get(period, [])
    if len(own) >= MIN_OWN_HOLD_SAMPLES:
        return list(own), f"天期 {period} 實測 {len(own)} 筆"
    longer = sorted(held for held in samples if held > period)
    shorter = sorted((held for held in samples if held < period), reverse=True)
    for candidate in longer + shorter:
        if len(samples[candidate]) >= MIN_OWN_HOLD_SAMPLES:
            return list(samples[candidate]), (
                f"天期 {period} 只有 {len(own)} 筆，借天期 {candidate} 實測 "
                f"{len(samples[candidate])} 筆"
            )
    if own:
        return list(own), f"天期 {period} 實測 {len(own)} 筆（樣本少）"
    return [period * 24.0], "沒有任何樣本，假設借滿"


# --- 掛價 ---------------------------------------------------------------------


def strategy_for(config: Dict[str, Any], setting: Setting) -> ExpectedValueStrategy:
    copied = copy.deepcopy(config)
    section = copied.setdefault("strategy", {})
    section["offer_period"] = setting.offer_period
    section["assumed_hold_hours"] = setting.assumed_hold_hours
    section["minimum_rate"] = setting.minimum_rate
    return ExpectedValueStrategy(copied)


def hourly_prices(
    strategy: ExpectedValueStrategy,
    tape: Tape,
    candles: Sequence[Dict[str, Any]],
    start_ms: int,
    end_ms: int,
    capital: float,
    frr_at: Callable[[int], Optional[float]],
) -> Dict[int, Optional[float]]:
    """每小時開頭，正式環境的策略會掛什麼價。沒有計畫就是 `None`。

    只餵**那一刻之前**的資料，不偷看：K 線取開始時間早於這一刻的最後 `candle_limit` 根，
    成交取這一刻之前最新的 `trade_limit` 筆。
    """
    ordered = sorted(candles, key=lambda candle: candle["mts"])
    moments = [candle["mts"] for candle in ordered]
    prices: Dict[int, Optional[float]] = {}
    for hour in range(start_ms // HOUR_MS, (end_ms - 1) // HOUR_MS + 1):
        moment = hour * HOUR_MS
        stop = bisect.bisect_left(moments, moment)
        window = ordered[max(stop - strategy.candle_limit, 0) : stop]
        trades = tape.trades_before(moment, strategy.trade_limit)
        plans = strategy.build_offer_plan(capital, frr_at(moment) or 0.0, None, trades, window)
        prices[hour] = plans[0].rate if plans else None
    return prices


def fixed_prices(annual_pct: float, start_ms: int, end_ms: int) -> Dict[int, Optional[float]]:
    rate = annual_pct / 36500
    return {hour: rate for hour in range(start_ms // HOUR_MS, (end_ms - 1) // HOUR_MS + 1)}


# --- 重播：實際掛價 ＋ 實際持有 ---------------------------------------------------


@dataclass
class RealOffer:
    posted_ms: int
    until_ms: int
    rate: float
    period: int
    amount: float
    filled_at_ms: Optional[int] = None
    hold_hours: Optional[float] = None
    offer_type: str = OFFER_TYPE_LIMIT
    # 實際成交的金額與金額加權利率。FRR 單的 `rate` 是偏移量，真正的利率只有成交之後才知道。
    filled_amount: float = 0.0
    fill_rate: Optional[float] = None

    @property
    def is_frr(self) -> bool:
        return self.offer_type in FRR_OFFER_TYPES


def _position_span_ms(position: Dict[str, Any], now_ms: int) -> Optional[Tuple[int, int]]:
    opened = hold_time.parse_moment(position.get("opened_at")) or hold_time.parse_moment(
        position.get("first_seen_at")
    )
    if opened is None:
        return None
    closed = hold_time.parse_moment(position.get("closed_at"))
    return to_ms(opened), to_ms(closed) if closed else now_ms


def carried_in(
    positions: Sequence[Dict[str, Any]],
    start_ms: int,
    capital: float,
    now_ms: int,
) -> Optional[tape_module.Carried]:
    """窗開始時還借著的部位。多筆（拆單）併成一筆，到最後一筆還回來為止。"""
    rows = []
    for position in positions:
        span = _position_span_ms(position, now_ms)
        if span and span[0] < start_ms < span[1]:
            rows.append((float(position.get("amount") or 0.0), float(position.get("rate") or 0.0), span[1]))
    if not rows:
        return None
    return tape_module.Carried(
        rate=sum(amount * rate for amount, rate, _ in rows) / capital,
        share=sum(amount for amount, _, _ in rows) / capital,
        until_ms=max(until for _, _, until in rows),
    )


def real_offers(
    offer_rows: Sequence[Dict[str, Any]],
    positions: Sequence[Dict[str, Any]],
    horizon_ms: int,
    now_ms: int,
) -> List[RealOffer]:
    """真金掛單的存活區間，並配上它成交成的部位。

    機器人先取消再掛，所以一張單活到下一張送出為止。成交靠「同利率同天期、開倉時間落在區間內」配對。
    """
    rows = sorted(
        (row for row in offer_rows if row.get("status") == "submitted"),
        key=lambda row: to_ms(datetime.fromisoformat(row["created_at"])),
    )
    spans = []
    for position in positions:
        span = _position_span_ms(position, now_ms)
        if span:
            spans.append((span[0], span[1], position))

    offers: List[RealOffer] = []
    for index, row in enumerate(rows):
        posted = to_ms(datetime.fromisoformat(row["created_at"]))
        until = (
            to_ms(datetime.fromisoformat(rows[index + 1]["created_at"]))
            if index + 1 < len(rows)
            else horizon_ms
        )
        rate, period = float(row["rate"]), int(row["duration"])
        offer_type = row.get("offer_type") or OFFER_TYPE_LIMIT
        is_frr = offer_type in FRR_OFFER_TYPES
        fills = [
            (opened, closed, position)
            for opened, closed, position in spans
            if posted - 2000 <= opened < until
            # FRR 單的 rate 是偏移量，配不上部位的利率，只能看天期與時間。
            and (is_frr or abs(float(position.get("rate") or 0.0) - rate) < 2e-8)
            and int(position.get("period") or 0) == period
        ]
        filled_at = min((fill[0] for fill in fills), default=None)
        hold = None
        total = 0.0
        fill_rate = None
        if fills:
            # 拆單：用金額加權的持有時數，USD × 小時才對得上實際。
            total = sum(float(fill[2].get("amount") or 0.0) for fill in fills)
            hold = (
                sum(
                    (fill[1] - fill[0]) / HOUR_MS * float(fill[2].get("amount") or 0.0)
                    for fill in fills
                )
                / total
                if total
                else 0.0
            )
            fill_rate = (
                sum(float(fill[2].get("rate") or 0.0) * float(fill[2].get("amount") or 0.0) for fill in fills)
                / total
                if total
                else None
            )
        offers.append(
            RealOffer(
                posted_ms=posted,
                until_ms=until,
                rate=rate,
                period=period,
                amount=float(row["amount"]),
                filled_at_ms=filled_at,
                hold_hours=hold,
                offer_type=offer_type,
                filled_amount=total,
                fill_rate=fill_rate,
            )
        )
    return offers


def periods_used(offers: Sequence[RealOffer], start_ms: int, end_ms: int) -> Dict[int, float]:
    """窗內每個天期的掛單活了幾小時（成交之後不算），用來判斷這週實際跑的是哪個天期。"""
    used: Dict[int, float] = {}
    for offer in offers:
        # FRR 單不是模型定的價，不能拿它來決定「現行設定」是哪個天期（D076 第三節的對照組是天期 7）。
        if offer.is_frr:
            continue
        stop = offer.filled_at_ms if offer.filled_at_ms is not None else offer.until_ms
        hours = (min(stop, end_ms) - max(offer.posted_ms, start_ms)) / HOUR_MS
        if hours > 0:
            used[offer.period] = used.get(offer.period, 0.0) + hours
    return used


@dataclass
class Replay:
    net_pct: float
    utilization_pct: float
    fills: int
    real_fills: int


def replay_real_offers(
    tape: Tape,
    offers: Sequence[RealOffer],
    positions: Sequence[Dict[str, Any]],
    start_ms: int,
    end_ms: int,
    capital: float,
    fallback_hold_hours: float,
    now_ms: int,
) -> Replay:
    """用**實際的掛價與持有**走一遍，成交時刻只看逐筆規則（判準 1）。

    這一條沒有定價也沒有持有樣本，唯一會錯的就是成交規則：**它對不上，就是規則走鐘了。**
    規則看到的只有「比我們貴的成交」，不看我們自己的成交，所以不是循環論證。

    - 週初還借著的部位不是這週的規則決定的，照實際算，錢在它還回來之前不能動。
    - 重播的單不會因為真的那張成交了就消失，它一直活到下一張真單送出；
      規則比實際晚成交，後面的路徑就跟著偏掉，這正是要量的東西。
    - 第 k 次成交用第 k 筆實際持有；規則多成交出來的（實際沒有的）用 `fallback_hold_hours`。
    - FRR 單不在逐筆規則管得到的範圍（D075），它的成交照實際算，只佔住資金。
    """
    fee = (100 - earnings.FUNDING_FEE_PCT) / 100
    usd_interest = usd_hours = 0.0
    free_at = start_ms

    def book(amount: float, rate: float, opened_ms: int, closed_ms: int) -> None:
        nonlocal usd_interest, usd_hours
        hours = (min(closed_ms, end_ms) - max(opened_ms, start_ms)) / HOUR_MS
        if hours > 0:
            usd_interest += amount * rate * hours / 24
            usd_hours += amount * hours

    for position in positions:
        span = _position_span_ms(position, now_ms)
        if span and span[0] < start_ms < span[1]:
            book(float(position.get("amount") or 0.0), float(position.get("rate") or 0.0), *span)
            free_at = max(free_at, span[1])

    in_window = [
        offer
        for offer in offers
        if offer.posted_ms < end_ms
        and offer.until_ms > start_ms
        and not (offer.filled_at_ms is not None and offer.filled_at_ms < start_ms)
    ]
    holds = deque(
        offer.hold_hours
        for offer in in_window
        if offer.filled_at_ms is not None and offer.filled_at_ms < end_ms and not offer.is_frr
    )
    real_fills = len(holds)
    fills = 0
    for offer in in_window:
        if offer.is_frr:
            if offer.filled_at_ms is not None and offer.filled_at_ms < end_ms:
                released = offer.filled_at_ms + int(offer.hold_hours * HOUR_MS)
                book(offer.filled_amount, offer.fill_rate or 0.0, offer.filled_at_ms, released)
                free_at = max(free_at, released)
            continue
        begin = max(offer.posted_ms + 3000, free_at, start_ms)
        stop = min(offer.until_ms, end_ms)
        if begin >= stop:
            continue
        fill, _ = tape_module.find_fill(
            tape.evidence(offer.period), offer.rate, begin, stop, offer.amount
        )
        if fill is None:
            continue
        hold = holds.popleft() if holds else fallback_hold_hours
        released = fill + int(hold * HOUR_MS)
        book(offer.amount, offer.rate, fill, released)
        free_at = released
        fills += 1

    window_hours = (end_ms - start_ms) / HOUR_MS
    return Replay(
        net_pct=usd_interest * fee / capital * 365 * 24 / window_hours * 100,
        utilization_pct=usd_hours / (capital * window_hours) * 100,
        fills=fills,
        real_fills=real_fills,
    )


# --- 判準 ---------------------------------------------------------------------


@dataclass
class Check:
    label: str
    level: str  # LEVEL_OK／WARNING／CRITICAL
    detail: str
    # 給 LINE 用的短句（一行塞得下）。
    summary: str
    action_required: bool = False

    @property
    def passed(self) -> bool:
        return self.level == LEVEL_OK


def check_replay(actual: Actual, replay: Replay) -> Check:
    gap = actual.position_pct - replay.net_pct
    summary = f"{replay.net_pct:.2f}%，差 {gap:+.2f}pp"
    fills = f"成交 {replay.fills} 次（實際 {replay.real_fills} 次）"
    if abs(gap) <= REPLAY_TOLERANCE_PP:
        return Check(
            "判準 1 重播",
            LEVEL_OK,
            f"部位推算 {actual.position_pct:.2f}% 對 重播 {replay.net_pct:.2f}%，"
            f"差 {gap:+.2f}pp（≤ {REPLAY_TOLERANCE_PP}），{fills}",
            f"{summary} ✅",
        )
    return Check(
        "判準 1 重播",
        LEVEL_CRITICAL,
        f"部位推算 {actual.position_pct:.2f}% 對 重播 {replay.net_pct:.2f}%，"
        f"差 {gap:+.2f}pp（> {REPLAY_TOLERANCE_PP}），{fills}。"
        "實際掛價與實際持有都是真的，只有成交規則是推的：成交規則可能走鐘了，先查",
        f"{summary} 🔴 對不上",
        action_required=True,
    )


def check_current(
    actual: Actual,
    simulated: PathSummary,
    with_actual_holds: PathSummary,
    label: str,
) -> Check:
    """判準 2。沒過時「先查」的那一步由這裡做：換成實際持有重跑，看是不是運氣（模組說明）。"""
    gap = actual.earned_pct - simulated.net_pct
    summary = f"{simulated.net_pct:.2f}%，差 {gap:+.2f}pp"
    head = (
        f"帳本實得 {actual.earned_pct:.2f}% 對 {label} 模擬 {simulated.net_pct:.2f}%，差 {gap:+.2f}pp"
    )
    if abs(gap) <= CURRENT_TOLERANCE_PP:
        return Check("判準 2 現行設定", LEVEL_OK, f"{head}（≤ {CURRENT_TOLERANCE_PP}）", f"{summary} ✅")
    held_gap = actual.earned_pct - with_actual_holds.net_pct
    retried = f"換成實際持有重跑是 {with_actual_holds.net_pct:.2f}%，差 {held_gap:+.2f}pp"
    if abs(held_gap) <= CURRENT_TOLERANCE_PP:
        return Check(
            "判準 2 現行設定",
            LEVEL_OK,
            f"{head}（> {CURRENT_TOLERANCE_PP}），但{retried}：差距來自持有時間的運氣，定價與成交都對得上",
            f"{summary}，持有時間的運氣（重跑差 {held_gap:+.2f}pp）✅",
        )
    return Check(
        "判準 2 現行設定",
        LEVEL_WARNING,
        f"{head}（> {CURRENT_TOLERANCE_PP}），而且{retried}：不是持有的運氣，"
        "定價或成交跟模型對不上。先看判準 1：過了就是定價的問題，沒過就是成交規則的問題",
        f"{summary}，重跑差 {held_gap:+.2f}pp 🟡 先查",
        action_required=True,
    )


def check_frr(actual: Actual, comparator: PathSummary, label: str) -> Check:
    """FRR 實測中的週。**判定看累積，不看單週**（D076 第三節），所以這裡只報數字、不響。"""
    gap = actual.earned_pct - comparator.net_pct
    return Check(
        "FRR 實測",
        LEVEL_OK,
        f"帳本實得 {actual.earned_pct:.2f}% 對 同期 {label} 模擬 {comparator.net_pct:.2f}%，差 {gap:+.2f}pp。"
        "判定看累積（完成 2 筆或滿 45 天），不看單週",
        f"對 {label} 模擬 {comparator.net_pct:.2f}%，差 {gap:+.2f}pp",
    )


def lost_to_previous(actual: Actual, previous: PathSummary) -> bool:
    return actual.earned_pct < previous.net_pct - PREVIOUS_TIE_PP


def check_previous(
    actual: Actual,
    previous: PathSummary,
    label: str,
    lost_last_week: Optional[bool],
) -> Check:
    """判準 3。**只有連續兩週輸才要人看**：單週的持有運氣很大（D076 第四節）。"""
    gap = actual.earned_pct - previous.net_pct
    summary = f"{previous.net_pct:.2f}%，差 {gap:+.2f}pp"
    head = f"帳本實得 {actual.earned_pct:.2f}% 對 {label} 模擬 {previous.net_pct:.2f}%，差 {gap:+.2f}pp"
    if not lost_to_previous(actual, previous):
        return Check("判準 3 上一版設定", LEVEL_OK, f"{head}（輸不到 {PREVIOUS_TIE_PP}pp 算打平）", f"{summary} ✅")
    if lost_last_week:
        return Check(
            "判準 3 上一版設定",
            LEVEL_WARNING,
            f"{head}。連續兩週輸給上一版設定，該回頭檢討這次的改動",
            f"{summary} 🟡 連兩週輸",
            action_required=True,
        )
    return Check(
        "判準 3 上一版設定",
        LEVEL_OK,
        f"{head}。這週輸了，但要連續兩週才算數"
        + ("（上週沒有紀錄）" if lost_last_week is None else ""),
        f"{summary} ⚠ 輸一週",
    )


def check_ledger(actual: Actual) -> Check:
    """帳本與部位是兩條獨立的路：差太多就有一邊缺資料（D072 第五節）。"""
    gap = actual.earned_pct - actual.position_pct
    summary = f"差 {gap:+.2f}pp"
    head = f"帳本 {actual.earned_pct:.2f}% 對 部位推算 {actual.position_pct:.2f}%，差 {gap:+.2f}pp"
    if abs(gap) <= LEDGER_GAP_PP:
        return Check("帳本對部位", LEVEL_OK, f"{head}（≤ {LEDGER_GAP_PP}）", f"{summary} ✅")
    return Check(
        "帳本對部位",
        LEVEL_WARNING,
        f"{head}（> {LEDGER_GAP_PP}）。可能是帳本還沒同步、某天缺列，或部位沒記全；"
        "7 天的窗上入帳時刻也會造成落差，先查再看其他判準",
        f"{summary} 🟡 先查",
        action_required=True,
    )


def check_backup(last_ok_at: Optional[str], now: datetime) -> Check:
    """備份壞了最怕沒人知道（D076）：定時器自己沒跑的時候，這裡是唯一會出聲的地方。"""
    moment = hold_time.parse_moment(last_ok_at)
    if moment is None:
        return Check(
            "備份",
            LEVEL_WARNING,
            "找不到最近一次成功的紀錄（backup_status.json）",
            "沒有紀錄 🟡",
            action_required=True,
        )
    hours = (now - moment).total_seconds() / 3600
    if hours > BACKUP_STALE_HOURS:
        return Check(
            "備份",
            LEVEL_WARNING,
            f"最近一次成功是 {hours:.0f} 小時前（> {BACKUP_STALE_HOURS:.0f}）",
            f"{hours:.0f} 小時前 🟡",
            action_required=True,
        )
    return Check("備份", LEVEL_OK, f"最近一次成功是 {hours:.0f} 小時前", f"{hours:.0f} 小時前 ✅")


# --- 報告 ---------------------------------------------------------------------


@dataclass
class WeeklyInputs:
    """算一週需要的全部資料。呼叫端負責抓好，這裡不碰網路與 DB。"""

    config: Dict[str, Any]
    tape: Tape
    candles: Dict[int, List[Dict[str, Any]]]
    earning_rows: List[Dict[str, Any]]
    position_rows: List[Dict[str, Any]]
    offer_rows: List[Dict[str, Any]]
    frr_at: Callable[[int], Optional[float]]
    first: Date
    last: Date
    now: datetime
    setting: Setting
    backup_last_ok_at: Optional[str] = None
    lost_last_week: Optional[bool] = None
    caveats: List[str] = field(default_factory=list)


@dataclass
class WeeklyReport:
    first: Date
    last: Date
    actual: Actual
    setting: Setting
    holds_label: str
    periods: Dict[int, float]
    replay: Replay
    current: PathSummary
    current_actual_holds: PathSummary
    previous: Optional[PathSummary]
    previous_setting: Optional[Setting]
    legacy: Optional[PathSummary]
    fixed_reference: PathSummary
    best_fixed_annual: float
    best_fixed: PathSummary
    lost_to_previous: Optional[bool]
    checks: List[Check]
    caveats: List[str]

    @property
    def period_label(self) -> str:
        return f"{self.first.strftime('%m-%d')}～{self.last.strftime('%m-%d')}"

    @property
    def level(self) -> str:
        levels = {check.level for check in self.checks}
        if LEVEL_CRITICAL in levels:
            return LEVEL_CRITICAL
        return LEVEL_WARNING if LEVEL_WARNING in levels else LEVEL_OK

    @property
    def action_required(self) -> bool:
        return any(check.action_required for check in self.checks)

    def to_record(self) -> Dict[str, Any]:
        """存進 `bot_kv` 的摘要：下週判準 3 要看這週有沒有輸，日後也查得到當時算了什麼。"""
        return {
            "first": self.first.isoformat(),
            "last": self.last.isoformat(),
            "earned_pct": round(self.actual.earned_pct, 4),
            "position_pct": round(self.actual.position_pct, 4),
            "utilization_pct": round(self.actual.utilization_pct, 2),
            "nominal_pct": self.actual.nominal_pct and round(self.actual.nominal_pct, 4),
            "replay_pct": round(self.replay.net_pct, 4),
            "current_sim_pct": round(self.current.net_pct, 4),
            "current_actual_holds_pct": round(self.current_actual_holds.net_pct, 4),
            "previous_sim_pct": self.previous and round(self.previous.net_pct, 4),
            "lost_to_previous": self.lost_to_previous,
            "setting": self.setting.label,
            "level": self.level,
            # 完整報告也存起來：這台機器的 user journal 沒有保存，stdout 跑完就不見了。
            "text": format_report(self),
        }


def default_setting(
    config: Dict[str, Any],
    offer_rows: Sequence[Dict[str, Any]],
    position_rows: Sequence[Dict[str, Any]],
    start_ms: int,
    end_ms: int,
    now_ms: int,
) -> Setting:
    """這週要拿哪個設定當「現行設定」：天期看掛單實際用最久的，P 與地板看設定檔。

    🔴 **不能直接拿設定檔的天期**：週中才換設定的話，那一週大部分時間跑的不是它；
    補算過去的週也一樣。沒掛過單就退回設定檔。
    """
    section = config.get("strategy") or {}
    positions = hold_time.screen_positions(list(position_rows)).kept
    used = periods_used(real_offers(offer_rows, positions, end_ms, now_ms), start_ms, end_ms)
    period = max(used, key=lambda held: used[held]) if used else int(section["offer_period"])
    return make_setting(period, float(section["assumed_hold_hours"]), float(section["minimum_rate"]))


def periods_to_price(setting: Setting, first: Date) -> List[int]:
    """這週的報告要抓哪幾個天期的 K 線。"""
    needed = {setting.offer_period, PREVIOUS_SETTING.offer_period}
    if first <= LEGACY_LAST_WEEK:
        needed.add(LEGACY_SETTING.offer_period)
    return sorted(needed)


def build_report(inputs: WeeklyInputs) -> WeeklyReport:
    first, last, now = inputs.first, inputs.last, inputs.now
    start_ms = to_ms(midnight(first))
    end_ms = min(to_ms(midnight(last) + timedelta(days=1)), to_ms(now))
    now_ms = to_ms(now)

    screen = hold_time.screen_positions(inputs.position_rows)
    positions = screen.kept
    actual = actual_numbers(inputs.earning_rows, positions, first, last, now)
    capital = actual.capital

    samples = hold_samples(screen, midnight(last) + timedelta(days=1))
    offers = real_offers(inputs.offer_rows, positions, end_ms, now_ms)
    used = periods_used(offers, start_ms, end_ms)

    def prices_for(setting: Setting) -> Dict[int, Optional[float]]:
        return hourly_prices(
            strategy_for(inputs.config, setting),
            inputs.tape,
            inputs.candles[setting.offer_period],
            start_ms,
            end_ms,
            capital,
            inputs.frr_at,
        )

    def simulate(setting: Setting) -> PathSummary:
        """對照組：不知道它的週初會是什麼狀態，所以從空手開始，跨起跑點平均。"""
        holds, _ = pick_holds(samples, setting.offer_period)
        return tape_module.across_starts(
            inputs.tape.evidence(setting.offer_period),
            prices_for(setting),
            holds,
            start_ms,
            end_ms,
            capital,
            cap_hours=setting.offer_period * 24.0,
        )

    def fixed(annual_pct: float) -> PathSummary:
        holds, _ = pick_holds(samples, inputs.setting.offer_period)
        return tape_module.across_starts(
            inputs.tape.evidence(inputs.setting.offer_period),
            fixed_prices(annual_pct, start_ms, end_ms),
            holds,
            start_ms,
            end_ms,
            capital,
            cap_hours=inputs.setting.offer_period * 24.0,
        )

    frr_active = any(
        offer.is_frr and offer.posted_ms < end_ms and offer.until_ms > start_ms for offer in offers
    )
    # 現行設定：從真實的週初狀態開始（模組說明），因為週初那張單就是現行設定掛的。
    # FRR 實測中例外：模擬是對照組（同期天期 7），週初那筆 FRR 部位不是它掛的。
    fallback_holds, holds_label = pick_holds(samples, inputs.setting.offer_period)
    current_prices = prices_for(inputs.setting)
    carried = None if frr_active else carried_in(positions, start_ms, capital, now_ms)
    current_evidence = inputs.tape.evidence(inputs.setting.offer_period)
    current = tape_module.across_starts(
        current_evidence,
        current_prices,
        fallback_holds,
        start_ms,
        end_ms,
        capital,
        cap_hours=inputs.setting.offer_period * 24.0,
        carried=carried,
    )
    actual_holds = [
        offer.hold_hours
        for offer in offers
        if offer.filled_at_ms is not None
        and start_ms <= offer.filled_at_ms < end_ms
        and offer.hold_hours is not None
        and not offer.is_frr
    ]
    current_actual_holds = tape_module.across_starts(
        current_evidence,
        current_prices,
        actual_holds + fallback_holds,
        start_ms,
        end_ms,
        capital,
        carried=carried,
        rotate_holds=False,
    )
    replay = replay_real_offers(
        inputs.tape,
        offers,
        positions,
        start_ms,
        end_ms,
        capital,
        sum(fallback_holds) / len(fallback_holds),
        now_ms,
    )

    same_as_previous = (
        PREVIOUS_SETTING.offer_period == inputs.setting.offer_period
        and PREVIOUS_SETTING.assumed_hold_hours == inputs.setting.assumed_hold_hours
        and PREVIOUS_SETTING.minimum_rate == inputs.setting.minimum_rate
    )
    previous = None if same_as_previous else simulate(PREVIOUS_SETTING)
    legacy = simulate(LEGACY_SETTING) if first <= LEGACY_LAST_WEEK else None

    reference = fixed(REFERENCE_FIXED_ANNUAL)
    grid = {annual: fixed(annual) for annual in FIXED_GRID_ANNUAL}
    best_annual = max(grid, key=lambda annual: grid[annual].net_pct)

    checks = [check_ledger(actual), check_replay(actual, replay)]
    lost = None
    if frr_active:
        # 判準 2、3 比的是「模型定的價」：這幾週跑的不是它，比了只會一直響。
        checks.append(check_frr(actual, current, inputs.setting.label))
    else:
        checks.append(check_current(actual, current, current_actual_holds, inputs.setting.label))
        if previous is not None:
            lost = lost_to_previous(actual, previous)
            checks.append(
                check_previous(actual, previous, PREVIOUS_SETTING.label, inputs.lost_last_week)
            )
    checks.append(check_backup(inputs.backup_last_ok_at, now))

    caveats = list(inputs.caveats)
    if frr_active:
        caveats.append("FRR 實測中：判準 2、3 不適用，重播裡的 FRR 單照實際算")
    if len(used) > 1:
        detail = "、".join(f"天期 {period} {hours:.0f} 小時" for period, hours in sorted(used.items()))
        caveats.append(f"這週換過天期（掛單時間：{detail}），實際不是單一設定跑出來的")
    orphans_in_window = [
        row
        for row in screen.orphans
        if (span := _position_span_ms(row, now_ms)) and span[0] < end_ms and span[1] > start_ms
    ]
    if orphans_in_window:
        caveats.append(
            f"有 {len(orphans_in_window)} 筆沒有 credit 雙胞胎的 loan 算進部位推算（D076）"
        )

    return WeeklyReport(
        first=first,
        last=last,
        actual=actual,
        setting=inputs.setting,
        holds_label=holds_label,
        periods=used,
        replay=replay,
        current=current,
        current_actual_holds=current_actual_holds,
        previous=previous,
        previous_setting=None if same_as_previous else PREVIOUS_SETTING,
        legacy=legacy,
        fixed_reference=reference,
        best_fixed_annual=best_annual,
        best_fixed=grid[best_annual],
        lost_to_previous=lost,
        checks=checks,
        caveats=caveats,
    )


def _sim_line(label: str, summary: PathSummary) -> str:
    nominal = f"{summary.nominal_pct:.2f}%" if summary.nominal_pct is not None else "—"
    return (
        f"  {label}：{summary.net_pct:.2f}%（{summary.low_pct:.2f}～{summary.high_pct:.2f}）"
        f"利用率 {summary.utilization_pct:.1f}%、名目 {nominal}、成交 {summary.fills:.1f} 次"
    )


def format_report(report: WeeklyReport) -> str:
    """給人看的完整版。"""
    actual = report.actual
    nominal = f"{actual.nominal_pct:.2f}%" if actual.nominal_pct is not None else "—"
    lines = [f"=== 週報 {report.period_label}（週日 00:00～週六 24:00，看哪天賺的）===", ""]
    lines.append("實際")
    lines.append(
        f"  帳本實得（正式）：{actual.earned_pct:.2f}%"
        f"（{actual.earned_usd:.4f} USD ／ 本金 {actual.capital:.2f} USD ／ {actual.days} 天，"
        f"{actual.ledger_rows} 列入帳）"
    )
    lines.append(f"  部位推算（交叉驗證）：{actual.position_pct:.2f}%")
    lines.append(f"  利用率 {actual.utilization_pct:.1f}%、金額加權名目 {nominal}")
    lines.append("")
    lines.append("判準（D076 第二節）")
    for check in report.checks:
        mark = {LEVEL_OK: "✅", LEVEL_WARNING: "🟡", LEVEL_CRITICAL: "🔴"}[check.level]
        lines.append(f"  {mark} {check.label}：{check.detail}")
    lines.append("")
    lines.append(f"模擬（逐筆規則、跨 24 個起跑點；持有樣本：{report.holds_label}）")
    lines.append(_sim_line(f"現行設定 {report.setting.label}", report.current))
    lines.append(_sim_line("　同上，換成實際持有", report.current_actual_holds))
    if report.previous is not None and report.previous_setting is not None:
        lines.append(_sim_line(f"上一版設定 {report.previous_setting.label}", report.previous))
    if report.legacy is not None:
        lines.append(_sim_line(f"D074 對照組 {LEGACY_SETTING.label}", report.legacy))
    lines.append(_sim_line(f"固定 {REFERENCE_FIXED_ANNUAL:g}%", report.fixed_reference))
    lines.append(_sim_line(f"事後看最好的固定價 {report.best_fixed_annual:g}%", report.best_fixed))
    lines.append(
        f"  重播：{report.replay.net_pct:.2f}%，利用率 {report.replay.utilization_pct:.1f}%，"
        f"成交 {report.replay.fills} 次（實際 {report.replay.real_fills} 次）"
    )
    if report.caveats:
        lines.append("")
        lines.append("要注意")
        lines.extend(f"  ⚠ {caveat}" for caveat in report.caveats)
    return "\n".join(lines)


def line_headline(report: WeeklyReport) -> str:
    """手機通知列只看得到第一行，所以結論要在這裡（D029）。"""
    failed = [check.label for check in report.checks if check.action_required]
    tail = "判準都過" if not failed else f"要看：{'、'.join(failed)}"
    return f"週報 {report.period_label}：實得 {report.actual.earned_pct:.2f}%，{tail}"


def line_fields(report: WeeklyReport) -> Dict[str, Any]:
    actual = report.actual
    nominal = f"{actual.nominal_pct:.2f}%" if actual.nominal_pct is not None else "—"
    fields: Dict[str, Any] = {
        "實得": f"帳本 {actual.earned_pct:.2f}%／部位 {actual.position_pct:.2f}%",
        "利用率": f"{actual.utilization_pct:.1f}%，名目 {nominal}",
    }
    for check in report.checks:
        fields[check.label] = check.summary
    if report.legacy is not None:
        fields[LEGACY_SETTING.label] = f"{report.legacy.net_pct:.2f}%"
    fields[f"固定 {REFERENCE_FIXED_ANNUAL:g}%"] = f"{report.fixed_reference.net_pct:.2f}%"
    fields["最好的固定價"] = f"{report.best_fixed_annual:g}% → {report.best_fixed.net_pct:.2f}%"
    if report.caveats:
        fields["注意"] = "；".join(report.caveats)
    return fields
