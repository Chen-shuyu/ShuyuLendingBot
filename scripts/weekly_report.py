# -*- coding: utf-8 -*-
"""每週對帳：一條指令印出週報，定時器每天呼叫一次（D076）。

    python3 scripts/weekly_report.py                        # 最新一週，只印不寫
    python3 scripts/weekly_report.py --week 2026-10-25      # 指定哪一週（給週日的日期）
    python3 scripts/weekly_report.py --since 2026-10-14 --until 2026-10-23
    python3 scripts/weekly_report.py --period 30 --assumed-hold 48 --floor-annual 8  # 補算舊設定
    python3 scripts/weekly_report.py --push-line            # 定時器用：沒推過才算、算完推 LINE
    python3 scripts/weekly_report.py --saved 2026-10-25     # 印出當時推播的那份完整報告，不重算

⚠ 補算過去的週要自己帶 `--period --assumed-hold --floor-annual`：天期看得出來（看實際掛單），
P 與地板只有設定檔的現值。

**只有 `--push-line` 會寫 DB**（`bot_kv` 的紀錄與記號），其餘一律唯讀。算法與判準在
`core/weekly.py`，這裡只負責抓資料、推播。交易所客戶端用 `dry_run=True` 建立：
這支程式只碰公開端點，**結構上就下不了單**。

## `--push-line` 的觸發：每天跑，但一週只推一次

定時器每天 18:35 叫一次；這裡看「可以算的最新一週」推過了沒，推過就立刻結束、不打網路。
**不綁在週日才跑**：週日剛好在部署或斷網，隔天就會自己補上（D053 同一個道理）。
停機好幾週只補最新那一週，不會連發。

**先記再推**（D053）：推播失敗就不要隔天再算一次再推一次，LINE 額度每月 200 則。
**算不出來**（斷網、交易所回錯誤）不算推過，隔天再試；但只在第一次失敗時推一則，一週最多多花一則。

## 為什麼要慢慢抓

逐筆成交一週大約 35 萬筆、35 頁。公開端點跟機器人共用 IP，每頁停 5 秒
（2026-11-01 用這個速度抓了 425 頁，全程沒有被限流，機器人也沒有任何警告）。
"""

import argparse
import json
import sqlite3
import sys
import time
from datetime import date as Date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.bitfinex_client import BitfinexClient  # noqa: E402
from config import settings  # noqa: E402
from core import tape as tape_module  # noqa: E402
from core import weekly  # noqa: E402
from db.repository import Repository, resolve_db_path  # noqa: E402
from notify import line_messaging, messages  # noqa: E402
from utils import clock  # noqa: E402

CURRENCY = "USD"
SENT_KEY = "weekly_report_sent_for"
FAILED_KEY = "weekly_report_failed_for"
RECORD_PREFIX = "weekly_report_result:"
BACKUP_STATUS_FILENAME = "backup_status.json"

PAGE_PAUSE_SECONDS = 5.0
# 常態價要看前 6 小時的成交（`trade_window_hours`），所以從週初往前多抓 6 小時。
TAPE_LEAD_HOURS = 6

MESSAGE_LEVELS = {
    weekly.LEVEL_OK: messages.LEVEL_INFO,
    weekly.LEVEL_WARNING: messages.LEVEL_WARNING,
    weekly.LEVEL_CRITICAL: messages.LEVEL_CRITICAL,
}


class _Logger:
    """同 `sync_earnings.py`：這是工具，輸出不要混進機器人的日誌檔。"""

    def info(self, message):
        print(f"  · {message}")

    def warning(self, message):
        print(f"  ⚠ {message}", file=sys.stderr)

    def error(self, message):
        print(f"  ❌ {message}", file=sys.stderr)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_rows(db_path: Path) -> Dict[str, Any]:
    """唯讀讀出 DB 裡要用的資料。"""
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:

        def rows(sql: str, *params: Any) -> List[Dict[str, Any]]:
            return [dict(row) for row in connection.execute(sql, params)]

        return {
            "earnings": rows(
                "SELECT date, interest, principal_avg FROM earnings_daily WHERE currency = ?", CURRENCY
            ),
            "positions": rows("SELECT * FROM funding_positions WHERE currency = ?", CURRENCY),
            "offers": rows(
                "SELECT created_at, rate, duration, amount, status FROM loan_offers "
                "WHERE currency = ? AND status = 'submitted' ORDER BY created_at",
                CURRENCY,
            ),
            "frr": [
                (int(datetime.fromisoformat(row["captured_at"]).timestamp() * 1000), float(row["frr"]))
                for row in rows(
                    "SELECT captured_at, frr FROM market_snapshots WHERE frr IS NOT NULL AND frr > 0"
                )
            ],
        }
    finally:
        connection.close()


def read_kv(db_path: Path, key: str) -> Optional[str]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT value FROM bot_kv WHERE key = ?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return row[0] if row else None


