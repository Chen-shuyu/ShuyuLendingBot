# -*- coding: utf-8 -*-
"""歷史重播報告：把時間倒回去，問「當時這個策略會掛什麼價」（M2 第 1 步）。

與 `scripts/hold_report.py`（D040）、`scripts/wait_report.py`（D045）並列的第三份
報告，但問的問題不同——前兩份量「已經發生的事」，這一份問「**如果當時不一樣
會怎樣**」。算法本體在 `core/backtest.py`，那裡也寫著三條刻意的界線。

**第 1 步**（`--verify`／`--sweep`）回答「會掛什麼價」，**第 2 步**（`--simulate`）
接上成交模擬，才回答「**那個選擇值多少**」。

用法：

    python3 scripts/backtest_report.py                     # 用 config.yaml 的設定重播
    python3 scripts/backtest_report.py --verify            # 對照正式紀錄（M2 的驗收）
    python3 scripts/backtest_report.py --sweep             # P 掃描：模型會選什麼
    python3 scripts/backtest_report.py --validate-fill     # 成交規則對得上真實成交嗎
    python3 scripts/backtest_report.py --simulate          # P 掃描：實得年化多少（D1）
    python3 scripts/backtest_report.py --step 6 --last 20  # 每 6 根重播一次、只印最後 20 點
    BFX_DB_PATH=/path/to/lending.sqlite3 python3 scripts/backtest_report.py

資料庫一律以**唯讀**開啟，理由同前兩份報告：報告不該有副作用，更不該在正式機上
順手把缺掉的表建回去，把真正的問題蓋掉。
"""

import argparse
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from core import backtest  # noqa: E402
from core import fill_simulation  # noqa: E402
from core import wait_time  # noqa: E402
from db.repository import resolve_db_path  # noqa: E402
from strategies.expected_value import ExpectedValueStrategy  # noqa: E402

# **路徑規則直接用 `db/repository.py` 那一份，不再抄第五份。**
# `hold_report` 與 `wait_report` 各自有一份拷貝，兩份的 docstring 還各自宣告
# 「三處必須對齊」卻點名了不同的三處——再抄一份只會讓那句話更難成立。
# （把那兩份也收掉是另一件事，不混在 M2 這條分支裡改。）

# 🔴 **`orderbook_depth` 刻意不在這裡，而這件事本身是一個發現。**
#
# PLAN.md 給 M2 寫的驗收標準是「拿它跑 `orderbook_depth`，要能重現『賣在區間底部』
# 這個已知結論」。**那個驗收標準在現有資料上跑不起來**，有兩個各自獨立的原因：
#
# 1. **`orderbook_depth` 沒有 `choose_rate()`。** 它的定價在 `build_offer_plan()`
#    裡直接吃訂單簿與成交紀錄，不經過 K 線。重播它要餵的是簿子，不是 K 線。
# 2. **要餵的簿子不存在。** 「賣在區間底部」是 2026-08-16～17 的結論（D033／D035），
#    而 `market_snapshots`（M1-a／D042）**2026-08-23 才開始寫第一列**。
#    那七天的簿子沒有被存下來，而且再也回不來。
#
# **驗收標準是 2026-08-17 寫的，比它所依賴的那張表早了六天**——寫的時候
# 那份資料還不存在，而寫完之後沒有人回頭確認它變得可跑了沒有。
# 這正是 D036 那個病的另一種長相：**條件寫得很具體，但沒有人驗證條件本身成不成立。**
#
# 取代它的驗收標準是 `--verify`：拿 `pricing_decisions` 裡**正式環境真的做過**的
# 決策逐點對照。它比原本那條弱（只證明工具沒偏離、不證明策略對），
# 但它**跑得起來**，而跑不起來的驗收標準等於沒有驗收標準。
STRATEGIES = {
    "expected_value": ExpectedValueStrategy,
}

