# -*- coding: utf-8 -*-
"""SQLite 讀寫封裝（WAL 模式）。

採「單一寫入者（主迴圈）+ 多唯讀查詢（未來報表 / 狀態頁）」模型，天然避免
寫入衝突；WAL 則讓讀取不會被寫入擋住。主迴圈是單執行緒，因此整支程式共用
一條連線即可。
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from db import models
from utils import clock

DEFAULT_DB_PATH = "data/lending.sqlite3"

# 專案根目錄（本檔在 `db/` 底下，往上一層）。相對路徑一律以它為基準，
# 與 `scripts/healthcheck.py` 的 `project_root()` 算法保持一致。
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def resolve_db_path(configured_path: Optional[str] = None) -> Path:
    """決定 SQLite 檔位置：環境變數優先，其次設定值，最後預設值。

    相對路徑一律相對於**專案根目錄**，而不是當下的工作目錄。這一點必須跟
    `scripts/healthcheck.py` 的 `resolve_db_path()` 完全一致，否則兩邊會算出
    不同的檔案位置：主程式在啟動它的地方建 DB、健康檢查仍去專案目錄找，
    結果是健康檢查永遠回報「尚未寫入任何心跳」，但機器人其實跑得好好的
    （見 TASKS.md A4）。這種錯誤很難聯想到是路徑問題，所以兩邊的規則
    ——包含 `BFX_DB_PATH` 的優先權——都要對齊。

    config.yaml 對 `database.path` 的註解本來就寫「相對於專案根目錄」，
    這裡是讓程式的行為追上文件的說法。
    """
    raw = os.getenv("BFX_DB_PATH") or configured_path or DEFAULT_DB_PATH
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path

# loan_offers.status 的可能值
STATUS_SUBMITTED = "submitted"
STATUS_DRY_RUN = "dry_run"
STATUS_FAILED = "failed"


def now_iso() -> str:
    """目前時間的 ISO 8601 字串（秒為精度），**一律帶時區偏移**。

    2026-08-16 起改寫專案時區（預設 `Asia/Taipei`），寫出來長這樣：
    `2026-08-16T14:11:14+08:00`。原本是 UTC，於是 DB 查出來的心跳跟主機時間差 8 小時，
    對帳時要自己在腦內加減。

    **舊資料不需要遷移**：舊列帶的是 `+00:00`、新列帶 `+08:00`，兩者都是 aware，
    `scripts/healthcheck.py` 拿去相減得到的秒數完全正確——時區偏移不同不影響時間點比較。
    """
    return clock.now().isoformat(timespec="seconds")


def _millis_to_iso(millis) -> Optional[str]:
    """把 Bitfinex 的毫秒時間戳轉成本專案格式的 ISO 字串。

    轉不動就回 None 而不是拋例外：這個欄位是「幾點借出去的」這種輔助資訊，
    為了它讓一輪巡檢失敗並不划算——真正重要的是部位本身有沒有被記錄下來。
    """
    if millis is None:
        return None
    try:
        moment = datetime.fromtimestamp(int(millis) / 1000, tz=clock.get_timezone())
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    return moment.isoformat(timespec="seconds")


class Repository:
    """掛單流水、已借出部位、每日收益、機器人狀態的持久化封裝。"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = resolve_db_path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.db_path))
        self.connection.row_factory = sqlite3.Row
        # WAL：讀寫並行不互鎖。
        self.connection.execute("PRAGMA journal_mode=WAL;")
        # 搭配 WAL 用 NORMAL 就夠：最壞情況是主機斷電時失去最後幾筆寫入，
        # 資料庫本身不會損毀，而放貸紀錄本來就能從交易所端重新取得。
        self.connection.execute("PRAGMA synchronous=NORMAL;")
        self._create_schema()

    @classmethod
    def from_config(cls, config) -> "Repository":
        """依 config.yaml 的 `database.path` 建立（相對路徑相對於專案根目錄）。"""
        database_config = (config or {}).get("database", {}) or {}
        return cls(database_config.get("path") or DEFAULT_DB_PATH)

    def _create_schema(self) -> None:
        with self.connection:
            for statement in models.ALL_STATEMENTS:
                self.connection.execute(statement)

    def record_offer(self, plan, result: Dict[str, Any]) -> None:
        """記錄一筆已送出的掛單。

        dry-run 也照樣寫入（status 為 `dry_run`），這樣不必連上實盤就能驗證資料層。
        金額／利率／天期優先採用交易所回報的值，取不到才退回策略層原本的計畫值——
        兩者在部分成交或交易所調整時可能不同，落帳要以交易所為準。
        """
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO loan_offers
                    (offer_id, currency, amount, rate, duration, status, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(result.get("id")) if result.get("id") is not None else None,
                    plan.currency,
                    float(result.get("amount", plan.amount)),
                    float(result.get("rate", plan.rate)),
                    int(result.get("period", result.get("duration", plan.duration))),
                    result.get("status") or STATUS_SUBMITTED,
                    result.get("symbol"),
                    now_iso(),
                ),
            )

    def record_offer_failure(self, plan, reason: str) -> None:
        """記錄一筆掛單失敗。

        失敗的嘗試同樣要留痕：掛單 API 無法 rollback，同一輪若第一筆成功、第二筆
        失敗，錢已經出去了，只有逐筆落帳才看得出當下的真實狀態。
        """
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO loan_offers
                    (offer_id, currency, amount, rate, duration, status, detail, created_at)
                VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.currency,
                    float(plan.amount),
                    float(plan.rate),
                    int(plan.duration),
                    STATUS_FAILED,
                    str(reason),
                    now_iso(),
                ),
            )

    def record_wait_forecast(self, offer_id, forecast: Dict[str, Any]) -> None:
        """記下一張掛單在送出當下對「要等多久」的預估（D038）。

        `offer_id` 取不到（dry-run、或交易所沒回 id）就直接跳過：這張表的用途是
        事後把預估與實際等待對起來，而對不起來的列只會讓校準資料變髒。

        重掛同一個價位會拿到新的 offer_id，所以主鍵衝突理論上不會發生；
        真的撞到就以新的為準（`INSERT OR REPLACE`），因為同一個 id 在場上只有一張單。
        """
        if offer_id is None:
            return
        with self.connection:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO offer_wait_forecasts
                    (offer_id, rate, mean_hours, median_hours, p75_hours,
                     hits, censored_ratio, window_hours, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(offer_id),
                    float(forecast["rate"]),
                    float(forecast["mean_hours"]),
                    float(forecast["median_hours"]),
                    float(forecast["p75_hours"]),
                    int(forecast["hits"]),
                    float(forecast["censored_ratio"]),
                    int(forecast["window_hours"]),
                    now_iso(),
                ),
            )

    def get_wait_forecast(self, offer_id) -> Optional[Dict[str, Any]]:
        """取回某張掛單當初的等待預估；沒有就回 `None`。

        回 `None` 是正常情況而不是錯誤：這張表 2026-08-19 才加，在它之前掛出去的單
        本來就沒有預估，機器人要能照常運作並在日誌裡說「沒有留下當初的預估」。
        """
        if offer_id is None:
            return None
        row = self.connection.execute(
            "SELECT * FROM offer_wait_forecasts WHERE offer_id = ?", (str(offer_id),)
        ).fetchone()
        return dict(row) if row else None

    def record_market_snapshot(
        self,
        currency: str,
        frr: Optional[float],
        book: Optional[Dict[str, Any]] = None,
        trades: Optional[Dict[str, Any]] = None,
        candles: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """記下這一輪市場長什麼樣（M1），回傳這一列的 id（沒寫列就回傳 `None`）。

        **回傳 id 是 M1-b 加的**：`pricing_decisions` 要指回本輪的市場長相，
        而「本輪」這件事只有這裡知道。用時間去 JOIN 是行不通的——同一秒可能有
        兩列，而且決策比快照晚幾百毫秒才產生。

        **三份摘要都可以是 `None`**：策略用不到的端點根本不會去打
        （`requires_book` / `requires_trades` / `requires_candles`），
        而抓回來是空清單也是一種真實情況。那些欄位就留 NULL——
        **「沒觀測到」跟「觀測到 0」是兩件事**，用 0 填會讓事後分析
        把一段沒有資料的期間讀成一段市場死掉的期間。

        **三份全都是 `None`、而且連 FRR 都沒有，才不寫列。** 一列除了時間什麼都沒有的
        紀錄對 M2 沒有用處，只會讓「這段期間有幾筆觀測」這個數字說謊；
        但只有 FRR 的一列仍然值得存——`bot_state.last_frr` 是單列表，每輪覆蓋，
        **FRR 的歷史除了這裡沒有第二個地方留得下來**。
        """
        if book is None and trades is None and candles is None and frr is None:
            return None

        book = book or {}
        trades = trades or {}
        candles = candles or {}
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO market_snapshots
                    (captured_at, currency, frr,
                     book_levels, book_lowest_rate, book_highest_rate, book_truncated,
                     book_total_amount, book_curve_json, book_period_totals_json,
                     trade_count, trade_span_minutes, trade_latest_mts, trade_volume,
                     trade_rate_min, trade_rate_median, trade_rate_weighted_median,
                     trade_rate_max, trade_period_rates_json, trade_period_counts_json,
                     candle_count, candle_latest_mts, candle_high_median,
                     candle_high_p75, candle_high_max, candle_close_latest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_iso(),
                    currency,
                    None if frr is None else float(frr),
                    book.get("levels"),
                    book.get("lowest_rate"),
                    book.get("highest_rate"),
                    # SQLite 沒有布林型別；存 0/1 而不是 'true'/'false'，
                    # 這樣 `WHERE book_truncated = 1` 這種查詢才不必記得引號。
                    None if book.get("truncated") is None else int(bool(book["truncated"])),
                    book.get("total_amount"),
                    book.get("curve_json"),
                    book.get("period_totals_json"),
                    trades.get("count"),
                    trades.get("span_minutes"),
                    trades.get("latest_mts"),
                    trades.get("volume"),
                    trades.get("rate_min"),
                    trades.get("rate_median"),
                    trades.get("rate_weighted_median"),
                    trades.get("rate_max"),
                    trades.get("period_rates_json"),
                    trades.get("period_counts_json"),
                    candles.get("count"),
                    candles.get("latest_mts"),
                    candles.get("high_median"),
                    candles.get("high_p75"),
                    candles.get("high_max"),
                    candles.get("close_latest"),
                ),
            )
        return cursor.lastrowid

    def record_candles(self, currency: str, period: int, timeframe: str, candles) -> int:
        """把 K 線一根一列寫進 `market_candles`，回傳這一次實際寫了幾根。

        **只寫「已存最新那根以後」的部分**：巡檢 600 秒一輪、K 線一小時一根，
        整個窗每輪重寫一次等於一天三萬多次 UPSERT 去講 24 根 K 的事。
        第一次會把整個窗都存下來（那是想要的），之後每輪通常只有 1～2 根。

        **邊界要含「等於」，不能只寫更新的**：已存的最新那根當時可能還在成形中，
        它的 high／close／volume 之後還會變大。少了這個等號，每根 K 都會被凍結在
        它剛出生那一刻的樣子——而 `high` 正是這個策略唯一在意的欄位（D035）。
        """
        if not candles:
            return 0

        row = self.connection.execute(
            """
            SELECT MAX(mts) AS latest FROM market_candles
            WHERE currency = ? AND period = ? AND timeframe = ?
            """,
            (currency, int(period), timeframe),
        ).fetchone()
        latest = row["latest"] if row and row["latest"] is not None else None

        pending = [
            candle
            for candle in candles
            if latest is None or int(candle["mts"]) >= latest
        ]
        if not pending:
            return 0

        stamp = now_iso()
        with self.connection:
            self.connection.executemany(
                """
                INSERT INTO market_candles
                    (currency, period, timeframe, mts, open, close, high, low,
                     volume, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(currency, period, timeframe, mts) DO UPDATE SET
                    open       = excluded.open,
                    close      = excluded.close,
                    high       = excluded.high,
                    low        = excluded.low,
                    volume     = excluded.volume,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        currency,
                        int(period),
                        timeframe,
                        int(candle["mts"]),
                        float(candle["open"]),
                        float(candle["close"]),
                        float(candle["high"]),
                        float(candle["low"]),
                        float(candle["volume"]),
                        stamp,
                    )
                    for candle in pending
                ],
            )
        return len(pending)

    def record_pricing_decision(
        self,
        currency: str,
        decision: Dict[str, Any],
        snapshot_id: Optional[int] = None,
    ) -> Optional[int]:
        """記下這一輪策略**怎麼選出那個價位的**（M1-b 決策落地）。

        `decision` 由策略的 `pricing_decision()` 產生——**策略層不碰 IO，
        這裡不碰策略**。傳進來的是純資料，序列化成 JSON 是儲存的細節，
        所以留在這一層（與 `market_snapshot.summarize_book()` 相反的分工是刻意的：
        那個模組的曲線點數本身就是摘要的一部分，而候選集不是）。

        回傳這一列的 id；`decision` 是空的就什麼都不做並回傳 `None`
        ——**「這一輪沒有評估過」不可以寫成一列什麼都是 NULL 的決策**。
        資金全部借出的日子裡餘額守門檻會讓 `choose_rate()` 一次都跑不到，
        那些輪次在這張表裡就該不存在，而不是存成一列空的（D041 的同一條界線：
        DB 裡多一列假資料沒有鄰行會反駁）。
        """
        if not decision:
            return None

        candidate_rates = decision.get("candidate_rates")
        candidate_effectives = decision.get("candidate_effectives")
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO pricing_decisions
                    (decided_at, currency, strategy, snapshot_id,
                     chosen_rate, chosen_effective, chosen_mean_hours,
                     chosen_median_hours, chosen_p75_hours, chosen_hits,
                     chosen_censored_ratio,
                     fastest_rate, fastest_mean_hours, fastest_effective,
                     candidate_count, candidate_rates_json, candidate_effectives_json,
                     window_hours, hold_hours_assumed, candle_count, candle_latest_mts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_iso(),
                    currency,
                    decision.get("strategy"),
                    snapshot_id,
                    decision["chosen_rate"],
                    decision["chosen_effective"],
                    decision.get("chosen_mean_hours"),
                    decision.get("chosen_median_hours"),
                    decision.get("chosen_p75_hours"),
                    decision.get("chosen_hits"),
                    decision.get("chosen_censored_ratio"),
                    decision.get("fastest_rate"),
                    decision.get("fastest_mean_hours"),
                    decision.get("fastest_effective"),
                    decision["candidate_count"],
                    # 分隔符去掉空白：110 個候選省下約 400 位元組，而這兩欄
                    # 是這張表最大的一項。
                    None if candidate_rates is None else json.dumps(
                        candidate_rates, separators=(",", ":")
                    ),
                    None if candidate_effectives is None else json.dumps(
                        candidate_effectives, separators=(",", ":")
                    ),
                    decision.get("window_hours"),
                    decision.get("hold_hours_assumed"),
                    decision.get("candle_count"),
                    decision.get("candle_latest_mts"),
                ),
            )
        return cursor.lastrowid

    def record_repost_comparison(
        self,
        currency: str,
        comparison: Dict[str, Any],
        snapshot_id: Optional[int] = None,
    ) -> Optional[int]:
        """記下這一輪「保住場上那張 vs 改掛本輪候選」的並排比較（M1-c 反事實落地）。

        `comparison` 由 `bot_engine._record_repost_comparison()` 組好——**引擎層算
        比較、這裡只負責寫**，與 `record_pricing_decision()` 同一種分工。

        `comparison` 是空的就什麼都不做並回傳 `None`：**場上沒有掛單的輪次，
        在這張表裡就該不存在**，而不是存成一列什麼都是 NULL 的比較（D043 的同一條
        界線）。這也是 D046 驗收條件 1 的字面意思。

        **允許 NULL 的欄位不要在這裡補預設值。** `live_effective` 算不出來就是
        算不出來（窗內命中不足），寫成 0 會讓它在事後的聚合裡冒充「實質年化為零」
        ——那比缺一格更糟。
        """
        if not comparison:
            return None

        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO repost_comparisons
                    (compared_at, currency, strategy, snapshot_id,
                     live_offer_id, live_offer_count, live_rate, live_amount,
                     live_period, live_idle_hours, live_forgone_usd,
                     live_forecast_mean_hours, live_forecast_median_hours,
                     live_forecast_p75_hours,
                     live_wait_hours, live_hits, live_censored_ratio, live_effective,
                     candidate_rate, candidate_amount, candidate_period,
                     candidate_wait_hours, candidate_hits, candidate_censored_ratio,
                     candidate_effective,
                     live_queue_ahead, live_queue_truncated,
                     candidate_queue_ahead, candidate_queue_truncated,
                     action, action_reason, hold_hours_assumed, window_hours)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_iso(),
                    currency,
                    comparison.get("strategy"),
                    snapshot_id,
                    # 型別對齊 `offer_wait_forecasts.offer_id`（TEXT），
                    # 兩張表要 JOIN 得起來才對得出「當初的預估 vs 後來每一輪的重估」。
                    None if comparison.get("live_offer_id") is None
                    else str(comparison["live_offer_id"]),
                    comparison["live_offer_count"],
                    comparison["live_rate"],
                    comparison.get("live_amount"),
                    comparison.get("live_period"),
                    comparison.get("live_idle_hours"),
                    comparison.get("live_forgone_usd"),
                    comparison.get("live_forecast_mean_hours"),
                    comparison.get("live_forecast_median_hours"),
                    comparison.get("live_forecast_p75_hours"),
                    comparison.get("live_wait_hours"),
                    comparison.get("live_hits"),
                    comparison.get("live_censored_ratio"),
                    comparison.get("live_effective"),
                    comparison["candidate_rate"],
                    comparison.get("candidate_amount"),
                    comparison.get("candidate_period"),
                    comparison.get("candidate_wait_hours"),
                    comparison.get("candidate_hits"),
                    comparison.get("candidate_censored_ratio"),
                    comparison.get("candidate_effective"),
                    comparison.get("live_queue_ahead"),
                    # SQLite 沒有布林；`None` 要保持 `None`（「答不出來」），
                    # 不可以被 `int()` 壓成 0（「沒有越界」）——那是兩件事。
                    None if comparison.get("live_queue_truncated") is None
                    else int(bool(comparison["live_queue_truncated"])),
                    comparison.get("candidate_queue_ahead"),
                    None if comparison.get("candidate_queue_truncated") is None
                    else int(bool(comparison["candidate_queue_truncated"])),
                    comparison["action"],
                    comparison.get("action_reason"),
                    comparison.get("hold_hours_assumed"),
                    comparison.get("window_hours"),
                ),
            )
        return cursor.lastrowid

    def upsert_daily_earning(
        self,
        date: str,
        currency: str,
        interest: float,
        principal_avg: Optional[float] = None,
    ) -> None:
        """寫入或累加某一天的收益。

        同一天重複寫入時 `interest` 採累加（同一天可能分多次補入帳），
        `principal_avg` 則直接覆蓋——平均值累加沒有意義。

        注意：目前尚無呼叫端。要填入真實數字需另外查 Bitfinex 的 ledger 端點
        取得利息入帳紀錄，該項已列入 TASKS.md，本輪只先備妥表結構與介面。
        """
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO earnings_daily (date, currency, interest, principal_avg, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(date, currency) DO UPDATE SET
                    interest      = earnings_daily.interest + excluded.interest,
                    principal_avg = COALESCE(excluded.principal_avg, earnings_daily.principal_avg),
                    updated_at    = excluded.updated_at
                """,
                (date, currency, float(interest), principal_avg, now_iso()),
            )

    def sync_positions(self, currency: str, positions) -> Dict[str, list]:
        """把交易所回報的已借出部位與 DB 對帳，回傳這一輪的變化。

        回傳 `{"opened": [...], "closed": [...]}`：
        - `opened`：DB 沒見過的部位 = **這一輪剛成交**
        - `closed`：DB 裡還開著、但交易所已經查不到 = **已還款或到期**

        這是整個「成交偵測」的核心。在它之前，錢借出去之後餘額歸零，
        日誌只會寫「可放貸金額不足，略過本輪」——**跟錢包本來就是空的一模一樣**
        （TASKS.md P2-1）。

        **交易所回報的是唯一真相**：只要某個 id 這次沒出現，就算它已經結束。
        不用「猜它是不是暫時查不到」——查詢失敗會在 `api` 層就拋例外，
        根本走不到這裡，所以能走到這裡的空清單就是真的空。
        """
        open_rows = {
            row["position_id"]: dict(row)
            for row in self.connection.execute(
                "SELECT * FROM funding_positions WHERE closed_at IS NULL AND currency = ?",
                (currency,),
            )
        }

        seen = set()
        opened = []
        for position in positions:
            position_id = str(position["id"])
            seen.add(position_id)
            if position_id in open_rows:
                continue
            opened.append(position)

        closed = [row for key, row in open_rows.items() if key not in seen]

        timestamp = now_iso()
        with self.connection:
            for position in opened:
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO funding_positions
                        (position_id, currency, amount, rate, period, kind,
                         opened_at, first_seen_at, closed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        str(position["id"]),
                        currency,
                        float(position["amount"]),
                        float(position["rate"]),
                        int(position["period"]),
                        position.get("kind", "credit"),
                        _millis_to_iso(position.get("opened_at")),
                        timestamp,
                    ),
                )
            for row in closed:
                self.connection.execute(
                    "UPDATE funding_positions SET closed_at = ? WHERE position_id = ?",
                    (timestamp, row["position_id"]),
                )
                # 回傳的 dict 是 UPDATE **之前**查出來的，`closed_at` 還留著 None。
                # 不補這一行，呼叫端拿到的「剛收回的部位」看起來會跟「還開著」
                # 一模一樣——`core/hold_time.py` 會據此把它判成右設限樣本，
                # 於是每一筆還款的當下都被講成「至少借了 N 小時（仍在生息中）」。
                row["closed_at"] = timestamp

        return {"opened": opened, "closed": closed}

    def open_positions(self, currency: str) -> list:
        """目前還在生息中的部位，供總曝險計算與每日摘要使用。"""
        return [
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM funding_positions WHERE closed_at IS NULL AND currency = ?",
                (currency,),
            )
        ]

    def all_positions(self, currency: str) -> list:
        """全部部位（含已結束），供持有時間量測使用（見 `core/hold_time.py`）。

        **刻意不在 SQL 裡過濾掉 `closed_at IS NULL`**：仍在借出中的部位是右設限
        樣本，量測需要知道它們存在才能算出「這份統計蓋掉了多少」。在這一層就
        濾掉，上層永遠不會發現自己只看到活得夠短的那些部位。
        """
        return [
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM funding_positions WHERE currency = ? "
                "ORDER BY COALESCE(opened_at, first_seen_at)",
                (currency,),
            )
        ]

    def save_state(
        self,
        last_frr: Optional[float] = None,
        last_action: Optional[str] = None,
        consecutive_failures: Optional[int] = None,
    ) -> None:
        """更新單列狀態表，同時把 `last_run_at` 當作心跳時間戳。

        `last_frr` 傳 None 時保留前一次的值（本輪抓不到 FRR，不代表要把
        「最後已知 FRR」洗掉）；`consecutive_failures` 同理，傳 None 就不動。
        """
        with self.connection:
            self.connection.execute(
                """
                UPDATE bot_state SET
                    last_run_at          = ?,
                    last_frr             = COALESCE(?, last_frr),
                    last_action          = COALESCE(?, last_action),
                    consecutive_failures = COALESCE(?, consecutive_failures)
                WHERE id = 1
                """,
                (now_iso(), last_frr, last_action, consecutive_failures),
            )

    def get_state(self) -> Optional[Dict[str, Any]]:
        """讀回目前狀態，供崩潰恢復與外部健康檢查使用。"""
        row = self.connection.execute(
            """
            SELECT last_run_at, last_frr, last_action, consecutive_failures
            FROM bot_state WHERE id = 1
            """
        ).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        self.connection.close()
