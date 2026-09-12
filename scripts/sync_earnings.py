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
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.bitfinex_client import BitfinexClient  # noqa: E402
from config import settings  # noqa: E402
from core import earnings  # noqa: E402
from core import hold_time  # noqa: E402
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


def load_positions(db_path: Path, currency: str) -> List[Dict[str, Any]]:
    """唯讀讀出部位，給毛／淨對帳用（D065）。**篩掉 D057 的幽靈樣本。**"""
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM funding_positions WHERE currency = ?", (currency,)
            )
        ]
    finally:
        connection.close()
    return hold_time.screen_positions(rows).kept


def load_deployed_capital(
    db_path: Path, currency: str, since: Optional[str]
) -> Optional[Dict[str, Any]]:
    """唯讀讀出「已部署資金」當實得年化的分母（D065 落地、D069 接上）。

    🔴 **這一支存在的理由是一個錯了一週的數字。** D065 讓機器人每輪把觀測到的
    已部署資金寫進當天那一列，而 STATUS 因此寫下「本金不必再手打了」
    ——**但這支報告從來沒讀回來過**。`format_summary()` 只在 `principal` 有值時
    才印實得年化，於是照維運指令跑（不給 `--principal`）**什麼都不會印**，
    人就自己手算，然後用了「有入帳的天數」當分母，算出 7.75%
    （誠實的數字是 6.83%）。詳見 D069 第一節。

    👉 **教訓是「少印一行」比「印錯一行」更危險**：印錯的會被看到，
    少印的會被人用腦內算式補上，而腦內算式不會留下它用了什麼分母。

    **取平均而不是取最新一列**：分母該是「這段期間平均部署了多少錢」。
    只有機器人跑過的日子有值（舊日子是 NULL），所以回傳時一併帶上
    `days` 讓呼叫端能說清楚這個平均是幾天算出來的——**不能假裝它涵蓋全期間**。
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        sql = (
            "SELECT date, principal_avg FROM earnings_daily "
            "WHERE currency = ? AND principal_avg IS NOT NULL"
        )
        params: List[Any] = [currency]
        if since:
            sql += " AND date >= ?"
            params.append(since)
        rows = [dict(row) for row in connection.execute(sql + " ORDER BY date", params)]
    except sqlite3.Error:
        # **失敗一律吞掉**：報表不可以把「唯一那條會寫帳本的路」弄掉（D052 的守則）。
        return None
    finally:
        connection.close()

    values = [float(row["principal_avg"]) for row in rows if row["principal_avg"]]
    if not values:
        return None
    return {
        "value": sum(values) / len(values),
        "days": len(values),
        "first": rows[0]["date"],
        "last": rows[-1]["date"],
    }


def format_utilization(
    summary: earnings.LedgerSummary,
    positions: List[Dict[str, Any]],
    since: Optional[str],
    capital: Optional[Dict[str, Any]],
) -> List[str]:
    """資金利用率，並排「利用率 × 名目 × 0.85」與帳本實得（D069）。

    🔴 **為什麼這一段值得存在**：帳本告訴你賺了多少，**但不告訴你為什麼**。
    而 2026-09-12 量到利用率乘上名目利率之後，三週都能把帳本解釋到 0.2pp 以內
    ——**名目價格幾乎沒動，變的全是利用率**。

    這一段就是把那個分解印出來，讓「這週比較差」當場分得出是
    **借不出去**（利用率掉）還是**賣太便宜**（名目掉）。在它之前得手算。
    """
    if not positions or not summary.days or not capital:
        return []
    last = datetime.strptime(summary.days[-1].date, "%Y-%m-%d").replace(
        tzinfo=clock.get_timezone()
    )
    start = (
        datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=clock.get_timezone())
        if since
        else datetime.strptime(summary.days[0].date, "%Y-%m-%d").replace(
            tzinfo=clock.get_timezone()
        )
    )
    # 含頭含尾：最後一天整天都算（同 `format_summary()` 的曆日數）。
    end = last + timedelta(days=1)
    got = earnings.capital_utilization(positions, capital["value"], start, end)
    if not got:
        return []

    util = got["utilization_pct"]
    nominal = got["nominal_annual_pct"]
    expected = util / 100 * nominal * (100 - earnings.FUNDING_FEE_PCT) / 100
    days = got["window_hours"] / 24
    actual = summary.realized_annual_pct(capital["value"], max(round(days), 1))

    lines = ["", "--- 為什麼是這個數字：利用率 × 名目 ---"]
    lines.append(
        f"  資金利用率 **{util:.1f}%**"
        f"（{days:.0f} 天裡有 {days * util / 100:.1f} 天的錢在借出去）"
        f" ／ 金額加權名目年化 **{nominal:.2f}%**"
    )
    lines.append(
        f"  → 利用率 × 名目 × {(100 - earnings.FUNDING_FEE_PCT) / 100:.2f} = "
        f"**{expected:.2f}%**"
        + (f"，帳本實得 **{actual:.2f}%**" if actual is not None else "")
    )
    if actual is not None:
        gap = actual - expected
        if abs(gap) <= 0.5:
            lines.append(
                "  ✅ 兩邊對得上——**所以這個期間的績效是利用率與名目共同決定的**，"
                "沒有第三個東西在吃錢。"
            )
        else:
            lines.append(
                f"  🔴 **差 {gap:+.2f} 個百分點。** 對不上就代表有第三個因素"
                "——先看毛／淨對帳那一段是不是也偏了（缺列會同時讓兩邊都偏）。"
            )
    lines.append(
        "  📌 **利用率一定要用金額加權**：拆單的日子（三張部位併存）"
        "把時數直接加總會算出超過 100% 的利用率。分子是「USD × 小時」。"
    )
    lines.append(
        "  ⚠ **名目是「借出去的那些錢的平均利率」**，不是「掛單價」"
        "——沒成交的掛單不在裡面，那部分的代價算在利用率上。"
    )
    return lines


def format_reconciliation(
    summary: earnings.LedgerSummary,
    positions: List[Dict[str, Any]],
    since: Optional[str],
) -> List[str]:
    """帳本淨利息 vs 從部位推算的毛利息，並排（D065）。

    🔴 **為什麼要有這一段**：帳本是唯一的錨（D051），但**沒有任何東西在看它**。
    2026-09-05 靠人眼發現 `earnings_daily` 在 08-16／08-20／08-21／08-31 缺列
    ——而缺列與「那天真的沒賺」長得一模一樣。

    這一段給的是**一條參考線**：抽成 15% 對應淨毛比 85%。
    偏離太多就代表有一天沒入帳、或有一筆部位沒被記到。
    **它不會自己判斷是哪一種**——判斷需要的資訊不在這兩個數字裡。
    """
    if not positions or not summary.days:
        return []
    # 🔴 **兩半必須涵蓋同一段時間。** 帳本那半已經被 `--since` 篩過了，
    # 所以推算那半也要裁到同一個窗——不裁的後果見 `expected_gross_interest` 的說明。
    start = None
    if since:
        start = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=clock.get_timezone())
    gross = earnings.expected_gross_interest(positions, start=start)
    if gross <= 0:
        return []
    ratio = summary.total_interest / gross * 100
    expected = 100 - earnings.FUNDING_FEE_PCT
    lines = ["", "--- 毛／淨對帳（帳本是錢，推算是參考線）---"]
    lines.append(
        f"  推算毛利息 {gross:.4f} USD ／ 帳本淨利息 {summary.total_interest:.4f} USD"
        f" → **淨毛比 {ratio:.1f}%**（抽成 {earnings.FUNDING_FEE_PCT:.0f}% 對應 {expected:.0f}%）"
    )
    gap = ratio - expected
    if abs(gap) <= 8:
        lines.append("  ✅ 落在參考線附近——**沒有明顯缺列**。")
    elif gap < 0:
        lines.append(
            f"  🔴 **比參考線低 {abs(gap):.1f} 個百分點。** 兩種可能而它們的意思完全相反："
            "有幾天的利息沒有入帳（帳本缺列），或推算把某些部位算多了。"
        )
    else:
        lines.append(
            f"  ⚠ **比參考線高 {gap:.1f} 個百分點。** 多半是部位沒被記全"
            "（推算的分母偏小），不是賺得比合約多。"
        )
    lines.append(
        "  ⚠ **只有多日合計有意義**：利息是**結算日**入帳不是權責日，日對日必定對不齊。"
        "推算值本身也偏高（沒算複利、`closed_at` 被巡檢延遲高估）。"
    )
    if not since:
        lines.append(
            "  ⚠ 沒給 `--since`，兩邊涵蓋的期間不一定相同——**這個比值會失真**。"
        )
    return lines


def format_summary(
    summary: earnings.LedgerSummary,
    principal: Optional[float],
    since: Optional[str],
    capital: Optional[Dict[str, Any]] = None,
) -> str:
    """把帳本摘要排版成人看的報告。

    `principal` 是 `--principal` 給的（呼叫端說了算）；`capital` 是從
    `earnings_daily.principal_avg` 讀回來的觀測值（D065／D069）。
    **給了 `--principal` 就用它**——使用者明確說的話勝過我們自己觀測到的。
    """
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

    first = datetime.strptime(summary.days[0].date, "%Y-%m-%d")
    last = datetime.strptime(summary.days[-1].date, "%Y-%m-%d")
    # 🔴 **分母的起點是「期間的開始」，不是「第一筆入帳」。**
    # 用第一筆入帳當起點，會把「錢已經進來但還沒借出去」的那段時間
    # 從分母裡刪掉——而那正是這個專案一路踩過來的同一個坑
    # （`wait_report` 的 7.99% 就是這樣偏樂觀的）。
    # 給了 `--since` 就從那天算起：使用者說期間從哪裡開始，就從哪裡開始。
    start = datetime.strptime(since, "%Y-%m-%d") if since else first
    # 🔴 **`+ 1`：曆日數是「含頭含尾」，不是兩個日期相減。**
    # 2026-09-12 之前這裡是 `(last - start).days`，而同一個函式裡的空白日判斷
    # 用的卻是 `elapsed + 1`——**同一份報告裡兩種天數**。
    # 09-05 → 09-12 其實是 8 天，算成 7 天會讓年化高估 14%（6.87% 印成 7.86%）。
    # D069 那個錯數字是「用入帳列數當分母」，這一條是它的鄰居：**差一天也是差**。
    elapsed = max((last - start).days + 1, 1)

    # 🔴 **這一段以前躲在 `if principal:` 裡面，那是 D069 第一節那個錯數字的根因。**
    # 分母是**曆日**，而「合計 N 天」印的是入帳列數——兩者在有空白日時不一樣。
    # 空白日常常是最重要的訊號（沒借出去、或錢不在 funding 錢包），
    # **所以它不該依賴呼叫端有沒有給本金**。
    有入帳 = {day.date for day in summary.days}
    # `elapsed` 現在自己就是含頭含尾的曆日數了，所以這裡不再 `+ 1`。
    空白 = elapsed - len(有入帳)
    lines.append(
        f"  📌 **分母是曆日：{start.strftime('%m-%d')} → {last.strftime('%m-%d')} 共 "
        f"{elapsed} 天**，而上面那個「{len(summary.days)} 天」是**入帳列數**。"
    )
    if 空白 > 0:
        lines.append(
            f"  ⚠ **期間內有 {空白} 天完全沒有利息入帳**"
            "——可能是沒借出去，也可能是錢不在 funding 錢包。"
            "**它們在分母裡，這是對的**，但值得看一眼是哪幾天。"
        )
        lines.append(
            "  🔴 **不要拿「入帳列數」當分母**：利息是按每筆單子的 24 小時結算點"
            "入帳，不是按日曆日，所以空白日與「那天真的沒賺」長得一樣。"
            "拿列數當分母會系統性高估（D069 那次高估了 0.9 個百分點）。"
        )

    # 本金：`--principal` 勝過觀測值（使用者明確說的話算數），
    # 但**兩者都沒有時要講出來為什麼印不出年化**——少印一行比印錯一行更危險（D069）。
    分母 = principal if principal else (capital["value"] if capital else None)
    if 分母:
        annual = summary.realized_annual_pct(分母, elapsed)
        if annual is not None:
            lines.append("")
            lines.append(
                f"  **實得年化 {annual:.2f}%**"
                f"（本金 {分母:.2f} USD、{start.strftime('%m-%d')} → "
                f"{last.strftime('%m-%d')} 共 {elapsed} 天）"
            )
            if not since:
                lines.append(
                    "  🔴 **沒給 `--since`，所以分母從第一筆入帳算起**"
                    "——那會把「錢進來了但還沒借出去」的時間從分母裡刪掉，"
                    "**數字偏樂觀**。要誠實的數字請給 `--since <期間起點>`。"
                )
            if principal:
                lines.append(
                    "  ⚠ **本金是呼叫端給的，不是算出來的**：帳本只看得到餘額，"
                    "而餘額含已賺到的利息、也含還掛在場上沒借出去的錢。"
                    "猜一個本金出來，這個數字就又變成推論了。"
                )
            else:
                lines.append(
                    f"  ✅ **本金是機器人自己觀測的已部署資金**（D065）："
                    f"{capital['days']} 天的平均（{capital['first']} → {capital['last']}），"
                    "不是手打的。"
                )
                if capital["days"] < elapsed:
                    lines.append(
                        f"  ⚠ **只有 {capital['days']} 天有觀測值，期間卻有 {elapsed} 天**"
                        "——D065 之前的日子是 NULL，那些天的部署金額沒有被平均進去。"
                    )
    else:
        lines.append("")
        lines.append(
            "  🔴 **算不出實得年化**：`earnings_daily.principal_avg` 一列都沒有"
            "（D065 之前的資料），而你也沒給 `--principal`。"
            "**不要自己拿合計去除入帳列數**——那正是 D069 第一節那個錯數字的來源。"
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

    configured = args.db or ((config.get("database") or {}).get("path"))
    db_path = resolve_db_path(configured)

    # 🔴 **本金要在排版之前讀出來。** 以前 `db_path` 是在 `format_summary()`
    # 之後才算的，於是報告根本拿不到 D065 落地的觀測值——而那就是 D069 第一節
    # 那個錯了一週的數字的機械原因。**吞掉失敗**：讀不到本金只是少印一行年化，
    # 不可以讓報表整支掛掉（D052 的守則，同下面的對帳）。
    capital = None
    if db_path.exists():
        try:
            capital = load_deployed_capital(db_path, args.currency, args.since)
        except Exception as exc:  # noqa: BLE001 - 見上
            print(f"（讀不到已部署資金，實得年化改用 --principal：{exc}）")

    print(format_summary(summary, args.principal, args.since, capital))

    # 🔴 **對帳在 `--write` 的分岔之前**：它是唯讀的，而**只看不寫的那條路
    # 才是最需要它的那條**——「先看一眼對不對」正是不寫的時候要做的事。
    # 失敗一律吞掉：**報表不可以把「唯一那條會寫帳本的路」弄掉**（D052 的守則）。
    if db_path.exists():
        try:
            positions = load_positions(db_path, args.currency)
            utilization = format_utilization(
                summary, positions, args.since, capital
            )
            if utilization:
                print("\n".join(utilization))
            reconciliation = format_reconciliation(summary, positions, args.since)
            if reconciliation:
                print("\n".join(reconciliation))
        except Exception as exc:  # noqa: BLE001 - 見上
            print(f"\n（毛／淨對帳算不出來，略過：{exc}）")

    if not args.write:
        print("")
        print("  （只看不寫。要真的寫進 `earnings_daily` 請加 `--write`。）")
        return 0

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
