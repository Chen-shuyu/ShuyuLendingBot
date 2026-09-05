# -*- coding: utf-8 -*-
"""把交易所帳本裡的利息挑出來，彙總成每日收益（P2-2）。

## 為什麼這支模組值得存在

**這是整個專案唯一一條「交易所自己說的錢」。** 其他每一個績效數字都是推論：

| 數字 | 怎麼來的 |
|---|---|
| 成交時間 | 靠「利率相同 ＋ 開倉時間落在掛單存活區間」**配對推出來的**（`wait_time`） |
| 還款時間 | 靠**巡檢偵測**，每筆被高估最多 10 分鐘（`hold_time`） |
| 實得年化 | 上面兩者相乘 |
| 回測的實得年化 | 建立在上面那些推論之上，驗收標準也是對照它們 |

**那是一條沒有錨點的推論鏈，而帳本就是錨。**

2026-08-30 第一次把錨放下去，結果是：

| 來源 | 實得年化 | 說明 |
|---|---|---|
| `wait_report` | 7.99% | 自己標註偏樂觀（空掛期間不在分母） |
| 回測 `run_policy`（P=48） | 6.54% | 分母含空等，但成交時點是模擬的（偏快） |
| **交易所帳本** | **5.42%** | **0.75517665 USD／14.76 天／本金 344.31** |

**每一層推論都偏樂觀，而真金落在全部之下。**

## 🔴 帳本裡混著別的東西，而且有兩個陷阱

實測 27 列裡：利息 20 列、錢包轉帳 6 列、幣別兌換 1 列。

1. **「把金額加總」會錯**——轉帳與兌換都會被算成收益。
2. **「只取正數」也會錯**——同一筆轉帳出現**兩列、正負相反、掛在不同錢包上**
   （`Transfer of 184.3 USD ... on wallet funding` ＋ `... on wallet exchange`），
   只取正數會留下其中一半。

所以分類**一定要同時看 `description` 與 `wallet`**。

## 日期怎麼切

Bitfinex 每天約 **09:30 CST** 結一次放貸利息，所以按 CST 的日曆日分桶。
**時區不是細節**：用 UTC 切的話 09:30 CST（= 01:30 UTC）會落在同一天，
看起來沒差，但跨日的那幾筆會歸錯天，而日結摘要（P2-4）就是照這個切的。
時區一律走 `utils/clock.py`（D028）。
"""

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from utils import clock

# 放貸利息入帳的描述前綴。**實測值**，不是從文件抄的：
# `'Margin Funding Payment on wallet funding'`。
INTEREST_PREFIX = "Margin Funding Payment"

# 利息只認 funding 錢包。**這一條是防陷阱 2 的**：轉帳會在兩個錢包各留一列。
INTEREST_WALLET = "funding"

KIND_INTEREST = "interest"
KIND_TRANSFER = "transfer"
KIND_OTHER = "other"


def classify(entry: Dict[str, Any]) -> str:
    """一列帳本是哪一種。**看 `description` ＋ `wallet`，兩個都要看。**"""
    description = (entry.get("description") or "").strip()
    if description.startswith(INTEREST_PREFIX):
        # 描述對了但錢包不對 → 不是我們要的那一列（見模組說明的陷阱 2）。
        return KIND_INTEREST if entry.get("wallet") == INTEREST_WALLET else KIND_OTHER
    if description.startswith("Transfer"):
        return KIND_TRANSFER
    return KIND_OTHER


