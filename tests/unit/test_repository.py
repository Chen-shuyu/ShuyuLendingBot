# -*- coding: utf-8 -*-
"""`db/repository.py` 與 `db/models.py` 的單元測試。

資料層是事後對帳的唯一依據：掛單成功、dry-run、失敗三種情形都必須留痕，
`bot_state` 則兼作心跳與健康檢查來源，寫壞了在容器裡不會有人發現。
"""

import sqlite3

import pytest

from db import models
from db.repository import (
    DEFAULT_DB_PATH,
    PROJECT_ROOT,
    STATUS_DRY_RUN,
    STATUS_FAILED,
    STATUS_SUBMITTED,
    Repository,
    resolve_db_path,
    utc_now,
)
from strategies.base import OfferPlan


def make_plan(amount=200.0, rate=0.0004, duration=2, currency="USD"):
    return OfferPlan(currency=currency, amount=amount, rate=rate, duration=duration)


def fetch_offers(repo):
    return [dict(row) for row in repo.connection.execute("SELECT * FROM loan_offers ORDER BY id")]


class TestInitialisation:
    def test_creates_parent_directory(self, tmp_path):
        db_path = tmp_path / "nested" / "deeper" / "lending.sqlite3"
        repo = Repository(str(db_path))
        assert db_path.exists()
        repo.close()

    def test_uses_wal_journal_mode(self, repository):
        mode = repository.connection.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    def test_synchronous_is_normal(self, repository):
        # NORMAL = 1；搭配 WAL 已足夠，最壞情況只失去最後幾筆寫入
        assert repository.connection.execute("PRAGMA synchronous").fetchone()[0] == 1

    def test_creates_all_three_tables(self, repository):
        names = {
            row[0]
            for row in repository.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"loan_offers", "earnings_daily", "bot_state"} <= names

    def test_creates_loan_offers_index(self, repository):
        names = {
            row[0]
            for row in repository.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        assert "idx_loan_offers_created_at" in names

    def test_reopening_is_idempotent(self, tmp_path):
        """重啟後重跑一次建表不能清掉既有資料。"""
        db_path = str(tmp_path / "lending.sqlite3")
        first = Repository(db_path)
        first.record_offer(make_plan(), {"status": STATUS_DRY_RUN})
        first.close()

        second = Repository(db_path)
        assert len(fetch_offers(second)) == 1
        second.close()

    def test_from_config_reads_database_path(self, tmp_path):
        db_path = tmp_path / "custom.sqlite3"
        repo = Repository.from_config({"database": {"path": str(db_path)}})
        assert repo.db_path == db_path
        repo.close()

    @pytest.mark.parametrize("config", [None, {}, {"database": None}, {"database": {}}])
    def test_from_config_falls_back_to_default_path(self, config, tmp_path, monkeypatch):
        # 只驗路徑怎麼算，不真的建立 Repository——建立會 mkdir + 開檔，
        # 而預設路徑指向真正的專案目錄，測試不該在那裡留下 DB 檔。
        monkeypatch.delenv("BFX_DB_PATH", raising=False)
        monkeypatch.chdir(tmp_path)
        database_config = (config or {}).get("database") or {}
        assert resolve_db_path(database_config.get("path")) == PROJECT_ROOT / DEFAULT_DB_PATH


class TestPathResolution:
    """相對路徑一律相對於專案根目錄，而不是誰在哪裡下的指令（TASKS.md A4）。

    這組測試釘的是「主程式與 `scripts/healthcheck.py` 算出同一個檔案位置」。
    兩邊不一致時的症狀非常難聯想：健康檢查永遠回報「尚未寫入任何心跳」，
    但機器人其實跑得好好的，只是把 DB 建在別的地方。
    """

    def test_relative_path_is_resolved_against_project_root(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BFX_DB_PATH", raising=False)
        monkeypatch.chdir(tmp_path)
        assert resolve_db_path("data/lending.sqlite3") == PROJECT_ROOT / "data" / "lending.sqlite3"

    def test_cwd_does_not_change_the_result(self, tmp_path, monkeypatch):
        # 這是修正前的實際行為：從別的目錄啟動，DB 就會建在別的地方
        monkeypatch.delenv("BFX_DB_PATH", raising=False)
        monkeypatch.chdir(tmp_path)
        from_elsewhere = resolve_db_path("data/lending.sqlite3")
        monkeypatch.chdir(PROJECT_ROOT)
        from_project = resolve_db_path("data/lending.sqlite3")
        assert from_elsewhere == from_project

    def test_absolute_path_is_left_alone(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BFX_DB_PATH", raising=False)
        absolute = tmp_path / "custom.sqlite3"
        assert resolve_db_path(str(absolute)) == absolute

    def test_env_var_wins_over_config(self, tmp_path, monkeypatch):
        # 與 healthcheck 的優先權一致；不一致的話設了環境變數就會兩邊分家
        override = tmp_path / "override.sqlite3"
        monkeypatch.setenv("BFX_DB_PATH", str(override))
        assert resolve_db_path("data/lending.sqlite3") == override

    def test_agrees_with_healthcheck_resolver(self, tmp_path, monkeypatch):
        """同一份設定，主程式與健康檢查必須算出同一個路徑。"""
        from scripts import healthcheck

        monkeypatch.delenv("BFX_DB_PATH", raising=False)
        monkeypatch.delenv("BFX_CONFIG", raising=False)
        monkeypatch.chdir(tmp_path)  # 從別的目錄啟動也要一致

        assert resolve_db_path("data/lending.sqlite3") == healthcheck.resolve_db_path(PROJECT_ROOT)

    def test_agrees_with_healthcheck_on_env_override(self, tmp_path, monkeypatch):
        override = tmp_path / "override.sqlite3"
        monkeypatch.setenv("BFX_DB_PATH", str(override))
        from scripts import healthcheck

        assert resolve_db_path("data/lending.sqlite3") == healthcheck.resolve_db_path(PROJECT_ROOT)


class TestRecordOffer:
    def test_records_submitted_offer_from_exchange_response(self, repository):
        plan = make_plan(amount=200.0, rate=0.0004, duration=2)
        repository.record_offer(
            plan,
            {"status": "submitted", "id": 123456, "symbol": "fUSD", "amount": 200.0,
             "rate": 0.0004, "period": 2},
        )
        row = fetch_offers(repository)[0]
        assert row["offer_id"] == "123456"
        assert row["status"] == STATUS_SUBMITTED
        assert row["detail"] == "fUSD"
        assert row["currency"] == "USD"

    def test_prefers_exchange_values_over_plan(self, repository):
        """部分成交或交易所調整時兩者會不同，落帳要以交易所回報為準。"""
        plan = make_plan(amount=200.0, rate=0.0004, duration=2)
        repository.record_offer(
            plan, {"status": "submitted", "id": 1, "amount": 180.5, "rate": 0.00055, "period": 30}
        )
        row = fetch_offers(repository)[0]
        assert (row["amount"], row["rate"], row["duration"]) == (180.5, 0.00055, 30)

    def test_falls_back_to_plan_when_response_lacks_fields(self, repository):
        plan = make_plan(amount=200.0, rate=0.0004, duration=2)
        repository.record_offer(plan, {"status": "submitted"})
        row = fetch_offers(repository)[0]
        assert (row["amount"], row["rate"], row["duration"]) == (200.0, 0.0004, 2)
        assert row["offer_id"] is None

    def test_dry_run_offer_is_recorded_without_exchange_id(self, repository):
        """dry-run 拿不到交易所 ID，但同樣要留痕，才能不連實盤就驗證資料層。"""
        plan = make_plan()
        repository.record_offer(
            plan,
            {"status": "dry_run", "currency": "USD", "amount": 200.0, "rate": 0.0004, "duration": 2},
        )
        row = fetch_offers(repository)[0]
        assert row["status"] == STATUS_DRY_RUN
        assert row["offer_id"] is None

    def test_missing_status_defaults_to_submitted(self, repository):
        repository.record_offer(make_plan(), {"id": 7})
        assert fetch_offers(repository)[0]["status"] == STATUS_SUBMITTED

    def test_created_at_is_utc_iso_string(self, repository):
        repository.record_offer(make_plan(), {"status": STATUS_DRY_RUN})
        created_at = fetch_offers(repository)[0]["created_at"]
        assert created_at.endswith("+00:00")


class TestRecordOfferFailure:
    def test_records_failure_with_reason(self, repository):
        plan = make_plan(amount=150.0, rate=0.0005, duration=30)
        repository.record_offer_failure(plan, "查詢逾時")
        row = fetch_offers(repository)[0]
        assert row["status"] == STATUS_FAILED
        assert row["offer_id"] is None
        assert row["detail"] == "查詢逾時"
        assert (row["amount"], row["rate"], row["duration"]) == (150.0, 0.0005, 30)

    def test_partial_round_keeps_both_success_and_failure(self, repository):
        """同一輪第一筆成功、第二筆失敗時，錢已經出去了一部分，兩筆都要看得到。"""
        repository.record_offer(make_plan(amount=100.0), {"status": "submitted", "id": 1})
        repository.record_offer_failure(make_plan(amount=200.0), "交易所拒單")
        statuses = [row["status"] for row in fetch_offers(repository)]
        assert statuses == [STATUS_SUBMITTED, STATUS_FAILED]


class TestEarnings:
    def test_inserts_new_row(self, repository):
        repository.upsert_daily_earning("2026-08-01", "USD", 1.25, 500.0)
        row = repository.connection.execute("SELECT * FROM earnings_daily").fetchone()
        assert (row["interest"], row["principal_avg"]) == (1.25, 500.0)

    def test_interest_accumulates_on_conflict(self, repository):
        """同一天可能分多次補入帳，利息採累加。"""
        repository.upsert_daily_earning("2026-08-01", "USD", 1.25, 500.0)
        repository.upsert_daily_earning("2026-08-01", "USD", 0.75, 600.0)
        row = repository.connection.execute("SELECT * FROM earnings_daily").fetchone()
        assert row["interest"] == pytest.approx(2.0)
        assert row["principal_avg"] == 600.0  # 平均值累加沒有意義，直接覆蓋

    def test_null_principal_keeps_previous_value(self, repository):
        repository.upsert_daily_earning("2026-08-01", "USD", 1.0, 500.0)
        repository.upsert_daily_earning("2026-08-01", "USD", 1.0, None)
        row = repository.connection.execute("SELECT * FROM earnings_daily").fetchone()
        assert row["principal_avg"] == 500.0

    def test_principal_avg_is_optional(self, repository):
        """回歸測試：`principal_avg` 曾被宣告成 NOT NULL，導致不傳它就直接 IntegrityError。

        介面約定是「傳 None 代表本次不更新平均本金」，靠 ON CONFLICT 的 COALESCE 實現；
        但 NOT NULL 會在衝突解析之前就先擋下，等於整條 None 路徑從來沒有能用過。
        接 Bitfinex ledger 資料源時（TASKS.md）第一個呼叫就會撞到。
        """
        repository.upsert_daily_earning("2026-08-01", "USD", 1.25)
        row = repository.connection.execute("SELECT * FROM earnings_daily").fetchone()
        assert row["interest"] == pytest.approx(1.25)
        assert row["principal_avg"] is None

    def test_different_dates_and_currencies_are_separate_rows(self, repository):
        repository.upsert_daily_earning("2026-08-01", "USD", 1.0)
        repository.upsert_daily_earning("2026-08-02", "USD", 1.0)
        repository.upsert_daily_earning("2026-08-01", "UST", 1.0)
        count = repository.connection.execute("SELECT COUNT(*) FROM earnings_daily").fetchone()[0]
        assert count == 3


class TestBotState:
    def test_initial_row_exists(self, repository):
        state = repository.get_state()
        assert state is not None
        assert state["consecutive_failures"] == 0
        assert state["last_run_at"] is None

    def test_save_state_updates_heartbeat(self, repository):
        repository.save_state(last_action="測試")
        assert repository.get_state()["last_run_at"] is not None

    def test_none_values_keep_previous(self, repository):
        """本輪抓不到 FRR，不代表要把「最後已知 FRR」洗掉。"""
        repository.save_state(last_frr=0.0004, last_action="掛單完成", consecutive_failures=2)
        repository.save_state(last_action="FRR 無效，略過本輪")
        state = repository.get_state()
        assert state["last_frr"] == 0.0004
        assert state["consecutive_failures"] == 2
        assert state["last_action"] == "FRR 無效，略過本輪"

    def test_zero_failures_is_written_not_ignored(self, repository):
        """0 是有效值，不能被 COALESCE 當成「沒傳」而保留舊值。"""
        repository.save_state(consecutive_failures=3)
        repository.save_state(consecutive_failures=0)
        assert repository.get_state()["consecutive_failures"] == 0

    def test_heartbeat_moves_forward(self, repository, monkeypatch):
        repository.save_state(last_action="第一輪")
        first = repository.get_state()["last_run_at"]
        monkeypatch.setattr("db.repository.utc_now", lambda: "2099-01-01T00:00:00+00:00")
        repository.save_state(last_action="第二輪")
        assert repository.get_state()["last_run_at"] != first

    def test_table_structurally_allows_only_one_row(self, repository):
        """單列限制寫在 CHECK 條件裡，不必靠程式自律。"""
        with pytest.raises(sqlite3.IntegrityError):
            with repository.connection:
                repository.connection.execute("INSERT INTO bot_state (id) VALUES (2)")

    def test_state_survives_reopen(self, tmp_path):
        """崩潰重啟後要讀得回上次狀態，這正是 healthcheck 的資料來源。"""
        db_path = str(tmp_path / "lending.sqlite3")
        first = Repository(db_path)
        first.save_state(last_frr=0.00035, last_action="掛出 2 筆掛單", consecutive_failures=1)
        first.close()

        second = Repository(db_path)
        state = second.get_state()
        assert state["last_frr"] == 0.00035
        assert state["consecutive_failures"] == 1
        second.close()


class TestModels:
    def test_all_statements_are_idempotent(self, repository):
        """每次啟動都會重跑一次，不可因為表已存在就炸掉。"""
        with repository.connection:
            for statement in models.ALL_STATEMENTS:
                repository.connection.execute(statement)
        count = repository.connection.execute("SELECT COUNT(*) FROM bot_state").fetchone()[0]
        assert count == 1


class TestUtcNow:
    def test_returns_second_precision_utc(self):
        stamp = utc_now()
        assert stamp.endswith("+00:00")
        assert "." not in stamp  # timespec="seconds"，不帶微秒