def read_backup_last_ok(db_path: Path) -> Optional[str]:
    """備份腳本寫在 DB 旁邊的狀態檔（D076）。讀不到就回 None，判準會把它喊出來。"""
    try:
        with open(db_path.parent / BACKUP_STATUS_FILENAME, encoding="utf-8") as handle:
            return json.load(handle).get("last_ok_at")
    except (OSError, ValueError):
        return None


def lost_last_week(db_path: Path, first: Date) -> Optional[bool]:
    """上一週的紀錄有沒有輸給上一版設定。沒有紀錄回 None（報告會講出來）。"""
    raw = read_kv(db_path, f"{RECORD_PREFIX}{(first - timedelta(days=7)).isoformat()}")
    if not raw:
        return None
    try:
        return json.loads(raw).get("lost_to_previous")
    except ValueError:
        return None


def build_inputs(
    config: Dict[str, Any],
    client: Any,
    db_path: Path,
    first: Date,
    last: Date,
    now: datetime,
    overrides: Optional[Dict[str, Any]] = None,
    pause_seconds: float = PAGE_PAUSE_SECONDS,
) -> weekly.WeeklyInputs:
    """讀 DB、抓公開資料，組成 `core/weekly.py` 要的輸入。"""
    rows = load_rows(db_path)
    frr = tape_module.FrrSeries(rows["frr"])
    start_ms = weekly.to_ms(weekly.midnight(first))
    end_ms = min(weekly.to_ms(weekly.midnight(last) + timedelta(days=1)), weekly.to_ms(now))

    setting = weekly.default_setting(
        config, rows["offers"], rows["positions"], start_ms, end_ms, weekly.to_ms(now)
    )
    if overrides:
        period = overrides.get("period") or setting.offer_period
        hold = overrides.get("assumed_hold") or setting.assumed_hold_hours
        rate = (
            overrides["floor_annual"] / 36500 if overrides.get("floor_annual") else setting.minimum_rate
        )
        setting = weekly.make_setting(period, hold, rate)

    print(f"抓逐筆成交（{first} → {last}，每頁停 {pause_seconds:g} 秒）…", flush=True)
    trades = tape_module.collect_pages(
        lambda begin, stop, size: client.get_trades_page(CURRENCY, begin, stop, size),
        start_ms - TAPE_LEAD_HOURS * tape_module.HOUR_MS,
        end_ms,
        pause=lambda: time.sleep(pause_seconds),
    )
    tape = tape_module.build_tape(trades, frr.at)
    print(f"逐筆成交 {len(tape)} 筆。", flush=True)

    # 窗內每一小時都要往前看 `candle_limit` 根，而且可能缺根，所以多抓一個窗的量。
    strategy_section = config.get("strategy") or {}
    candle_limit = int(strategy_section.get("candle_limit", 240))
    hours = int((end_ms - start_ms) / tape_module.HOUR_MS) + 1
    candles = {}
    for period in weekly.periods_to_price(setting, first):
        time.sleep(pause_seconds)
        candles[period] = client.get_rate_candles(
            CURRENCY,
            period=period,
            timeframe=str(strategy_section.get("candle_timeframe", "1h")),
            limit=candle_limit + hours + 24,
            end_ms=end_ms,
        )

    caveats = []
    if not rows["frr"]:
        caveats.append("DB 沒有 FRR 快照，分不出 FRR 管道，判準 1 不可信")
    else:
        gap = frr.longest_gap_hours(start_ms, end_ms)
        if gap > 6:
            caveats.append(f"FRR 快照最久空窗 {gap:.0f} 小時（機器人停過），FRR 管道的判準用了舊值")
    if tape._mts and tape._mts[-1] < end_ms - 6 * tape_module.HOUR_MS:
        caveats.append("逐筆成交沒有涵蓋到窗尾，模擬會偏低")
    if rows["earnings"]:
        ledger_last = (last + timedelta(days=1)).isoformat()
        newest = max(row["date"] for row in rows["earnings"])
        if newest < ledger_last:
            caveats.append(f"帳本最新一列是 {newest}，{ledger_last} 那筆可能還沒同步")

    return weekly.WeeklyInputs(
        config=config,
        tape=tape,
        candles=candles,
        earning_rows=rows["earnings"],
        position_rows=rows["positions"],
        offer_rows=rows["offers"],
        frr_at=frr.at,
        first=first,
        last=last,
        now=now,
        setting=setting,
        backup_last_ok_at=read_backup_last_ok(db_path),
        lost_last_week=lost_last_week(db_path, first),
        caveats=caveats,
    )


def push_report(
    report: weekly.WeeklyReport,
    repository: Any,
    notifier: Any,
) -> bool:
    """存紀錄 → 記號 → 推播。**先記再推**（D053）。"""
    key = report.first.isoformat()
    repository.set_kv(f"{RECORD_PREFIX}{key}", json.dumps(report.to_record(), ensure_ascii=False))
    repository.set_kv(SENT_KEY, key)
    return notifier.send(
        messages.weekly_report(
            weekly.line_headline(report),
            weekly.line_fields(report),
            level=MESSAGE_LEVELS[report.level],
            action_required=report.action_required,
        )
    )


