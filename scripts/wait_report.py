# -*- coding: utf-8 -*-
"""等待時間校準報告：掛出去那一刻以為要等多久，實際上等了多久。

回答的是 DECISIONS.md **D045** 的問題，與 `scripts/hold_report.py`（D040）成對：

    實質年化 = r × P ÷ (W + P)
                   ↑        ↑
          hold_report  wait_report

`strategies/expected_value.py` 挑價位時，`W` 由 `estimate_wait()` 從 K 線估出來，
而估得準不準決定了它會偏向高價還是低價——**`W` 正是算式裡懲罰高利率的那一項**。
預估值從 D038 起就寫進 `offer_wait_forecasts`，實際成交時間一直躺在
`loan_offers` 與 `funding_positions` 裡，**兩者存了兩週從來沒有被對照過**。

**它不改任何參數、不做任何決策**。`estimate_wait()` 要怎麼改是 M2 的題目
——先改參數再建量測正是 D036 記下的錯誤。

用法：

    python3 scripts/wait_report.py                # 讀 config.yaml 指定的 DB
    python3 scripts/wait_report.py --currency USD
    python3 scripts/wait_report.py --since 2026-08-18   # 只看期望值策略上線之後
    BFX_DB_PATH=/path/to/lending.sqlite3 python3 scripts/wait_report.py

資料庫一律以**唯讀**開啟，理由同 `scripts/hold_report.py`：報告不該有副作用，
更不該在正式機上順手把缺掉的表建回去，把真正的問題蓋掉。
"""

import argparse
import unicodedata
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from core import wait_time  # noqa: E402

DEFAULT_DB_PATH = "data/lending.sqlite3"
DEFAULT_INTERVAL_SECONDS = 600


def project_root() -> Path:
    """專案根目錄（本檔在 `scripts/` 底下，往上一層）。"""
    return Path(__file__).resolve().parent.parent


def resolve_db_path(configured_path: Optional[str] = None) -> Path:
    """與 `db/repository.py`、`scripts/hold_report.py` 完全一致的路徑規則。

    三處必須對齊，否則報告會去別的地方找 DB 然後回報「沒有任何掛單」
    ——而機器人其實記得好好的（同 TASKS.md A4 踩過的坑）。
    """
    raw = os.getenv("BFX_DB_PATH") or configured_path or DEFAULT_DB_PATH
    path = Path(raw)
    return path if path.is_absolute() else project_root() / path