# `--sweep` 的預設掃描點。**不是隨手挑的**：
#   48.0  = 模型現在寫死的假設（`offer_period` 2 天）
#   25.84 = 已結束部位的四分之三位數
#   16.93 = 實測平均持有（hold_report，17 筆）
#   11.61 = 實測中位持有（同上）
#   1.84  = 四分之一位數，也就是最短的那一叢
DEFAULT_SWEEP_HOURS = (48.0, 25.84, 16.93, 11.61, 1.84)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_candles(
    db_path: Path, currency: str, period: int, timeframe: str
) -> List[Dict[str, Any]]:
    """唯讀讀出 K 線，**由舊到新**排序。

    排序不是為了好看：`core/backtest.py` 的「看不到未來」是靠切片
    `candles[:index + 1]` 達成的，順序錯了就等於讓策略看到未來，
    而且結果會很好看、完全不像壞掉。
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT mts, open, close, high, low, volume FROM market_candles "
            "WHERE currency = ? AND period = ? AND timeframe = ? ORDER BY mts",
            (currency, period, timeframe),
        )
        return [dict(row) for row in rows]
    finally:
        connection.close()


def load_recorded_decisions(
    db_path: Path, currency: str, strategy_name: str
) -> Dict[int, Dict[str, Any]]:
    """唯讀讀出正式環境**真的做過**的定價決策，以 `candle_latest_mts` 為索引。

    這是 PLAN.md 給 M2 的驗收標準的另一半：「重現不出來就是工具不對，不是策略對」。
    `pricing_decisions` 每評估一輪一列（D043），而 `candle_latest_mts` 是那一輪
    窗尾那根 K——**它是重播點與正式輪次之間唯一不會因為時區設定而跑掉的鍵**
    （同 `market_candles` 的選擇理由）。

    同一根 K 的小時內可能有六輪巡檢，這裡**保留最後一輪**：重播用的窗到那根 K
    為止，最接近的就是那個小時最後一次評估。
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT * FROM pricing_decisions WHERE currency = ? AND strategy = ? "
            "AND candle_latest_mts IS NOT NULL ORDER BY decided_at",
            (currency, strategy_name),
        )
        return {int(row["candle_latest_mts"]): dict(row) for row in rows}
    finally:
        connection.close()


def format_verification(
    result: backtest.ReplayResult, recorded: Dict[int, Dict[str, Any]]
) -> str:
    """把重播結果與正式環境的紀錄逐點對照。**這是工具的驗收，不是策略的驗收。**

    對不上有兩種可能，而**它們的意思完全相反**：重播寫錯了，或是 `market_candles`
    少存了幾根 K（機器人每輪向交易所抓 240 根，DB 只留寫進去的那些）。
    所以不合的那幾點要把兩邊的數字都印出來，不要只印一個「❌」。
    """
    lines = ["", "=== 驗收：重播 vs 正式環境真的做過的決策 ===", ""]
    if not recorded:
        lines.append(
            "  `pricing_decisions` 裡沒有這個策略的紀錄，**這一項無法驗收**"
            "——不是通過。"
        )
        return "\n".join(lines)

    by_mts = {point.mts: point for point in result.points}
    matched: List[str] = []
    mismatched: List[str] = []
    missing = 0
    for mts, row in sorted(recorded.items()):
        point = by_mts.get(mts)
        if point is None:
            missing += 1
            continue
        expected = row["chosen_rate"]
        actual = point.chosen_rate
        same = (expected is None and actual is None) or (
            expected is not None
            and actual is not None
            and abs(expected - actual) < 1e-12
        )
        label = (
            f"{point.at.strftime('%m-%d %H:%M')}  "
            f"正式 {_pct(None if expected is None else expected * 365 * 100)}"
            f"  重播 {_pct(point.chosen_annual_pct)}"
        )
        (matched if same else mismatched).append(label)

    total = len(matched) + len(mismatched)
    lines.append(
        f"  正式紀錄 {len(recorded)} 列 → 對得上重播點的 {total} 列"
        + (f"（另有 {missing} 列在重播範圍外，K 線沒存到那根）" if missing else "")
    )
    if total:
        lines.append(
            f"  **逐點一致 {len(matched)} 列、不一致 {len(mismatched)} 列**"
        )
    if mismatched:
        lines.append("")
        lines.append("  ❌ 不一致的點（兩邊的數字都印出來，成因見本函式的說明）：")
        for label in mismatched[:20]:
            lines.append(f"     {label}")
        if len(mismatched) > 20:
            lines.append(f"     …另有 {len(mismatched) - 20} 點")
    elif total:
        lines.append("")
        lines.append(
            "  ✅ **全數一致**——重播呼叫的是策略本尊，所以這代表工具沒有偏離正式環境。"
        )
        lines.append(
            "  ⚠ 但這只證明「同一份輸入算出同一個答案」，**不證明策略是對的**。"
        )
    return "\n".join(lines)


