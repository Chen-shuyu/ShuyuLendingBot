# -*- coding: utf-8 -*-
"""實際持有時間報告：借出去的錢，到底待了多久才被還回來。

回答的是 TASKS.md D1 那一半「現在就能做」的問題。`strategies/expected_value.py`
挑價位時假設每一筆都借滿天期（`hold_hours = offer_period * 24`），但
`funding_positions` 裡的 `opened_at` / `closed_at` 早就記著實際值，只是從來沒有
人算過。這支腳本把它算出來並印成人看得懂的樣子。

**它不改任何參數、不做任何決策**。48 這個數字要換成什麼，是 M2 回測工具的題目
——先改參數再建量測，正是 D036 記下的那個錯誤。

用法：

    python3 scripts/hold_report.py                # 讀 config.yaml 指定的 DB
    python3 scripts/hold_report.py --currency USD
    BFX_DB_PATH=/path/to/lending.sqlite3 python3 scripts/hold_report.py

資料庫一律以**唯讀**開啟，理由同 `scripts/healthcheck.py`：報告不該有副作用，
更不該在正式機上順手把缺掉的表建回去，把真正的問題蓋掉。
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from core import hold_time  # noqa: E402

DEFAULT_DB_PATH = "data/lending.sqlite3"
DEFAULT_INTERVAL_SECONDS = 600


def project_root() -> Path:
    """專案根目錄（本檔在 `scripts/` 底下，往上一層）。"""
    return Path(__file__).resolve().parent.parent


def resolve_db_path(configured_path: Optional[str] = None) -> Path:
    """與 `db/repository.py`、`scripts/healthcheck.py` 完全一致的路徑規則。

    三處必須對齊，否則報告會去別的地方找 DB 然後回報「沒有任何部位」
    ——而機器人其實記得好好的（同 TASKS.md A4 踩過的坑）。
    """
    raw = os.getenv("BFX_DB_PATH") or configured_path or DEFAULT_DB_PATH
    path = Path(raw)
    return path if path.is_absolute() else project_root() / path


def load_positions(db_path: Path, currency: str) -> List[Dict[str, Any]]:
    """唯讀讀出該幣別的全部部位（含仍在借出中的）。"""
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT * FROM funding_positions WHERE currency = ? "
            "ORDER BY COALESCE(opened_at, first_seen_at)",
            (currency,),
        )
        return [dict(row) for row in rows]
    finally:
        connection.close()


def _hours(value: Optional[float]) -> str:
    """None 就寫「—」，不要印出 0.00 假裝有這個數字。"""
    return f"{value:.2f}h" if value is not None else "—"


def format_report(summary: hold_time.HoldSummary, currency: str) -> str:
    """把摘要排成給人讀的報告。

    版面刻意讓三個誠實度來源（右設限、偵測延遲、近似起算時間）跟數字並排，
    而不是收進腳註——量測值旁邊沒有誤差來源，下一個讀到它的人就會把它
    當成精確值（D040）。
    """
    lines: List[str] = []
    lines.append(f"=== {currency} 實際持有時間報告 ===")
    lines.append("")

    if not summary.records:
        lines.append("目前沒有任何可用的部位紀錄。")
        return "\n".join(lines)

    lines.append(
        f"部位總數 {summary.total} 筆："
        f"已結束 {summary.settled} 筆、仍在借出中 {summary.censored} 筆"
        f"（右設限 {summary.censored_ratio * 100:.0f}%）"
    )
    if summary.unusable:
        lines.append(f"⚠ 另有 {summary.unusable} 筆起算時間壞掉，算不出持有時間，未列入。")
    if summary.approximate_opened:
        lines.append(
            f"⚠ 其中 {summary.approximate_opened} 筆沒有交易所端的 opened_at，"
            f"改用「第一次看到它」的時間起算，是高估後的近似值。"
        )
    lines.append("")

    lines.append("--- 逐筆 ---")
    for record in summary.records:
        lines.append("  " + hold_time.describe_record(record))
    lines.append("")

    lines.append("--- 已結束部位的持有時間（右設限的那些不列入）---")
    if summary.enough_for_quantile:
        lines.append(
            f"  平均 {_hours(summary.mean_hours)}"
            f"／中位數 {_hours(summary.median_hours)}"
            f"／四分之一在 {_hours(summary.p25_hours)} 內"
            f"／四分之三在 {_hours(summary.p75_hours)} 內"
        )
    elif summary.settled:
        # 樣本太少時攤開原始值，不要用插值出來的中位數冒充統計量（D040）。
        lines.append(f"  只有 {summary.settled} 筆，直接列出：{summary.hours_listing()}")
    else:
        lines.append("  還沒有已結束的部位。")
    if summary.mean_completion is not None:
        lines.append(
            f"  平均完成率 {summary.mean_completion * 100:.1f}%"
            f"——借到期 {summary.matured} 筆、提前還款 {summary.early} 筆"
            f"（門檻：完成率 ≥ {summary.matured_threshold * 100:.0f}% 算借到期）"
        )
    if summary.detection_lag_hours:
        lines.append(
            f"  ⚠ 以上每一筆都被**高估**最多 {summary.detection_lag_hours * 60:.0f} 分鐘："
            f"closed_at 是我們巡檢時偵測到的時間，不是交易所實際還款的時間。"
        )
    lines.append("")

    lines.append("--- 對照 expected_value.py 的假設 ---")
    if summary.mean_completion is not None:
        lines.append(
            f"  模型假設每筆都借滿天期（完成率 100%），實測平均 "
            f"{summary.mean_completion * 100:.1f}%。"
        )
        lines.append(
            "  分子被高估時，等待成本在 `rate × P ÷ (W + P)` 裡的權重被壓縮，"
            "選出的價位會偏高。"
        )
        lines.append(
            "  **這是觀察，不是結論**：要不要改那個 48、改成什麼，"
            "由 M2 回測工具回答（TASKS.md D1）。"
        )
    else:
        lines.append("  還沒有已結束的部位，對照不出來。")
    lines.append("")

    split = hold_time.split_by_rate(summary)
    lines.append("--- 「越貴借越短」這個假設 ---")
    if split is None:
        lines.append("  已結束的部位不足 2 筆，還分不出兩組。")
    else:
        pivot_annual = split.pivot_rate * 365 * 100
        lines.append(f"  以已結束部位的利率中位數 年化 {pivot_annual:.2f}% 為界：")
        for label, bound, group in (
            ("便宜組", f"< {pivot_annual:.2f}%", split.cheaper),
            ("昂貴組", f"≥ {pivot_annual:.2f}%", split.pricier),
        ):
            if group.enough_for_quantile:
                shape = f"中位數 {_hours(group.median_hours)}"
            elif group.settled:
                shape = f"持有 {group.hours_listing()}"
            else:
                shape = "沒有已結束的部位"
            still_open = f"、另有 {group.censored} 筆仍在借出中" if group.censored else ""
            lines.append(
                f"    {label}（{bound}）：{group.settled} 筆已結束，{shape}{still_open}"
            )

        gap = split.gap_hours
        if gap is None:
            # 這裡刻意不去湊一個差距出來。兩組至少各要 3 筆才比得出中位數，
            # 否則差距只是在比兩個插值出來的虛構數字（見 D040）。
            lines.append(
                f"    **還比不出來**：中位數要兩組各至少 "
                f"{hold_time.MIN_SAMPLES_FOR_QUANTILE} 筆已結束的部位才算得準，"
                f"目前是 {split.cheaper.settled} 與 {split.pricier.settled} 筆。"
            )
            if split.degenerate:
                # 🔴 **上面那句話單獨出現時會騙人。** 它讀起來像「再等幾筆就會好」，
                # 而分界同時是眾數的時候，多蒐集同利率的樣本永遠不會讓便宜組變大
                # ——每一筆都同時把中位數釘在原地、又落進昂貴組。
                # 說「還不夠」跟說「這樣分下去永遠不夠」是兩件事。
                total_settled = split.cheaper.settled + split.pricier.settled
                # ⚠ **兩個「相同」要分開講。** `at_pivot` 是日利率完全相等，
                # `displayed_at_pivot` 是年化印出來相同——2026-08-29 的資料差一筆
                # （0.00024972 對 0.00024971）。只講前者，讀的人會照逐筆那一段
                # 數出後者然後以為報告算錯。
                same_display = ""
                if split.displayed_at_pivot > split.at_pivot:
                    same_display = (
                        f"（另有 {split.displayed_at_pivot - split.at_pivot} 筆的年化"
                        f"也印成 {pivot_annual:.2f}%，但日利率差在小數第 8 位，"
                        f"同樣落在昂貴組）"
                    )
                lines.append(
                    f"    🔴 **而且這個分界不會自己好**：{total_settled} 筆已結束部位裡"
                    f"有 {split.at_pivot} 筆的日利率**完全等於**分界"
                    f"（年化 {pivot_annual:.2f}%，中位數同時是眾數），"
                    f"`<` 把它們全掃進昂貴組{same_display}。"
                )
                lines.append(
                    "    **再多蒐集同一個利率的樣本也不會讓便宜組變大**——"
                    "模型每選一次同樣的價位，就同時把中位數釘在原地、又往昂貴組加一筆。"
                )
                lines.append(
                    f"    ⚠ **而且只有「更低」有用，「別的」不夠**：便宜組收的是"
                    f"`< {pivot_annual:.2f}%`，所以模型選到**更高**的價位一樣落進昂貴組"
                    f"——只會讓失衡更嚴重。"
                )
                lines.append(
                    "    要比得出來，只能等模型選到**低於分界**的價位，"
                    "或改用不靠中位數當分界的分組方式——後者是 M2 的題目，不在這裡拍板。"
                )
            lines.append("    逐筆那一段仍然看得到形狀，只是還不夠下判斷。")
        elif gap > 0:
            lines.append(
                f"    差距 {gap:.2f}h，方向**符合**「越貴借越短」。"
                f"樣本 {split.cheaper.settled + split.pricier.settled} 筆，"
                f"是值得繼續蒐集的訊號，不是結論。"
            )
        else:
            lines.append(
                f"    差距 {gap:.2f}h，方向**不支持**「越貴借越短」。"
                f"樣本 {split.cheaper.settled + split.pricier.settled} 筆。"
            )

    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="實際持有時間報告")
    parser.add_argument("--currency", default="USD", help="幣別（預設 USD）")
    parser.add_argument("--db", default=None, help="SQLite 檔位置（預設讀 config.yaml）")
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

    positions = load_positions(db_path, args.currency)
    summary = hold_time.summarize(
        positions,
        detection_lag_hours=interval_seconds / 3600,
    )
    print(format_report(summary, args.currency))
    return 0


if __name__ == "__main__":
    sys.exit(main())