def load_data(
    db_path: Path, currency: str, since: Optional[str]
) -> tuple:
    """唯讀讀出掛單、部位與預估值三份資料。

    **部位不套用 `since` 過濾**：`since` 之前掛出、之後才成交的那一張單，
    需要看得到它等到的部位，否則會被誤判成「沒成交」——**過濾條件把樣本
    從成交改判成右設限，是這份報告最容易造出來的假數字。**
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        offer_sql = (
            "SELECT * FROM loan_offers WHERE currency = ? AND status = 'submitted' "
        )
        params: List[Any] = [currency]
        if since:
            offer_sql += "AND created_at >= ? "
            params.append(since)
        offer_sql += "ORDER BY created_at"
        offers = [dict(row) for row in connection.execute(offer_sql, params)]

        positions = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM funding_positions WHERE currency = ? "
                "ORDER BY COALESCE(opened_at, first_seen_at)",
                (currency,),
            )
        ]

        forecasts = {
            str(row["offer_id"]): dict(row)
            for row in connection.execute("SELECT * FROM offer_wait_forecasts")
        }
        return offers, positions, forecasts
    finally:
        connection.close()


def _display_width(text: str) -> int:
    """字串在等寬終端機裡佔幾格。

    中文是全形，`str.ljust()` 那類方法按**字元數**補空白，於是中文欄位一定
    對不齊——`f"{'統計量':<18}"` 補出來的是 15 個空格，實際只差 12 格。
    """
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def _pad(text: str, width: int, right: bool = False) -> str:
    """照顯示寬度補到 `width` 格。"""
    padding = " " * max(width - _display_width(text), 0)
    return padding + text if right else text + padding


def _hours(value: Optional[float]) -> str:
    """None 就寫「—」，不要印出 0.00 假裝有這個數字。"""
    return f"{value:.2f}h" if value is not None else "—"


STATISTICS = (
    ("mean", "平均（策略正在用）"),
    ("median", "中位數"),
    ("p75", "四分之三"),
)


def _statistic_table(summary: wait_time.WaitSummary) -> List[str]:
    """三個統計量誰估得準的對照表。

    **為什麼要有這張表**：`estimate_wait()` 一次算出平均／中位數／四分之三三個值，
    `offer_wait_forecasts` 三個都存了，但策略只拿 `mean` 去算期望值
    （`expected_value.py`：`effective = rate × P ÷ (mean_hours + P)`），
    而這份報告在 2026-08-29 之前也只印 `mean`——**握著三份證據只看了一份**。

    D045 本文與追記都把「W 估不準」當成一個要除掉的倍數在談（先是 3.9 倍、
    後來 5.4 倍，追記又發現它是駝峰所以任何單一倍數都不對）。
    **這張表是第三條路**：也許不是要除以一個數字，而是一開始就選錯了統計量。

    ⚠ **這裡只把三個數字並排，不做選擇。** 換統計量會改變策略挑出來的價位，
    那是 M2 回測工具的題目——先改參數再建量測正是 D036 記下的那個錯誤。
    """
    lines = ["  --- 換一個統計量會準多少（同一份預估，只是取不同的代表值）---"]
    lines.append(
        "    " + _pad("統計量", 20) + _pad("總量比", 10, right=True)
        + _pad("逐筆中位", 10, right=True) + _pad("最好", 9, right=True)
        + _pad("最差", 9, right=True)
    )
    for key, label in STATISTICS:
        overall = summary.overall_factor_for(key)
        if overall is None:
            lines.append("    " + _pad(label, 20) + _pad("（無樣本）", 10, right=True))
            continue
        median = summary.median_factor_for(key)
        span = summary.factor_range_for(key)
        lines.append(
            "    "
            + _pad(label, 20)
            + _pad(f"{overall:.2f}×", 10, right=True)
            + _pad(f"{median:.1f}×" if median is not None else "—", 10, right=True)
            + _pad(f"{span[0]:.1f}×" if span else "—", 9, right=True)
            + _pad(f"{span[1]:.1f}×" if span else "—", 9, right=True)
        )

    # 只在三者都算得出來時才下這句話——少一個就沒有「全數」可言。
    usable = summary.calibratable_for("mean")
    ranked = [
        (summary.overall_factor_for(key), key, label)
        for key, label in STATISTICS
        if summary.overall_factor_for(key) is not None
    ]
    if len(ranked) == len(STATISTICS) and usable:
        best_key, best_label = min(ranked, key=lambda item: abs(item[0] - 1))[1:]
        if best_key != "mean":
            wins = sum(
                1
                for s in usable
                if s.factor_for(best_key) is not None
                and abs(s.factor_for(best_key) - 1) < abs(s.factor_for("mean") - 1)
            )
            lines.append(
                f"    🔴 **{best_label}比策略正在用的平均更接近實際**，"
                f"{len(usable)} 段裡有 {wins} 段較準。"
            )
            lines.append(
                "    ⚠ **這不是「改成它就會賺比較多」**：三個統計量下的實質年化"
                "算式分母不同，數字不可直接比較，而且樣本仍全落在模型自己選出來的"
                "那條窄帶內。要不要換由 M2 回測回答。"
            )
    lines.append("")
    return lines


def format_report(summary: wait_time.WaitSummary, currency: str) -> str:
    """把摘要排成給人讀的報告。

    版面刻意讓四個誠實度來源（右設限、偵測延遲、配對是推的、預估值可能沒有）
    跟數字並排，而不是收進腳註——量測值旁邊沒有誤差來源，下一個讀到它的人
    就會把它當成精確值（D040 的教訓，D045 沿用）。
    """
    lines: List[str] = []
    lines.append(f"=== {currency} 等待時間校準報告 ===")
    lines.append("")

    if not summary.spells:
        lines.append("目前沒有任何可用的掛單紀錄。")
        return "\n".join(lines)

    lines.append(
        f"掛單期間 {summary.total} 段："
        f"已成交 {summary.filled} 段、沒等到成交 {summary.censored} 段"
        f"（右設限 {summary.censored_ratio * 100:.0f}%）"
    )
    if summary.merged_offers:
        lines.append(
            f"  （由 {summary.total + summary.merged_offers} 列掛單合併而成——"
            f"連續、同利率、中間沒成交過的重掛算同一段，理由見 core/wait_time.py）"
        )
    if summary.simultaneous:
        lines.append(
            f"  ⚠ 其中 {summary.simultaneous} 段是「同一輪掛出的另一張單」"
            f"（`spread_count > 1` 的時期），長度是零，**不算一段等待、不計入右設限**。"
        )
    lines.append("")

    lines.append("--- 逐筆 ---")
    for spell in summary.spells:
        lines.append("  " + wait_time.describe_spell(spell))
    lines.append("")

    lines.append("--- 已成交期間的實際等待（右設限的那些不列入）---")
    if summary.enough_for_quantile:
        lines.append(
            f"  平均 {_hours(summary.mean_hours)}／中位數 {_hours(summary.median_hours)}"
        )
    elif summary.filled:
        lines.append(f"  只有 {summary.filled} 段，直接列出：{summary.hours_listing()}")
    else:
        lines.append("  還沒有成交過的掛單期間。")
    if summary.detection_lag_hours:
        lines.append(
            f"  ⚠ 以上每一筆都被**高估**最多 {summary.detection_lag_hours * 60:.0f} 分鐘："
            f"成交時間是我們巡檢時偵測到的，不是交易所實際成交的時間。"
        )
    longest = summary.longest_censored_hours
    if longest is not None:
        lines.append(
            f"  ⚠ 另有 {summary.censored} 段沒等到成交，最長的一段掛了 "
            f"**至少 {longest:.2f} 小時**——**只看成交的那幾段，會把等待看得比實際短。**"
        )
    if summary.ongoing:
        lines.append(
            f"  ⚠ 其中 {summary.ongoing} 段**還在計時**（還沒有下一張單接手）——"
            f"它們的時數是下界且**會繼續長**，不是已經定案的觀測。"
        )
    lines.append("")

    lines.append("--- 對照 expected_value.py 的等待估計 ---")
    usable = summary.calibratable
    if not usable:
        lines.append("  還沒有「有預估值 ＋ 已成交」的掛單期間，校準不出來。")
        lines.append("  （預估值從 D038 才開始寫進 offer_wait_forecasts，更早的掛單沒有。）")
        return "\n".join(lines)

    factor = summary.overall_factor
    lines.append(
        f"  可校準 {len(usable)} 段（有預估值且已成交）："
        f"高估 {summary.overestimated} 段、低估 {summary.underestimated} 段"
    )
    lines.append(
        f"  **總預估 ÷ 總實際 = {factor:.1f} 倍**"
        f"（逐筆：{summary.factor_listing()}）"
    )
    median_factor = summary.median_factor
    if median_factor is not None and factor is not None:
        lines.append(
            f"  逐筆倍數的中位數是 {median_factor:.1f} 倍。"
            f"**與總量比差得越多，代表越不該用單一倍數轉述這件事。**"
        )
    lines.append("")
    lines.append(
        "  `W` 是算式 `r × P ÷ (W + P)` 裡懲罰高利率的那一項。"
        "`W` 被系統性放大，等於高利率被系統性懲罰過頭，選出的價位會偏低。"
    )
    span = summary.calibration_rate_span
    if span:
        lines.append(
            f"  🔴 **但校準樣本全部落在年化 {span} 這個帶內**"
            f"——那正是模型自己選出來的區間。**帶外沒有樣本，不能外推。**"
        )
    lines.append("")
    lines.extend(_statistic_table(summary))
    lines.append(
        "  **這是觀察，不是結論**：要不要改 `estimate_wait()`、改成什麼，"
        "由 M2 回測工具回答（DECISIONS.md D045）。"
    )
    lines.append(
        "  ⚠ 另有一個**方向相反**的偏誤：`P` 寫死 48 小時而實測完成率只有一半"
        "（D040），那一項是把高利率評得**過高**。兩者反向，淨效果不能用手算宣告。"
    )

    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="等待時間校準報告")
    parser.add_argument("--currency", default="USD", help="幣別（預設 USD）")
    parser.add_argument("--db", default=None, help="SQLite 檔位置（預設讀 config.yaml）")
    parser.add_argument(
        "--since",
        default=None,
        help="只看這個時間之後掛出的單（ISO 字串，例如 2026-08-18）",
    )
    args = parser.parse_args(argv)

    config: Dict[str, Any] = {}
    try:
        config_path = settings.resolve_config_path(project_root())
        config = settings.load_config(str(config_path)) or {}
    except Exception:
        # 報告不該因為設定檔讀不到就整支掛掉——DB 位置還有環境變數與預設值可用。
        config = {}

    configured = args.db or ((config.get("database") or {}).get("path"))
    db_path = resolve_db_path(configured)
    if not db_path.exists():
        print(f"找不到資料庫：{db_path}", file=sys.stderr)
        return 1

    engine_config = config.get("engine") or {}
    interval_seconds = int(
        engine_config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)
        or DEFAULT_INTERVAL_SECONDS
    )

    offers, positions, forecasts = load_data(db_path, args.currency, args.since)
    summary = wait_time.summarize(
        offers,
        positions,
        forecasts=forecasts,
        detection_lag_hours=interval_seconds / 3600,
    )
    print(format_report(summary, args.currency))
    return 0


if __name__ == "__main__":
    sys.exit(main())