def notify_failure_once(
    repository: Any, notifier: Any, first: Date, last: Date, reason: str
) -> None:
    """算不出來要出聲，但一週只出聲一次（失敗時的額度也是額度）。"""
    key = first.isoformat()
    if repository.get_kv(FAILED_KEY) == key:
        return
    repository.set_kv(FAILED_KEY, key)
    label = f"{first.strftime('%m-%d')}～{last.strftime('%m-%d')}"
    notifier.send(messages.weekly_report_failed(label, reason))


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="每週對帳：實際 vs 模擬（D076）")
    parser.add_argument("--db", default=None, help="SQLite 檔位置（預設讀 config.yaml）")
    parser.add_argument("--week", default=None, help="哪一週：給週日的日期（YYYY-MM-DD），預設最新一週")
    parser.add_argument("--since", default=None, help="自訂窗的第一天（賺錢的日子，要跟 --until 一起給）")
    parser.add_argument("--until", default=None, help="自訂窗的最後一天（含當天）")
    parser.add_argument("--period", type=int, default=None, help="「現行設定」的天期（補算舊設定用）")
    parser.add_argument("--assumed-hold", type=float, default=None, help="「現行設定」的 P（小時）")
    parser.add_argument("--floor-annual", type=float, default=None, help="「現行設定」的地板（年化 %%）")
    parser.add_argument("--saved", default=None, help="印出存著的完整報告（給週日的日期），不重算")
    parser.add_argument(
        "--push-line",
        action="store_true",
        help="定時器用：算最新一週，沒推過才算，算完存紀錄並推 LINE",
    )
    return parser.parse_args(argv)


def print_saved(db_path: Path, first: str) -> int:
    """印出當時存下來的完整報告。重算要抓 5 分鐘的資料，而且過了那週結果可能不一樣。"""
    raw = read_kv(db_path, f"{RECORD_PREFIX}{first}")
    if not raw:
        print(f"沒有 {first} 那週的紀錄（只有 --push-line 推過的週才有）", file=sys.stderr)
        return 1
    print(json.loads(raw).get("text") or raw)
    return 0


def resolve_window(args: argparse.Namespace, now: datetime) -> Optional[tuple]:
    """回傳 `(第一天, 最後一天)`；參數不合理回 None。"""
    try:
        if args.since or args.until:
            if not (args.since and args.until):
                print("--since 與 --until 要一起給", file=sys.stderr)
                return None
            first = Date.fromisoformat(args.since)
            last = Date.fromisoformat(args.until)
            if last < first:
                print(f"--until {last} 早於 --since {first}", file=sys.stderr)
                return None
            return first, last
        first = Date.fromisoformat(args.week) if args.week else weekly.latest_completed_week(now)
    except ValueError as exc:
        print(f"看不懂的日期：{exc}（格式是 YYYY-MM-DD）", file=sys.stderr)
        return None
    if first.weekday() != 6:
        print(f"{first} 不是週日：週的定義是週日 00:00～週六 24:00", file=sys.stderr)
        return None
    return first, first + timedelta(days=6)


def main(argv: Optional[List[str]] = None, client: Any = None, now: Optional[datetime] = None) -> int:
    args = parse_args(argv)
    now = now or clock.now()
    window = resolve_window(args, now)
    if window is None:
        return 2
    first, last = window

    settings.load_secrets_from_disk(project_root())
    config = settings.load_config(str(settings.resolve_config_path(project_root()))) or {}
    db_path = resolve_db_path(args.db or (config.get("database") or {}).get("path"))
    if not db_path.exists():
        print(f"找不到資料庫：{db_path}", file=sys.stderr)
        return 1
    if args.saved:
        return print_saved(db_path, args.saved)

    repository = None
    notifier = None
    if args.push_line:
        if read_kv(db_path, SENT_KEY) == first.isoformat():
            print(f"{first} 那週已經推過了。")
            return 0
        repository = Repository(str(db_path))
        notifier = line_messaging.build_notifier(config, _Logger())

    try:
        # dry_run=True：這支程式只碰公開端點，結構上就下不了單（見模組說明）。
        client = client or BitfinexClient(config, _Logger(), dry_run=True)
        overrides = {
            "period": args.period,
            "assumed_hold": args.assumed_hold,
            "floor_annual": args.floor_annual,
        }
        inputs = build_inputs(config, client, db_path, first, last, now, overrides)
        report = weekly.build_report(inputs)
    except Exception as exc:  # noqa: BLE001 - 要出聲，而且不能讓定時器以為沒事
        print(f"週報算不出來：{type(exc).__name__}: {exc}", file=sys.stderr)
        if repository is not None:
            notify_failure_once(repository, notifier, first, last, f"{type(exc).__name__}: {exc}")
        return 1

    print(weekly.format_report(report))
    if repository is None:
        return 0
    if not push_report(report, repository, notifier):
        print("LINE 推播失敗（或沒有啟用）；紀錄已存，不會重推。", file=sys.stderr)
        return 1
    print("已推送 LINE。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