def load_wait_spells(db_path: Path, currency: str, interval_seconds: int):
    """唯讀讀出掛單／部位／預估值，交給 `core/wait_time.py` 配對成掛單期間。

    **不自己從 `loan_offers` 配一次**：合併規則（同利率、中間沒成交過）與
    右設限、偵測延遲的處置全在 `wait_time` 裡，抄第二份出來一定會漂
    ——D045 的實作就是在那一步被一個靜默吃掉樣本的合併 bug 咬過。
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        offers = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM loan_offers WHERE currency = ? AND status = 'submitted' "
                "ORDER BY created_at",
                (currency,),
            )
        ]
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
    finally:
        connection.close()
    return wait_time.summarize(
        offers,
        positions,
        forecasts=forecasts,
        detection_lag_hours=interval_seconds / 3600,
    ).spells


def format_fill_validation(validation) -> str:
    """成交規則的驗收表。**這是模擬器的驗收，不是策略的驗收。**"""
    lines = ["", "=== 驗收：成交規則對得上真實成交嗎 ===", ""]
    comparable = validation.comparable
    if not comparable:
        lines.append("  沒有可比對的成交——**這一項無法驗收**，不是通過。")
        return "\n".join(lines)

    lines.append(
        _pad("掛出時間", 16)
        + _pad("年化", 9, right=True)
        + _pad("實際等待", 11, right=True)
        + _pad("模擬等待", 11, right=True)
        + _pad("模擬/實際", 11, right=True)
    )
    for row in validation.rows:
        if row.simulated_hours is None:
            lines.append(
                _pad(row.started_at.strftime("%m-%d %H:%M"), 16)
                + _pad(_pct(row.rate * 365 * 100), 9, right=True)
                + _pad(_hours(row.actual_hours), 11, right=True)
                + f"  {row.note}"
            )
            continue
        ratio = f"{row.ratio:.2f}×" if row.ratio is not None else "—"
        lines.append(
            _pad(row.started_at.strftime("%m-%d %H:%M"), 16)
            + _pad(_pct(row.rate * 365 * 100), 9, right=True)
            + _pad(_hours(row.actual_hours), 11, right=True)
            + _pad(_hours(row.simulated_hours), 11, right=True)
            + _pad(ratio, 11, right=True)
        )

    total = validation.total_ratio()
    above = validation.above_resolution
    lines.append("")
    lines.append(
        f"  **可比對 {len(comparable)} 筆，總量比 {total:.2f}×**"
        f"（模擬合計 {sum(r.simulated_hours for r in comparable):.2f}h"
        f" vs 實際合計 {sum(r.actual_hours for r in comparable):.2f}h）"
    )
    if above:
        lines.append(
            f"  實際等待 ≥ 1 小時的 {len(above)} 筆：總量比 "
            f"{validation.total_ratio(above):.2f}×"
        )
    lines.append("")
    lines.append(
        "  📌 **要讀的是總量比，不是逐筆倍數**：K 線一小時一根，而多數樣本的實際"
        "等待不到一小時，那些筆的 0.00× 與 — 是解析度雜訊，不是誤差。"
    )
    lines.append(
        "  ✅ 對照組：策略自己的 `estimate_wait()` 在同一批樣本上是 **4.25 倍高估**"
        "（D045）。**模擬器準了一個數量級**，這是它能拿來當裁判的理由。"
    )
    lines.append(
        "  ⚠ **模擬的成交必然偏快**：`high >= rate` 只說有需求掃到這個價位，"
        "沒說掃掉的量足夠輪到我們那 345 USD。"
    )
    lines.append(
        "  ⚠ **樣本全落在年化 5.47%～10.95%**——那正是模型自己選出來的帶，"
        "**帶外沒有驗證過**（與 D045 同一條界線）。"
    )
    return "\n".join(lines)


def format_simulation(rows, hold_label: str, horizon_hours: float) -> str:
    """D1 的答案表：策略以為自己會借多久，換掉之後**實得年化**多少。"""
    lines = ["", "=== 成交模擬：換掉那個 48，實得年化會怎樣 ===", ""]
    lines.append(
        f"實際持有用「{hold_label}」／歷史長度約 {horizon_hours / 24:.1f} 天"
    )
    lines.append("")
    lines.append(
        _pad("策略假設 P", 14, right=True)
        + _pad("實得年化", 11, right=True)
        + _pad("循環數", 9, right=True)
        + _pad("成交率", 9, right=True)
        + _pad("等待中位", 11, right=True)
    )
    for assumed, outcome in rows:
        lines.append(
            _pad(f"{assumed:.2f}h", 14, right=True)
            + _pad(_pct(outcome.realized_annual_pct), 11, right=True)
            + _pad(str(len(outcome.cycles)), 9, right=True)
            + _pad(
                f"{outcome.fill_rate * 100:.0f}%" if outcome.fill_rate is not None else "—",
                9,
                right=True,
            )
            + _pad(_hours(outcome.median_wait_hours), 11, right=True)
        )

    lines.append("")
    lines.append(
        "  ✅ **分母含空等與空轉**：沒等到成交的每一個小時都以 0% 計入。"
        "`wait_report` 印的 7.99% 就是因為少了這一塊才偏樂觀。"
    )
    lines.append(
        "  🔴 **不要從這張表挑一個數字去改那個 48。** 相鄰幾列的差距"
        "（約 0.1～0.3 個百分點）在這個樣本數下是雜訊：歷史只有十幾天、"
        "循環只有十幾次，而曲線本身不是單調的。**挑最高的那一列就是"
        "`target_queue_usd` 的死法**（D032）。"
    )
    lines.append(
        "  ⚠ **這張表講的是方向，不是數值**：要拿它下手改參數，"
        "至少得先有一段「模型沒有參與過」的歷史（現在這段是模型自己選出來的），"
        "以及跨時段都站得住的結論。"
    )
    return "\n".join(lines)


REPOST_POLICIES = (
    ("不重掛（下界對照）", lambda: None),
    ("★ 現況：2% 容差雙向", lambda: fill_simulation.rate_tolerance(2.0)),
    ("只往下，2% 容差", lambda: fill_simulation.down_only(2.0)),
    ("躺 12.6h 後才往下", lambda: fill_simulation.down_after_idle(12.6)),
    ("躺 18.9h 後才往下", lambda: fill_simulation.down_after_idle(18.9)),
    ("候選一變就跟（上界）", lambda: fill_simulation.follow_candidate()),
)


def format_repost(rows, assumed_hold: float) -> str:
    """A2-b 的比較表（D046／D050）。**機器人的重掛邏輯一行都沒有改。**"""
    lines = ["", "=== 重掛政策比較（A2-b，只在模擬裡跑）===", ""]
    lines.append(f"策略假設 P = {assumed_hold:.2f}h")
    lines.append("")
    lines.append(
        _pad("重掛政策", 26)
        + _pad("實得年化", 11, right=True)
        + _pad("循環", 7, right=True)
        + _pad("成交率", 8, right=True)
        + _pad("改掛次數", 10, right=True)
    )
    for name, outcome in rows:
        lines.append(
            _pad(name, 26)
            + _pad(_pct(outcome.realized_annual_pct), 11, right=True)
            + _pad(str(len(outcome.cycles)), 7, right=True)
            + _pad(
                f"{outcome.fill_rate * 100:.0f}%" if outcome.fill_rate is not None else "—",
                8,
                right=True,
            )
            + _pad(str(outcome.repost_count), 10, right=True)
        )

    spread = None
    values = [o.realized_annual_pct for _, o in rows if o.realized_annual_pct is not None]
    if values:
        spread = max(values) - min(values)
    lines.append("")
    if spread is not None and spread < 0.05:
        lines.append(
            f"  🔴 **分不出勝負**：最好與最差差 {spread:.2f} 個百分點。"
            "**而這不是因為沒有機會作用**——等待佔掉整段歷史約三成。"
        )
        lines.append(
            "     成因是**訊號太慢**：候選價位來自 168 小時的窗，"
            "一場十幾小時的乾旱幾乎推不動它（D050）。"
            "最長那段空掛裡，候選價位**前 32 小時完全沒動**。"
        )
        lines.append(
            "  📌 **所以 A2-b 的下一步不是挑一個門檻，是換一個訊號**"
            "——重掛的判斷需要比定價更短的視野。"
        )
    lines.append(
        "  ⚠ **模擬看不到重掛的兩項成本**，兩項都讓重掛顯得比實際划算："
        "(1) 取消會把排隊位置歸零；(2) 取消當下就成交的風險（D031 真的發生過）。"
        "**所以上面的差距是上界。**"
    )
    return "\n".join(lines)


def format_signals(cycles, highs, comparison) -> str:
    """D054：訊號偵測得多快，以及「拿它降價」到底划不划算。"""
    lines = ["", "=== 訊號比較：我的單躺太久了嗎（A2-b 的下一步，D054）===", ""]

    長 = [c for c in cycles if c.wait_hours >= 6]
    短 = [c for c in cycles if c.wait_hours < 6]

    def 第幾小時發話(cycle, threshold=3.0):
        for hour in range(0, int(cycle.wait_hours) + 1):
            ratio = fill_simulation.stale_ratio(highs, cycle.decided_index + hour, cycle.rate)
            if ratio is not None and ratio >= threshold:
                return hour
        return None

    lines.append("--- 上半場：偵測得準不準 ---")
    lines.append(
        f"  長等待（≥6h）{len(長)} 段、快速成交（<6h）{len(短)} 段"
    )
    命中 = [第幾小時發話(c) for c in 長]
    誤報 = [c for c in 短 if 第幾小時發話(c) is not None]
    lines.append(
        f"  **命中間隔比 ≥3× 在長等待上發話 {sum(1 for h in 命中 if h is not None)}／{len(長)} 段**"
        f"（第 {min(h for h in 命中 if h is not None)}～{max(h for h in 命中 if h is not None)} 小時），"
        f"快速成交上誤報 **{len(誤報)}／{len(短)}**"
    )
    lines.append(
        "  ✅ **門檻 1.5×～4× 都是同一個結果**——這是它與 `target_queue_usd` 的差別："
        "**不是挑出來的一個點，是一整片高原。**"
    )
    lines.append(
        "  📌 對照組：**候選價位（現況用的訊號）在這 5 段裡只有 1 段發話，而且在第 30 小時**"
        "——那時候那段等待已經走完 78%（D050）。"
    )

    lines.append("")
    lines.append("--- 🔴 下半場：拿它去降價，划不划算 ---")
    if comparison.get("samples"):
        lines.append(
            f"  {comparison['samples']} 個起跑點平均："
            f"不重掛 **{comparison['baseline_mean']:.2f}%** → "
            f"躺太久就降價 **{comparison['candidate_mean']:.2f}%**"
            f"（**{comparison['difference']:+.2f} 個百分點**）"
        )
        lines.append(
            f"  勝率 {comparison['candidate_wins']}／{comparison['samples']}，"
            f"最好 {comparison['best_gain']:+.2f}pp、最差 {comparison['worst_loss']:+.2f}pp"
        )
        lines.append("")
        lines.append(
            "  🔴 **偵測得好，不等於知道該做什麼。** 降價會把一個較差的利率"
            "**鎖住最多 48 小時**，而省下來的只是一段等待——**贏很多次、輸很大次**。"
        )
        lines.append(
            "  ⚠ **只看勝率會得到相反的結論**：`lookback=12` 贏過半數的起跑點，"
            "平均仍然是輸的。**平均與勝率要一起看。**"
        )
        lines.append(
            "  🔴 **而且單一起跑點會給出相反的符號**：同一個政策在單一起跑點上"
            "比基準高 0.70 個百分點，平均掉相位運氣之後低 2.16 個百分點。"
            "**D049／D050 都是單一起跑點跑出來的。**"
        )
    return "\n".join(lines)


def _display_width(text: str) -> int:
    """字串在等寬終端機裡佔幾格（中文全形算兩格）。同 `wait_report`。"""
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def _pad(text: str, width: int, right: bool = False) -> str:
    padding = " " * max(width - _display_width(text), 0)
    return padding + text if right else text + padding


def _pct(value: Optional[float]) -> str:
    """None 就寫「—」，不要印出 0.00 假裝有這個數字（同前兩份報告）。"""
    return f"{value:.2f}%" if value is not None else "—"


def _hours(value: Optional[float]) -> str:
    return f"{value:.2f}h" if value is not None else "—"


def format_replay(result: backtest.ReplayResult, last: Optional[int]) -> str:
    """重播結果的逐點表 ＋ 一段「這張表能講什麼、不能講什麼」。"""
    lines: List[str] = []
    lines.append("=== 歷史重播：當時會掛什麼價 ===")
    lines.append("")
    lines.append(
        f"策略 {result.strategy_name}／窗長 {result.window_hours}h／"
        f"一根 K = {result.candle_hours}h／假設借出 {result.hold_hours:.2f}h"
    )
    lines.append(
        f"K 線 {result.candles_supplied} 根 → 重播 {len(result.points)} 點："
        f"選出價位 {len(result.decided)} 點、沒選出 {len(result.skipped)} 點"
    )

    if not result.points:
        lines.append("")
        lines.append("沒有任何重播點——`market_candles` 是空的，或篩選條件沒對上。")
        return "\n".join(lines)

    shown = result.points[-last:] if last else result.points
    lines.append("")
    if last and len(shown) < len(result.points):
        lines.append(f"--- 逐點（只印最後 {len(shown)} 點，共 {len(result.points)} 點）---")
    else:
        lines.append("--- 逐點 ---")

    header = (
        _pad("時間", 18)
        + _pad("選中年化", 10, right=True)
        + _pad("實質年化", 10, right=True)
        + _pad("W平均", 9, right=True)
        + _pad("W中位", 9, right=True)
        + _pad("設限", 8, right=True)
        + "  候選"
    )
    lines.append(header)
    for point in shown:
        if point.chosen_rate is None:
            lines.append(
                _pad(point.at.strftime("%m-%d %H:%M"), 18)
                + f"（沒選出價位）{point.skip_reason}"
            )
            continue
        censored = (
            f"{point.chosen_censored_ratio * 100:.1f}%"
            if point.chosen_censored_ratio is not None
            else "—"
        )
        lines.append(
            _pad(point.at.strftime("%m-%d %H:%M"), 18)
            + _pad(_pct(point.chosen_annual_pct), 10, right=True)
            + _pad(_pct(point.effective_annual_pct), 10, right=True)
            + _pad(_hours(point.chosen_wait_mean), 9, right=True)
            + _pad(_hours(point.chosen_wait_median), 9, right=True)
            + _pad(censored, 8, right=True)
            + f"  {point.candidate_count}"
        )

    lines.extend(_replay_caveats(result))
    return "\n".join(lines)


def _replay_caveats(result: backtest.ReplayResult) -> List[str]:
    """這張表能講什麼、不能講什麼。**寫在輸出裡，不寫在文件裡。**

    理由與 `hold_report`／`wait_report` 相同：會被拿去下判斷的是終端機上那幾行，
    不是 DECISIONS.md 裡的某一段。
    """
    lines = ["", "--- 這張表能講什麼 ---"]
    lines.append("  ✅ 「當時這個策略會掛什麼價」——重播呼叫的是策略本尊，不是它的副本。")
    lines.append(
        "  ❌ **這張表本身不能講「賺多少」**：它只有「會掛什麼價」。"
        "實得年化要接上成交模擬（`--simulate`，M2 第 2 步）。"
    )
    lines.append(
        "  ❌ **不能講「跑了幾輪」**：K 線一小時一根、機器人 600 秒一輪，"
        "同一小時的六輪在這裡是同一點。"
    )
    decided = result.decided
    if decided:
        rates = {point.chosen_rate for point in decided}
        lines.append(
            f"  ⚠ {len(decided)} 個決策點只選出 **{len(rates)} 個相異價位**"
            + ("——候選集再大，實際被選中的價位其實很集中。" if len(rates) < 10 else "。")
        )
    if result.skipped:
        first = result.skipped[0]
        lines.append(
            f"  ⚠ 有 {len(result.skipped)} 點沒選出價位，第一點的理由："
            f"{first.skip_reason}"
        )
    return lines


def format_sweep(rows: List[backtest.HoldSweepRow], at_label: str) -> str:
    """`P` 掃描表：換一個借出時間假設，模型會被推到哪裡去（D1）。"""
    lines = ["", f"=== 把 `P` 換掉再選一次（重播點：{at_label}）===", ""]
    lines.append(
        _pad("假設借出 P", 14, right=True)
        + _pad("選中年化", 10, right=True)
        + _pad("實質年化", 10, right=True)
        + _pad("W平均", 9, right=True)
        + _pad("W中位", 9, right=True)
    )
    for row in rows:
        if row.chosen_rate is None:
            lines.append(
                _pad(f"{row.hold_hours:.2f}h", 14, right=True)
                + f"  （沒選出價位）{row.skip_reason}"
            )
            continue
        lines.append(
            _pad(f"{row.hold_hours:.2f}h", 14, right=True)
            + _pad(_pct(row.chosen_annual_pct), 10, right=True)
            + _pad(_pct(row.effective_annual_pct), 10, right=True)
            + _pad(_hours(row.wait_mean), 9, right=True)
            + _pad(_hours(row.wait_median), 9, right=True)
        )

    lines.append("")
    lines.append("  🔴 **這張表回答「模型會選什麼」，不是「哪個假設賺比較多」。**")
    lines.append(
        "     三個假設下的 `effective` 分母不同，**數字不可以直接比大小**"
        "——同一個陷阱在 `wait_report` 的統計量對照表上已經標過一次。"
    )
    lines.append(
        "  ⚠ **也不要拿它去改那個 48**：實測持有逐筆從 0.50h 到 48.56h，"
        "換成任何一個常數都只是 `target_queue_usd` 的死法（D032）。"
    )
    lines.append("     要回答「該換成什麼」得等 M2 第 2 步（成交模擬）。")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="歷史重播報告（M2 第 1 步）")
    parser.add_argument("--currency", default="USD", help="幣別（預設 USD）")
    parser.add_argument("--db", default=None, help="SQLite 檔位置（預設讀 config.yaml）")
    parser.add_argument("--period", type=int, default=2, help="K 線的天期（預設 2）")
    parser.add_argument("--timeframe", default="1h", help="K 線時間框架（預設 1h）")
    parser.add_argument(
        "--strategy",
        default="expected_value",
        choices=sorted(STRATEGIES),
        help="要重播哪個策略（預設 expected_value）",
    )
    parser.add_argument("--step", type=int, default=1, help="每幾根 K 重播一次（預設 1）")
    parser.add_argument(
        "--last", type=int, default=24, help="逐點表只印最後幾點（0 = 全印，預設 24）"
    )
    parser.add_argument(
        "--hold-hours",
        type=float,
        default=None,
        help="把假設的借出時間換掉再重播（小時）。不給就用 config.yaml 的 offer_period",
    )
    parser.add_argument(
        "--sweep", action="store_true", help="多印一張 P 掃描表（D1 的問題）"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="拿 `pricing_decisions` 的正式紀錄逐點對照重播結果（M2 的驗收標準）",
    )
    parser.add_argument(
        "--validate-fill",
        action="store_true",
        help="拿真實成交檢驗成交規則（M2 第 2 步的驗收）",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="接上成交模擬，算出換掉那個 48 之後的**實得年化**（D1）",
    )
    parser.add_argument(
        "--signals",
        action="store_true",
        help="比較「我的單躺太久了」這個訊號的偵測力與獲利（D054，只在模擬裡跑）",
    )
    parser.add_argument(
        "--repost",
        action="store_true",
        help="比較幾種重掛政策的實得年化（A2-b，只在模擬裡跑）",
    )
    parser.add_argument(
        "--hold-model",
        default="empirical",
        help="實際持有時間怎麼給：empirical（實測分佈，預設）或 fixed:<小時>",
    )
    args = parser.parse_args(argv)

    config: Dict[str, Any] = {}
    try:
        config_path = settings.resolve_config_path(project_root())
        config = settings.load_config(str(config_path)) or {}
    except Exception:
        # 報告不該因為設定檔讀不到就整支掛掉（同前兩份報告）。
        config = {}

    configured = args.db or ((config.get("database") or {}).get("path"))
    db_path = resolve_db_path(configured)
    if not db_path.exists():
        print(f"找不到資料庫：{db_path}", file=sys.stderr)
        return 1

    candles = load_candles(db_path, args.currency, args.period, args.timeframe)
    if not candles:
        print(
            f"`market_candles` 裡沒有 {args.currency}／period={args.period}／"
            f"timeframe={args.timeframe} 的 K 線。",
            file=sys.stderr,
        )
        return 1

    strategy = STRATEGIES[args.strategy](config)
    if not hasattr(strategy, "choose_rate"):
        # 走不到，但留著：`STRATEGIES` 之後一定會有人再加東西進去，
        # 而那時候的錯誤訊息應該講出原因，不是丟一個 AttributeError。
        print(
            f"{type(strategy).__name__} 沒有 `choose_rate()`，這個重播器餵的是 K 線，"
            "餵不了它——理由見本檔 `STRATEGIES` 上方的說明。",
            file=sys.stderr,
        )
        return 1
    result = backtest.replay(
        strategy, candles, hold_hours=args.hold_hours, step=max(args.step, 1)
    )
    print(format_replay(result, args.last or None))

    if args.verify:
        recorded = load_recorded_decisions(
            db_path, args.currency, type(strategy).__name__
        )
        print(format_verification(result, recorded))

    if args.sweep:
        rows = backtest.sweep_hold_hours(strategy, candles, DEFAULT_SWEEP_HOURS)
        label = result.points[-1].at.strftime("%m-%d %H:%M") if result.points else "—"
        print(format_sweep(rows, label))

    if args.validate_fill:
        interval = int(
            (config.get("engine") or {}).get("interval_seconds", 600) or 600
        )
        spells = load_wait_spells(db_path, args.currency, interval)
        print(
            format_fill_validation(
                fill_simulation.validate_against_real_fills(spells, candles)
            )
        )

    if args.simulate:
        try:
            hold_model, hold_label = _build_hold_model(args.hold_model)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        rows = []
        for assumed in DEFAULT_SWEEP_HOURS:
            # **每一次都建一個新的策略實例**：`choose_rate()` 會把「本輪」的
            # 評估結果留在成員上（D041 的那四個），跨設定共用一個實例
            # 等於讓上一組設定的殘留參與下一組的結果。
            rows.append(
                (
                    assumed,
                    fill_simulation.run_policy(
                        STRATEGIES[args.strategy](config),
                        candles,
                        hold_model=hold_model,
                        hold_model_name=hold_label,
                        assumed_hold_hours=assumed,
                    ),
                )
            )
        print(format_simulation(rows, hold_label, len(candles) * 1.0))

    if args.repost:
        try:
            hold_model, _ = _build_hold_model(args.hold_model)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        assumed = args.hold_hours if args.hold_hours is not None else 48.0
        rows = []
        for name, build in REPOST_POLICIES:
            rows.append(
                (
                    name,
                    fill_simulation.run_policy(
                        STRATEGIES[args.strategy](config),
                        candles,
                        hold_model=hold_model,
                        assumed_hold_hours=assumed,
                        repost_policy=build(),
                        repost_policy_name=name,
                    ),
                )
            )
        print(format_repost(rows, assumed))

    if args.signals:
        try:
            hold_model, _ = _build_hold_model(args.hold_model)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        highs = [candle["high"] for candle in candles]
        assumed = args.hold_hours if args.hold_hours is not None else 48.0
        cycles = fill_simulation.run_policy(
            STRATEGIES[args.strategy](config),
            candles,
            hold_model=hold_model,
            assumed_hold_hours=assumed,
        ).cycles
        # **跨起跑點平均，不是單跑一次**——理由見 `run_policy_across_starts()`。
        starts = list(range(48, min(len(candles), 220), 8))
        shared = dict(hold_model=hold_model, assumed_hold_hours=assumed)
        baseline = fill_simulation.run_policy_across_starts(
            lambda: STRATEGIES[args.strategy](config), candles, starts, **shared
        )
        candidate = fill_simulation.run_policy_across_starts(
            lambda: STRATEGIES[args.strategy](config),
            candles,
            starts,
            repost_policy=fill_simulation.down_when_stale(highs, 3.0, 24),
            **shared,
        )
        print(
            format_signals(
                cycles, highs, fill_simulation.compare_across_starts(baseline, candidate)
            )
        )

    return 0


def _build_hold_model(spec: str):
    """`--hold-model` 的字串轉成 `HoldModel`。回傳 `(模型, 給人看的名字)`。"""
    if spec == "empirical":
        return (
            fill_simulation.empirical_hold(),
            f"實測分佈（{len(fill_simulation.OBSERVED_HOLD_HOURS)} 筆）",
        )
    if spec.startswith("fixed:"):
        try:
            hours = float(spec.split(":", 1)[1])
        except ValueError:
            raise ValueError(f"看不懂的 --hold-model：{spec}（格式是 fixed:<小時>）")
        return fill_simulation.fixed_hold(hours), f"固定 {hours:g}h"
    raise ValueError(f"看不懂的 --hold-model：{spec}（可用 empirical 或 fixed:<小時>）")


if __name__ == "__main__":
    sys.exit(main())