def interest_entries(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """只留放貸利息那些列，依時間由舊到新。"""
    picked = [entry for entry in entries if classify(entry) == KIND_INTEREST]
    return sorted(picked, key=lambda entry: entry.get("mts") or 0)


@dataclass(frozen=True)
class DailyEarning:
    """某一天（CST 日曆日）收到的放貸利息。"""

    date: str
    currency: str
    interest: float
    # 那一天最後一筆入帳後的錢包餘額。**當「本金」用是近似值**：
    # 它是「利息已經加進去之後」的餘額，而且錢還在場上掛單時也算在裡面。
    # 真正的平均本金要另外算，這裡不假裝它是。
    closing_balance: Optional[float]
    entry_count: int


def daily_earnings(
    entries: Iterable[Dict[str, Any]],
    currency: str = "USD",
    timezone_name: Optional[str] = None,
) -> List[DailyEarning]:
    """把利息列彙總成每日一筆，依日期由舊到新。

    同一天有多筆就相加——**這件事真的會發生**（補入帳），而
    `Repository.upsert_daily_earning()` 對同一天是**累加**的，
    所以這裡必須先合併好再寫，否則重跑一次就會把當天的利息加成兩倍。
    **那是這一支最容易造成假數字的地方**，測試有釘住。
    """
    tz = clock.get_timezone(timezone_name)
    buckets: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    for entry in interest_entries(entries):
        mts = entry.get("mts")
        if mts is None:
            continue
        from datetime import datetime

        date = datetime.fromtimestamp(mts / 1000, tz).strftime("%Y-%m-%d")
        buckets.setdefault(date, []).append(entry)

    result: List[DailyEarning] = []
    for date, rows in buckets.items():
        last = max(rows, key=lambda row: row.get("mts") or 0)
        result.append(
            DailyEarning(
                date=date,
                currency=currency,
                interest=sum(float(row["amount"]) for row in rows),
                closing_balance=last.get("balance"),
                entry_count=len(rows),
            )
        )
    return result


# Bitfinex 對放貸利息抽的成數。**這個常數只用在對帳，不參與任何定價決策**
# ——它是利息上的一個常數乘數，所以不改變 `r × P ÷ (W + P)` 的極大點。
#
# 值是**量出來的，不是查來的**：2026-09-05 把 `funding_positions` 逐日攤成
# 推算毛利息，與帳本淨利息相比，合計比值 **81.2%**（D060）。
# 15% 的抽成對應 85%，兩者的差距落在「利息是結算日入帳、不是權責日」造成的
# 邊界效應裡。**所以它是一條參考線，不是一個該被拿去精算的係數。**
FUNDING_FEE_PCT = 15.0


def expected_gross_interest(
    positions: Iterable[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> float:
    """從已借出部位推算「照合約應該產生多少毛利息」（D065）。

    **它是對帳用的參考線，不是收益數字。** 帳本才是錢（D051），
    這一支的用途是回答「帳本少的那些，是抽成，還是真的少了一天」。

    仍在生息中的部位以**現在**為止計算——那是下界，
    而下界拿來跟「已經入帳的利息」比，方向是保守的。

    ⚠ **它有三個已知的偏差來源**，全部指向同一個方向（推算值偏高）：
    複利沒有算進去、`closed_at` 是巡檢偵測到的時間（每筆高估最多一個巡檢間隔）、
    以及**利息是結算日入帳**，所以日對日一定對不齊。**只有多日合計有意義。**
    """
    now = now or clock.now()
    total = 0.0
    for position in positions:
        opened = parse_moment(position.get("opened_at")) or parse_moment(
            position.get("first_seen_at")
        )
        if opened is None:
            continue
        closed = parse_moment(position.get("closed_at")) or now
        hours = (closed - opened).total_seconds() / 3600
        if hours <= 0:
            continue
        amount = float(position.get("amount") or 0.0)
        rate = float(position.get("rate") or 0.0)
        total += amount * rate * hours / 24
    return total


def parse_moment(moment: Optional[str]) -> Optional[datetime]:
    """ISO 8601 字串轉 `datetime`；轉不動回 `None`。

    **與 `core/hold_time.py` 那一支同樣的約定**：轉不動就缺席，不要猜。
    """
    if not moment:
        return None
    try:
        return datetime.fromisoformat(moment)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class LedgerSummary:
    """一次帳本同步看到了什麼。**分類的每一種都要報出數量**，
    因為「混進別的東西」正是這支模組要擋的事——擋掉了幾列要看得見。"""

    total_rows: int
    interest_rows: int
    transfer_rows: int
    other_rows: int
    days: List[DailyEarning]

    @property
    def total_interest(self) -> float:
        return sum(day.interest for day in self.days)

    def realized_annual_pct(self, principal: float, days_elapsed: float):
        """`利息 ÷ 本金 × 365 ÷ 天數`。**這是唯一不靠推論的實得年化。**

        ⚠ **本金要由呼叫端給**，這裡不自己猜：帳本只看得到餘額，
        而餘額包含已經賺到的利息、也包含還掛在場上沒借出去的錢。
        猜一個本金出來就等於把這個數字也變成推論，那就失去它存在的意義了。
        """
        if principal <= 0 or days_elapsed <= 0:
            return None
        return self.total_interest / principal * 365 / days_elapsed * 100


def summarize(
    entries: Iterable[Dict[str, Any]],
    currency: str = "USD",
    timezone_name: Optional[str] = None,
) -> LedgerSummary:
    """分類 ＋ 彙總，一次講完這批帳本裡有什麼。"""
    rows = list(entries)
    kinds = [classify(entry) for entry in rows]
    return LedgerSummary(
        total_rows=len(rows),
        interest_rows=kinds.count(KIND_INTEREST),
        transfer_rows=kinds.count(KIND_TRANSFER),
        other_rows=kinds.count(KIND_OTHER),
        days=daily_earnings(rows, currency=currency, timezone_name=timezone_name),
    )
