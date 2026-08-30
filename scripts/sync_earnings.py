# -*- coding: utf-8 -*-
"""把交易所帳本的放貸利息同步進 `earnings_daily`，並印出對照（P2-2）。

**這支與另外三份報告不同：它會寫 DB。** `hold_report`／`wait_report`／
`backtest_report` 一律唯讀，而這一支的工作就是把資料寫進去，所以：

- **可以重跑**：用 `Repository.set_daily_earning()`（覆蓋，不是累加）。
  帳本每次都給出那一天的完整金額，累加的話重跑一次就把利息變兩倍。
- **`--dry-run` 只看不寫**，預設就是它——會改資料的東西不該預設會改資料。

用法：

    python3 scripts/sync_earnings.py                  # 只看，不寫
    python3 scripts/sync_earnings.py --write          # 真的寫進 earnings_daily
    python3 scripts/sync_earnings.py --principal 344.31 --since 2026-08-15
    python3 scripts/sync_earnings.py --write --currency USD

## 為什麼這件事重要

**這是整個專案唯一一條「交易所自己說的錢」。** 其他績效數字全是推論
（成交時間靠配對推、還款時間靠巡檢偵測、實得年化是兩者相乘），
而那條推論鏈一直沒有錨。詳見 `core/earnings.py` 的模組說明與 DECISIONS 的 D051。
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.bitfinex_client import BitfinexClient  # noqa: E402
from config import settings  # noqa: E402
from core import earnings  # noqa: E402
from db.repository import Repository, resolve_db_path  # noqa: E402
from utils import clock  # noqa: E402


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


class _Logger:
    """`BitfinexClient` 只需要 `info`／`warning`／`error` 三個方法。

    **不接專案的 `BotLogger`**：那支會寫進機器人的日誌檔，而這是一支
    人手動跑的工具——把它的輸出混進機器人的日誌，事後查「那天發生什麼」時
    會多出一批不是機器人做的事。
    """

    def info(self, message):
        print(f"  · {message}")

    def warning(self, message):
        print(f"  ⚠ {message}", file=sys.stderr)

    def error(self, message):
        print(f"  ❌ {message}", file=sys.stderr)


def format_summary(
    summary: earnings.LedgerSummary,
    principal: Optional[float],
    since: Optional[str],
) -> str:
    lines = ["=== 帳本同步：交易所自己說的錢 ===", ""]
    lines.append(
        f"帳本共 {summary.total_rows} 列 → "
        f"**利息 {summary.interest_rows} 列**、"
        f"錢包轉帳 {summary.transfer_rows} 列、其他 {summary.other_rows} 列"
    )
    lines.append(
        "  📌 **轉帳與其他被擋掉了，而這正是重點**：同一筆轉帳會出現兩列、"
        "正負相反、掛在不同錢包上——**「加總」與「只取正數」兩種做法都會算錯**。"
    )
    if not summary.days:
        lines.append("")
        lines.append("  帳本裡沒有放貸利息——**這一項無法驗收**，不是通過。")
        return "\n".join(lines)

    lines.append("")
    lines.append("--- 每日利息 ---")
    for day in summary.days:
        balance = (
            f"  餘額 {day.closing_balance:.8f}" if day.closing_balance is not None else ""
        )
        multi = f"（{day.entry_count} 筆）" if day.entry_count > 1 else ""
        lines.append(f"  {day.date}  +{day.interest:.8f} USD{multi}{balance}")

    lines.append("")
    lines.append(f"  **合計 {summary.total_interest:.8f} USD**（{len(summary.days)} 天）")

    if principal and summary.days:
        first = datetime.strptime(summary.days[0].date, "%Y-%m-%d")
        last = datetime.strptime(summary.days[-1].date, "%Y-%m-%d")
        # 🔴 **分母的起點是「期間的開始」，不是「第一筆入帳」。**
        # 用第一筆入帳當起點，會把「錢已經進來但還沒借出去」的那段時間
        # 從分母裡刪掉——而那正是這個專案一路踩過來的同一個坑
        # （`wait_report` 的 7.99% 就是這樣偏樂觀的）。
        # 給了 `--since` 就從那天算起：使用者說期間從哪裡開始，就從哪裡開始。
        start = datetime.strptime(since, "%Y-%m-%d") if since else first
        elapsed = max((last - start).days, 1)
        annual = summary.realized_annual_pct(principal, elapsed)
        if annual is not None:
            lines.append("")
            lines.append(
                f"  **實得年化 {annual:.2f}%**"
                f"（本金 {principal:.2f} USD、{start.strftime('%m-%d')} → "
                f"{last.strftime('%m-%d')} 共 {elapsed} 天）"
            )
            if not since:
                lines.append(
                    "  🔴 **沒給 `--since`，所以分母從第一筆入帳算起**"
                    "——那會把「錢進來了但還沒借出去」的時間從分母裡刪掉，"
                    "**數字偏樂觀**。要誠實的數字請給 `--since <期間起點>`。"
                )
            lines.append(
                "  ⚠ **本金是呼叫端給的，不是算出來的**：帳本只看得到餘額，"
                "而餘額含已賺到的利息、也含還掛在場上沒借出去的錢。"
                "猜一個本金出來，這個數字就又變成推論了。"
            )

        # 期間內完全沒有利息入帳的日子。**空白的日子一樣在分母裡**，
        # 而且它們常常是最重要的訊號（沒借出去、或錢根本不在 funding 錢包）。
        有入帳 = {day.date for day in summary.days}
        空白 = elapsed + 1 - len(有入帳)
        if 空白 > 0:
            lines.append(
                f"  ⚠ **期間內有 {空白} 天完全沒有利息入帳**"
                "——可能是沒借出去，也可能是錢不在 funding 錢包。"
                "**它們在分母裡，這是對的**，但值得看一眼是哪幾天。"
            )
    if since:
        lines.append(f"  （只算 {since} 之後）")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="帳本利息同步（P2-2）")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--db", default=None, help="SQLite 檔位置（預設讀 config.yaml）")
    parser.add_argument("--limit", type=int, default=500, help="一次抓幾列帳本")
    parser.add_argument(
        "--since", default=None, help="只算這個日期之後的入帳（YYYY-MM-DD）"
    )
    parser.add_argument(
        "--principal", type=float, default=None, help="算實得年化用的本金（USD）"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="真的寫進 earnings_daily（不給就只看不寫）",
    )
    args = parser.parse_args(argv)

    config: Dict[str, Any] = {}
    try:
        settings.load_secrets_from_disk(project_root())
        config = settings.load_config(str(settings.resolve_config_path(project_root()))) or {}
    except Exception as exc:
        print(f"讀不到設定：{exc}", file=sys.stderr)
        return 1

    client = BitfinexClient(config, _Logger(), dry_run=False)
    if client.exchange is None:
        print("交易所客戶端沒有初始化——請確認 API 金鑰。", file=sys.stderr)
        return 1

    start_ms = None
    if args.since:
        try:
            since = datetime.strptime(args.since, "%Y-%m-%d").replace(
                tzinfo=clock.get_timezone()
            )
        except ValueError:
            print(f"看不懂的日期：{args.since}（格式是 YYYY-MM-DD）", file=sys.stderr)
            return 1
        start_ms = int(since.timestamp() * 1000)

    entries = client.get_funding_ledger(
        args.currency, limit=args.limit, start_ms=start_ms
    )
    summary = earnings.summarize(entries, currency=args.currency)
    print(format_summary(summary, args.principal, args.since))

    if not args.write:
        print("")
        print("  （只看不寫。要真的寫進 `earnings_daily` 請加 `--write`。）")
        return 0

    configured = args.db or ((config.get("database") or {}).get("path"))
    db_path = resolve_db_path(configured)
    if not db_path.exists():
        print(f"找不到資料庫：{db_path}", file=sys.stderr)
        return 1

    repository = Repository(str(db_path))
    try:
        for day in summary.days:
            repository.set_daily_earning(
                date=day.date,
                currency=day.currency,
                interest=day.interest,
                principal_avg=args.principal,
            )
    finally:
        close = getattr(repository, "close", None)
        if callable(close):
            close()

    print("")
    print(f"  ✅ 已寫入 `earnings_daily` {len(summary.days)} 天（覆蓋，可重跑）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
