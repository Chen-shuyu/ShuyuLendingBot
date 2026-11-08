# -*- coding: utf-8 -*-
"""FRR 小額實測的狀態與判準（D076 第三節）。**只算，不碰網路也不碰 DB**；動手的是 `bot_engine`。

## 要回答的問題

一張 348 USD 的 FRR 單：①排隊要等多久、②借出去之後能借多久、③實得比天期 7 好多少。
公開資料答不出①②（D075 第五節），所以只能實測。

## 判準先寫死（D070 的教訓），所以是常數不是設定

| 情況 | 動作 |
|---|---|
| 掛出後 10 天還沒成交 | 撤單、回天期 7，結論「排不到」 |
| 連續兩筆都是「排隊 ≥ 3 天、持有 < 24 小時」 | 提前停 |
| 其餘情況 | 跑到完成 2 筆或滿 45 天，停下來判定 |

**停了就是停了**：`bot_kv` 記著停止的時間，重啟不會重新開始；要再測一次得刻意清掉那個鍵。
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from core import hold_time
from strategies.base import FRR_OFFER_TYPES, OFFER_TYPE_FRR_FIX, OFFER_TYPE_FRR_VAR

STATE_KEY = "frr_test_state"

QUEUE_LIMIT_DAYS = 10
LONG_QUEUE_DAYS = 3
SHORT_HOLD_HOURS = 24.0
CONSECUTIVE_SHORT_FILLS = 2
FILLS_TO_JUDGE = 2
DAYS_TO_JUDGE = 45


@dataclass(frozen=True)
class FrrTestConfig:
    enabled: bool = False
    offer_type: str = OFFER_TYPE_FRR_FIX
    period: int = 30
    # 相對 FRR 的偏移量（日利率）。
    offset: float = 0.0

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "FrrTestConfig":
        section = (config or {}).get("frr_test") or {}
        built = cls(
            enabled=bool(section.get("enabled", False)),
            offer_type=str(section.get("offer_type", OFFER_TYPE_FRR_FIX)),
            period=int(section.get("period", 30)),
            offset=float(section.get("offset", 0.0)),
        )
        if built.offer_type not in FRR_OFFER_TYPES:
            raise ValueError(f"frr_test.offer_type 只能是 {FRR_OFFER_TYPES}：{built.offer_type}")
        if built.offer_type == OFFER_TYPE_FRR_VAR and built.offset < 0:
            # 官方文件：FRRDELTAVAR 的偏移量只能是正的。
            raise ValueError("FRRDELTAVAR 的偏移量不能是負的")
        if not 2 <= built.period <= 120:
            raise ValueError(f"frr_test.period 要在 2～120 天：{built.period}")
        return built


@dataclass
class FrrTestState:
    started_at: datetime
    stopped_at: Optional[datetime] = None
    reason: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "started_at": self.started_at.isoformat(),
                "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
                "reason": self.reason,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> "FrrTestState":
        data = json.loads(raw)
        started = hold_time.parse_moment(data.get("started_at"))
        if started is None:
            raise ValueError(f"frr_test_state 沒有開始時間：{raw}")
        return cls(
            started_at=started,
            stopped_at=hold_time.parse_moment(data.get("stopped_at")),
            reason=data.get("reason"),
        )


@dataclass(frozen=True)
class Fill:
    """一次成交。拆單併成一筆；還借著的 `closed_at` 是 None。"""

    opened_at: datetime
    closed_at: Optional[datetime]
    queue_hours: float
    hold_hours: Optional[float]


def fills_since(
    positions: Sequence[Dict[str, Any]],
    period: int,
    started_at: datetime,
) -> List[Fill]:
    """實測開始之後、這個天期的成交，依時間排序。

    排隊時間從**錢回來的那一刻**算起（任何一筆部位還回來，或實測開始）：機器人的錢一回來就會重新掛單，
    所以這段就是「錢閒著在等」的時間，也是判定要算進去的代價。
    打開開關時錢可能還在天期 7 的部位裡（D077），那段不算 FRR 單在排隊。
    """
    kept = hold_time.screen_positions(list(positions)).kept
    returned = sorted(
        moment
        for moment in (hold_time.parse_moment(position.get("closed_at")) for position in kept)
        if moment is not None
    )
    rows = []
    for position in kept:
        if int(position.get("period") or 0) != period:
            continue
        opened = hold_time.parse_moment(position.get("opened_at")) or hold_time.parse_moment(
            position.get("first_seen_at")
        )
        if opened is None or opened < started_at:
            continue
        rows.append((opened, hold_time.parse_moment(position.get("closed_at"))))
    rows.sort(key=lambda row: row[0])

    groups: List[List[tuple]] = []
    for row in rows:
        if groups and (row[0] - groups[-1][0][0]).total_seconds() <= hold_time.DEFAULT_SPLIT_WINDOW_SECONDS:
            groups[-1].append(row)
        else:
            groups.append([row])

    fills: List[Fill] = []
    for group in groups:
        opened = group[0][0]
        closes = [row[1] for row in group]
        closed = None if any(moment is None for moment in closes) else max(closes)
        queue_from = max([started_at] + [moment for moment in returned if moment <= opened])
        fills.append(
            Fill(
                opened_at=opened,
                closed_at=closed,
                queue_hours=(opened - queue_from).total_seconds() / 3600,
                hold_hours=(closed - opened).total_seconds() / 3600 if closed else None,
            )
        )
    return fills


@dataclass(frozen=True)
class Stop:
    """實測該停了。`action_required`：只有「該判定了」要人看，其餘的結論已經有了。"""

    code: str
    summary: str
    action_required: bool = False


def decide_stop(
    started_at: datetime,
    now: datetime,
    fills: Sequence[Fill],
    offer_created_at: Optional[datetime],
) -> Optional[Stop]:
    """該不該停。`offer_created_at`：場上那張 FRR 單掛出的時間，沒有就是 None。"""
    if offer_created_at is not None:
        waited = now - offer_created_at
        filled_after = any(fill.opened_at >= offer_created_at for fill in fills)
        if waited >= timedelta(days=QUEUE_LIMIT_DAYS) and not filled_after:
            return Stop(
                "queue_timeout",
                f"掛出 {waited.total_seconds() / 86400:.1f} 天還沒成交，結論：排不到",
            )

    completed = [fill for fill in fills if fill.closed_at is not None]
    recent = completed[-CONSECUTIVE_SHORT_FILLS:]
    if len(recent) == CONSECUTIVE_SHORT_FILLS and all(
        fill.queue_hours >= LONG_QUEUE_DAYS * 24 and fill.hold_hours < SHORT_HOLD_HOURS
        for fill in recent
    ):
        return Stop(
            "short_holds",
            f"連續 {CONSECUTIVE_SHORT_FILLS} 筆都是排隊 ≥ {LONG_QUEUE_DAYS} 天、持有 < "
            f"{SHORT_HOLD_HOURS:.0f} 小時：利用率不到 25%，提前停",
        )

    if len(completed) >= FILLS_TO_JUDGE:
        return Stop("ready_to_judge", f"完成 {len(completed)} 筆，可以判定了", action_required=True)
    if now - started_at >= timedelta(days=DAYS_TO_JUDGE):
        return Stop("ready_to_judge", f"滿 {DAYS_TO_JUDGE} 天，可以判定了", action_required=True)
    return None
