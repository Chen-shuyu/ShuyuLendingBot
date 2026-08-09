# -*- coding: utf-8 -*-
"""SQLite 讀寫封裝（WAL 模式）。

採「單一寫入者（主迴圈）+ 多唯讀查詢（未來報表 / 狀態頁）」模型，天然避免
寫入衝突；WAL 則讓讀取不會被寫入擋住。主迴圈是單執行緒，因此整支程式共用
一條連線即可。
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from db import models

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


def utc_now() -> str:
    """目前時間的 UTC ISO 8601 字串，秒為精度。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Repository:
    """掛單流水、每日收益、機器人狀態的持久化封裝。"""

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
                    utc_now(),
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
                    utc_now(),
                ),
            )

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
                (date, currency, float(interest), principal_avg, utc_now()),
            )

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
                (utc_now(), last_frr, last_action, consecutive_failures),
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
