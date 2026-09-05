# -*- coding: utf-8 -*-
"""`db/repository.py` 與 `db/models.py` 的單元測試。

資料層是事後對帳的唯一依據：掛單成功、dry-run、失敗三種情形都必須留痕，
`bot_state` 則兼作心跳與健康檢查來源，寫壞了在容器裡不會有人發現。
"""

import sqlite3
from datetime import datetime

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
    now_iso,
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

    def test_creates_every_table(self, repository):
        names = {
            row[0]
            for row in repository.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"loan_offers", "earnings_daily", "funding_positions", "bot_state"} <= names

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

    def test_created_at_is_aware_iso_string_in_project_timezone(self, repository):
        repository.record_offer(make_plan(), {"status": STATUS_DRY_RUN})
        created_at = fetch_offers(repository)[0]["created_at"]
        assert datetime.fromisoformat(created_at).tzinfo is not None
        assert created_at.endswith("+08:00")


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
        monkeypatch.setattr("db.repository.now_iso", lambda: "2099-01-01T00:00:00+00:00")
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


class TestNowIso:
    def test_returns_second_precision_in_project_timezone(self):
        stamp = now_iso()
        assert stamp.endswith("+08:00")
        assert "." not in stamp  # timespec="seconds"，不帶微秒

    def test_is_timezone_aware(self):
        """帶時區是硬性要求：naive 值會讓 healthcheck 的相減直接拋 TypeError。"""
        assert datetime.fromisoformat(now_iso()).tzinfo is not None

    def test_follows_timezone_env_override(self, monkeypatch):
        monkeypatch.setenv("BFX_TIMEZONE", "UTC")
        assert now_iso().endswith("+00:00")

    def test_falls_back_to_utc_when_timezone_unknown(self, monkeypatch):
        """時區資料查不到不該讓機器人停擺——退回 UTC，而 +0000 偏移會讓人看得出來。"""
        monkeypatch.setenv("BFX_TIMEZONE", "Mars/Olympus_Mons")
        assert now_iso().endswith("+00:00")


class TestSyncPositions:
    """成交偵測的核心（TASKS.md P2-1）。

    在它之前，錢借出去之後餘額歸零，機器人只會寫一句「可放貸金額不足，略過本輪」
    ——跟錢包本來就是空的完全無法區分。
    """

    @staticmethod
    def position(position_id="1", amount=160.0, rate=0.00025, period=2, kind="credit",
                 opened_at=1786872920000):
        return {
            "id": position_id,
            "amount": amount,
            "rate": rate,
            "period": period,
            "kind": kind,
            "opened_at": opened_at,
        }

    def test_first_sighting_counts_as_opened(self, repository):
        changes = repository.sync_positions("USD", [self.position()])

        assert [item["id"] for item in changes["opened"]] == ["1"]
        assert changes["closed"] == []

    def test_same_position_is_not_reported_twice(self, repository):
        repository.sync_positions("USD", [self.position()])
        changes = repository.sync_positions("USD", [self.position()])

        assert changes["opened"] == []
        assert changes["closed"] == []

    def test_disappearing_position_counts_as_closed(self, repository):
        repository.sync_positions("USD", [self.position()])
        changes = repository.sync_positions("USD", [])

        assert [row["position_id"] for row in changes["closed"]] == ["1"]

    def test_closed_position_is_not_reported_again(self, repository):
        repository.sync_positions("USD", [self.position()])
        repository.sync_positions("USD", [])
        changes = repository.sync_positions("USD", [])

        assert changes["closed"] == []

    def test_reopening_the_database_does_not_replay_old_fills(self, repository, tmp_path):
        """**重啟不能把場上既有部位當成新成交。**

        狀態只放記憶體的話，每次部署都會推一輪假的成交通知——
        而這個管道只要騙過人一次，之後就不會再被相信（同 D023、D029 的判斷）。
        """
        repository.sync_positions("USD", [self.position()])

        from db.repository import Repository

        reopened = Repository(str(repository.db_path))
        changes = reopened.sync_positions("USD", [self.position()])
        reopened.close()

        assert changes["opened"] == []

    def test_records_the_position_details(self, repository):
        repository.sync_positions("USD", [self.position(amount=160.5, rate=0.000273, period=7)])
        row = dict(
            repository.connection.execute("SELECT * FROM funding_positions").fetchone()
        )

        assert row["amount"] == 160.5
        assert row["rate"] == 0.000273
        assert row["period"] == 7
        assert row["kind"] == "credit"
        assert row["closed_at"] is None

    def test_opened_at_is_converted_to_local_iso(self, repository):
        repository.sync_positions("USD", [self.position(opened_at=1786872920000)])
        row = repository.connection.execute(
            "SELECT opened_at FROM funding_positions"
        ).fetchone()

        # 帶時區偏移，與專案其他時間戳一致（D028）
        assert row["opened_at"].endswith("+08:00") or row["opened_at"].endswith("+00:00")

    def test_unparsable_opened_at_does_not_break_the_row(self, repository):
        """時間轉不動就留 None——為了一個輔助欄位讓整輪失敗並不划算。"""
        repository.sync_positions("USD", [self.position(opened_at="not-a-timestamp")])
        row = repository.connection.execute(
            "SELECT position_id, opened_at FROM funding_positions"
        ).fetchone()

        assert row["position_id"] == "1"
        assert row["opened_at"] is None

    def test_open_positions_lists_only_live_ones(self, repository):
        repository.sync_positions("USD", [self.position("1"), self.position("2")])
        repository.sync_positions("USD", [self.position("2")])

        assert [row["position_id"] for row in repository.open_positions("USD")] == ["2"]

    def test_currencies_do_not_interfere(self, repository):
        repository.sync_positions("USD", [self.position("1")])
        changes = repository.sync_positions("EUR", [self.position("2")])

        # 查 EUR 時不該把 USD 的部位判成「消失了」
        assert changes["closed"] == []
        assert len(repository.open_positions("USD")) == 1


class TestWaitForecasts:
    """掛單當下的等待預估（D038）。"""

    def forecast(self, **overrides):
        base = {
            "rate": 0.000268,
            "mean_hours": 6.0,
            "median_hours": 3.5,
            "p75_hours": 12.0,
            "hits": 54,
            "censored_ratio": 0.0,
            "window_hours": 168,
        }
        base.update(overrides)
        return base

    def test_存進去再取出來(self, repository):
        repository.record_wait_forecast("5084375241", self.forecast())
        saved = repository.get_wait_forecast("5084375241")
        assert saved["mean_hours"] == 6.0
        assert saved["median_hours"] == 3.5
        assert saved["p75_hours"] == 12.0
        assert saved["hits"] == 54
        assert saved["window_hours"] == 168

    def test_offer_id_數字與字串是同一張單(self, repository):
        """交易所回的 id 有時是整數、有時是字串，兩邊要對得起來才校準得了。"""
        repository.record_wait_forecast(5084375241, self.forecast())
        assert repository.get_wait_forecast("5084375241") is not None

    def test_沒有預估時回None而不是空dict(self, repository):
        """回 `None` 是正常情況：這張表 2026-08-19 才加，之前的單本來就沒有。"""
        assert repository.get_wait_forecast("不存在") is None
        assert repository.get_wait_forecast(None) is None

    def test_沒有offer_id就不落帳(self, repository):
        """dry-run 或交易所沒回 id 時對不起來，落一列只會讓校準資料變髒。"""
        repository.record_wait_forecast(None, self.forecast())
        rows = repository.connection.execute("SELECT COUNT(*) FROM offer_wait_forecasts").fetchone()
        assert rows[0] == 0

    def test_同一個id再寫一次以新的為準(self, repository):
        repository.record_wait_forecast("7", self.forecast(mean_hours=6.0))
        repository.record_wait_forecast("7", self.forecast(mean_hours=20.0))
        assert repository.get_wait_forecast("7")["mean_hours"] == 20.0
        rows = repository.connection.execute("SELECT COUNT(*) FROM offer_wait_forecasts").fetchone()
        assert rows[0] == 1


class Test持有時間量測要用的部位查詢:
    """`all_positions()` 與 `sync_positions()` 回傳值的 `closed_at`（見 D040）。"""

    def position(self, position_id="464242253", rate=0.00026027, amount=344.41):
        return {
            "id": position_id,
            "amount": amount,
            "rate": rate,
            "period": 2,
            "kind": "credit",
            "opened_at": 1_787_063_460_000,
        }

    def test_剛收回的部位在回傳值裡就帶著closed_at(self, repository):
        """**這是量測的前提**：回傳的 dict 是 UPDATE 之前查出來的。

        不補上 `closed_at`，呼叫端拿到的「剛收回的部位」看起來會跟「還開著」
        一模一樣，`core/hold_time.py` 會把它判成右設限樣本，於是每一筆還款的
        當下都被講成「至少借了 N 小時（仍在生息中）」——**講的是還款，
        話卻說成還在生息**。
        """
        repository.sync_positions("USD", [self.position()])
        changes = repository.sync_positions("USD", [])

        assert len(changes["closed"]) == 1
        assert changes["closed"][0]["closed_at"] is not None

    def test_回傳的closed_at與寫進DB的是同一個值(self, repository):
        repository.sync_positions("USD", [self.position()])
        changes = repository.sync_positions("USD", [])

        stored = repository.connection.execute(
            "SELECT closed_at FROM funding_positions WHERE position_id = ?",
            ("464242253",),
        ).fetchone()
        assert changes["closed"][0]["closed_at"] == stored["closed_at"]

    def test_all_positions含已結束的部位(self, repository):
        """**刻意不在 SQL 裡濾掉還開著的**：右設限樣本要看得見才算得出蓋掉多少。"""
        repository.sync_positions("USD", [self.position("a"), self.position("b")])
        repository.sync_positions("USD", [self.position("b")])

        rows = repository.all_positions("USD")

        assert len(rows) == 2
        assert sum(1 for row in rows if row["closed_at"] is not None) == 1
        assert sum(1 for row in rows if row["closed_at"] is None) == 1

    def test_all_positions只回該幣別(self, repository):
        repository.sync_positions("USD", [self.position("usd-1")])
        repository.sync_positions("UST", [self.position("ust-1")])

        assert [row["position_id"] for row in repository.all_positions("USD")] == ["usd-1"]

    def test_open_positions仍然只回還開著的(self, repository):
        """改動不能波及既有呼叫端：總曝險計算靠的就是這個只回未結束的行為。"""
        repository.sync_positions("USD", [self.position("a"), self.position("b")])
        repository.sync_positions("USD", [self.position("b")])

        assert [row["position_id"] for row in repository.open_positions("USD")] == ["b"]


def make_candle(mts, high=0.0003, close=0.00029, low=0.0001, open_=0.0002, volume=1000.0):
    return {"mts": mts, "open": open_, "close": close, "high": high, "low": low,
            "volume": volume}


class TestMarketSnapshot:
    """`market_snapshots` 的寫入（M1 市場資料落地）。

    這張表的資料**存下去就回不去**，而 M2 回測工具會拿它當事實。
    所以這裡驗的是「沒觀測到的東西有沒有留成 NULL」——用 0 填會讓一段
    沒有資料的期間被讀成一段市場死掉的期間，而那種錯誤沒有鄰行可以拆穿。
    """

    @staticmethod
    def rows(repository):
        return repository.connection.execute(
            "SELECT * FROM market_snapshots ORDER BY id"
        ).fetchall()

    def test_什麼都沒觀測到就不寫列(self, repository):
        repository.record_market_snapshot("USD", None)

        assert self.rows(repository) == []

    def test_只有FRR也要留下(self, repository):
        """`bot_state.last_frr` 是單列表、每輪覆蓋，
        **FRR 的歷史除了這裡沒有第二個地方留得下來**。"""
        repository.record_market_snapshot("USD", 0.00031)

        rows = self.rows(repository)
        assert len(rows) == 1
        assert rows[0]["frr"] == 0.00031

    def test_沒觀測到的欄位是NULL不是零(self, repository):
        repository.record_market_snapshot("USD", 0.0002, book={"levels": 3})

        row = self.rows(repository)[0]
        assert row["book_levels"] == 3
        assert row["trade_count"] is None
        assert row["candle_count"] is None

    def test_截斷旗標存成整數(self, repository):
        """存 0/1 而不是 'true'/'false'，這樣 `WHERE book_truncated = 1`
        這種查詢才不必記得引號。"""
        repository.record_market_snapshot("USD", 0.0002, book={"truncated": True})
        repository.record_market_snapshot("USD", 0.0002, book={"truncated": False})

        assert [row["book_truncated"] for row in self.rows(repository)] == [1, 0]

    def test_每輪各留一列(self, repository):
        for _ in range(3):
            repository.record_market_snapshot("USD", 0.0002, trades={"count": 5})

        assert len(self.rows(repository)) == 3

    def test_回傳寫進去那一列的id(self, repository):
        """M1-b 的決策要指得回本輪的市場長相。**用時間去 JOIN 是行不通的**
        ——同一秒可能有兩列，而決策比快照晚幾百毫秒才產生。"""
        first = repository.record_market_snapshot("USD", 0.0002, trades={"count": 5})
        second = repository.record_market_snapshot("USD", 0.0003, trades={"count": 6})

        assert [row["id"] for row in self.rows(repository)] == [first, second]
        assert first != second

    def test_沒寫列的時候回None而不是上一列的id(self, repository):
        """回傳上一列的 id 的話，決策會指到別一輪的市場長相上
        ——**而那種錯誤看起來完全正常**。"""
        repository.record_market_snapshot("USD", 0.0002, trades={"count": 5})

        assert repository.record_market_snapshot("USD", None) is None


class TestMarketCandles:
    """`market_candles` 的 UPSERT（M1）。

    K 線每小時才換一根、巡檢 600 秒一輪，所以這裡驗的是**寫入量**：
    整個窗每輪重寫一次等於一天三萬多次 UPSERT 去講 24 根 K 的事。
    """

    @staticmethod
    def stored(repository):
        return repository.connection.execute(
            "SELECT * FROM market_candles ORDER BY mts"
        ).fetchall()

    def test_第一次把整個窗都存下來(self, repository):
        candles = [make_candle(index * 3_600_000) for index in range(5)]

        assert repository.record_candles("USD", 2, "1h", candles) == 5
        assert len(self.stored(repository)) == 5

    def test_第二次只寫新的那幾根(self, repository):
        candles = [make_candle(index * 3_600_000) for index in range(5)]
        repository.record_candles("USD", 2, "1h", candles)

        # 下一輪多了一根，前面四根不該被重寫。
        extended = candles + [make_candle(5 * 3_600_000)]
        written = repository.record_candles("USD", 2, "1h", extended)

        # 已存最新那根 ＋ 新的那根 = 2（等號是刻意的，理由見下一條測試）
        assert written == 2
        assert len(self.stored(repository)) == 6

    def test_最新那根還在成形就要跟著更新(self, repository):
        """**邊界要含等號。** 已存的最新那根當時可能還在成形中，
        它的 high 之後還會變大——而 `high` 正是這個策略唯一在意的欄位（D035）。
        少了等號，每根 K 都會被凍結在它剛出生那一刻的樣子。"""
        repository.record_candles("USD", 2, "1h", [make_candle(0, high=0.0002)])
        repository.record_candles("USD", 2, "1h", [make_candle(0, high=0.0009)])

        rows = self.stored(repository)
        assert len(rows) == 1
        assert rows[0]["high"] == 0.0009

    def test_沒有新的就一根都不寫(self, repository):
        candles = [make_candle(index * 3_600_000) for index in range(3)]
        repository.record_candles("USD", 2, "1h", candles)

        # 同一份資料再送一次：只有最新那根需要覆蓋。
        assert repository.record_candles("USD", 2, "1h", candles[:-1]) == 0

    def test_不同天期互不干擾(self, repository):
        """`p{period}` 這一段不能省：不指定天期會把所有天期混在一起，
        而 2 天期佔了 86% 的供給、價格結構與長天期不同（D030）。"""
        repository.record_candles("USD", 2, "1h", [make_candle(0, high=0.0002)])
        repository.record_candles("USD", 30, "1h", [make_candle(0, high=0.0004)])

        rows = self.stored(repository)
        assert len(rows) == 2
        assert {row["period"]: row["high"] for row in rows} == {2: 0.0002, 30: 0.0004}

    def test_空清單不炸(self, repository):
        assert repository.record_candles("USD", 2, "1h", []) == 0


class TestPricingDecisions:
    """`pricing_decisions` 的寫入（M1-b 決策落地）。

    **這張表跟 `market_snapshots` 的差別在於它存的是判斷，不是觀測。**
    D041 當初把它擋在驗收後面，理由是「日誌印錯還有鄰行可以拆穿，
    DB 裡多一列假資料沒有鄰行會反駁」——所以這裡驗的第一件事是
    **沒評估過的輪次不可以留下任何一列**。
    """

    @staticmethod
    def rows(repository):
        return repository.connection.execute(
            "SELECT * FROM pricing_decisions ORDER BY id"
        ).fetchall()

    @staticmethod
    def decision(**overrides):
        base = {
            "strategy": "ExpectedValueStrategy",
            "chosen_rate": 0.00026027,
            "chosen_effective": 0.00024,
            "chosen_mean_hours": 6.1,
            "chosen_median_hours": 3.5,
            "chosen_p75_hours": 10.0,
            "chosen_hits": 53,
            "chosen_censored_ratio": 0.06,
            "fastest_rate": 0.00015,
            "fastest_mean_hours": 0.5,
            "fastest_effective": 0.00014844,
            "candidate_count": 3,
            "candidate_rates": [0.00015, 0.00021918, 0.00026027],
            "candidate_effectives": [0.00014844, 0.00021, 0.00024],
            "window_hours": 168,
            "hold_hours_assumed": 48.0,
            "candle_count": 168,
            "candle_latest_mts": 1_787_576_400_000,
        }
        base.update(overrides)
        return base

    def test_沒評估過就不寫列(self, repository):
        """資金全借出的日子裡餘額守門檻會讓 `choose_rate()` 一次都跑不到。
        那些輪次在這張表裡就該不存在，**而不是存成一列什麼都是 NULL 的決策**
        ——後者會讓「這段期間評估過幾次」這個數字說謊。"""
        assert repository.record_pricing_decision("USD", {}) is None
        assert repository.record_pricing_decision("USD", None) is None

        assert self.rows(repository) == []

    def test_選中的價位與統計量都存下來(self, repository):
        repository.record_pricing_decision("USD", self.decision())

        row = self.rows(repository)[0]
        assert row["chosen_rate"] == 0.00026027
        assert row["chosen_effective"] == 0.00024
        assert row["chosen_median_hours"] == 3.5
        assert row["chosen_hits"] == 53
        assert row["strategy"] == "ExpectedValueStrategy"
        assert row["hold_hours_assumed"] == 48.0

    def test_候選集兩排讀回來還是原來的數字(self, repository):
        """JSON 是儲存的細節，讀回來要跟存進去的一模一樣。
        **浮點數在這裡不可以四捨五入**：候選價位就是量化過的日利率，
        差一個小數位就是另一個價位。"""
        import json

        sent = self.decision()
        repository.record_pricing_decision("USD", sent)

        row = self.rows(repository)[0]
        assert json.loads(row["candidate_rates_json"]) == sent["candidate_rates"]
        assert json.loads(row["candidate_effectives_json"]) == sent["candidate_effectives"]

    def test_候選集用緊湊分隔符(self, repository):
        """這兩欄是這張表最大的一項，110 個候選省下約 400 位元組。"""
        repository.record_pricing_decision("USD", self.decision())

        assert ", " not in self.rows(repository)[0]["candidate_rates_json"]

    def test_接得回本輪的市場快照(self, repository):
        snapshot_id = repository.record_market_snapshot("USD", 0.0003, trades={"count": 5})
        repository.record_pricing_decision("USD", self.decision(), snapshot_id)

        assert self.rows(repository)[0]["snapshot_id"] == snapshot_id

    def test_快照寫不進去時決策照樣落得下來(self, repository):
        """**一個看得見的缺口不該變成兩個。** `snapshot_id` 允許 NULL，
        快照那邊失敗時決策仍然要留下——決策才是這張表的主體。"""
        assert repository.record_pricing_decision("USD", self.decision(), None) is not None

        assert self.rows(repository)[0]["snapshot_id"] is None

    def test_每輪各留一列(self, repository):
        for rate in (0.00026027, 0.00024971, 0.00021918):
            repository.record_pricing_decision("USD", self.decision(chosen_rate=rate))

        assert [row["chosen_rate"] for row in self.rows(repository)] == [
            0.00026027,
            0.00024971,
            0.00021918,
        ]


class TestRepostComparisons:
    """`repost_comparisons` 的寫入（M1-c 反事實落地，D046）。

    **這張表存的是「沒發生的那條路」**，而沒發生的事沒有鄰行可以拆穿它
    ——所以這裡驗的第一件事跟 `pricing_decisions` 一樣：**場上沒有掛單的輪次
    不可以留下任何一列**（D046 驗收條件 1 的字面意思）。

    第二件事是 **NULL 要保持 NULL**：`live_effective` 算不出來就是算不出來，
    補成 0 會讓它在事後的聚合裡冒充「實質年化為零」，那比缺一格更糟。
    """

    @staticmethod
    def rows(repository):
        return repository.connection.execute(
            "SELECT * FROM repost_comparisons ORDER BY id"
        ).fetchall()

    @staticmethod
    def comparison(**overrides):
        base = {
            "strategy": "ExpectedValueStrategy",
            "live_offer_id": 464505426,
            "live_offer_count": 1,
            "live_rate": 0.00024971,
            "live_amount": 344.72,
            "live_period": 2,
            "live_idle_hours": 2.4,
            "live_forgone_usd": 0.0086,
            "live_forecast_mean_hours": 7.09,
            "live_forecast_median_hours": 3.5,
            "live_forecast_p75_hours": 10.0,
            "live_wait_hours": 8.04,
            "live_hits": 66,
            "live_censored_ratio": 0.0,
            "live_effective": 0.00021409,
            "candidate_rate": 0.00027,
            "candidate_amount": 344.72,
            "candidate_period": 2,
            "candidate_wait_hours": 14.2,
            "candidate_hits": 21,
            "candidate_censored_ratio": 0.02,
            "candidate_effective": 0.00020876,
            "live_queue_ahead": 5_381_114.0,
            "live_queue_truncated": True,
            "candidate_queue_ahead": 5_381_114.0,
            "candidate_queue_truncated": True,
            "action": "hold_matched",
            "action_reason": "掛單條件與場上一致（利率容差 2%）",
            "hold_hours_assumed": 48.0,
            "window_hours": 168,
        }
        base.update(overrides)
        return base

    def test_空的比較不留任何一列(self, repository):
        """場上沒有掛單的輪次，在這張表裡就該不存在——**而不是存成一列
        什麼都是 NULL 的比較**（D043 的同一條界線）。"""
        assert repository.record_repost_comparison("USD", {}) is None
        assert repository.record_repost_comparison("USD", None) is None
        assert self.rows(repository) == []

    def test_寫得進去也讀得回來(self, repository):
        row_id = repository.record_repost_comparison("USD", self.comparison(), 327)

        rows = self.rows(repository)
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["id"] == row_id
        assert row["snapshot_id"] == 327, "指得回本輪的市場長相"
        assert row["live_rate"] == pytest.approx(0.00024971)
        assert row["candidate_rate"] == pytest.approx(0.00027)
        assert row["action"] == "hold_matched"

    def test_offer_id存成字串才對得上等待預估那張表(self, repository):
        """`offer_wait_forecasts.offer_id` 是 TEXT。型別不一致的話
        「當初的預估 vs 後來每一輪的重估」這個 JOIN 會安靜地回空集合。"""
        repository.record_repost_comparison("USD", self.comparison())

        row = dict(self.rows(repository)[0])
        assert row["live_offer_id"] == "464505426"

        repository.record_wait_forecast(
            464505426,
            {"rate": 0.00024971, "mean_hours": 7.09, "median_hours": 3.5,
             "p75_hours": 10.0, "hits": 66, "censored_ratio": 0.0, "window_hours": 168},
        )
        joined = repository.connection.execute(
            "SELECT f.mean_hours FROM repost_comparisons c "
            "JOIN offer_wait_forecasts f ON f.offer_id = c.live_offer_id"
        ).fetchall()
        assert len(joined) == 1, "兩張表要 JOIN 得起來"

    def test_算不出實質年化的那一列照樣要寫而且NULL保持NULL(self, repository):
        """**這是 08-19 那張單的形狀**：掛 9.78% 在場 34.2 小時沒成交，
        窗內命中不足，算不出實質年化。

        那一列是最想留住的一列（D046 驗收條件 4 要靠它），而
        `live_effective` 補成 0 會讓它在事後聚合時冒充「賺 0%」。
        """
        repository.record_repost_comparison(
            "USD",
            self.comparison(live_effective=None, live_wait_hours=None,
                            live_censored_ratio=None, live_hits=0),
        )

        row = dict(self.rows(repository)[0])
        assert row["live_effective"] is None
        assert row["live_wait_hours"] is None
        assert row["live_hits"] == 0, "『一次都沒掃到』是 0，不是 NULL"

    def test_越界旗標答不出來時不可以被壓成沒越界(self, repository):
        """`None`（拿不到簿子，答不出來）與 `False`（問過了，沒越界）
        是兩件事。`int()` 會把前者壓成 0，於是事後看起來像「量過而且沒越界」
        ——D026 靜默失效的同一族。"""
        repository.record_repost_comparison(
            "USD",
            self.comparison(live_queue_truncated=None, live_queue_ahead=None,
                            candidate_queue_truncated=False),
        )

        row = dict(self.rows(repository)[0])
        assert row["live_queue_truncated"] is None
        assert row["candidate_queue_truncated"] == 0

    def test_三種action都落得下去(self, repository):
        for action in ("hold_matched", "hold_cheaper_not_worth_it", "repost"):
            repository.record_repost_comparison("USD", self.comparison(action=action))

        assert [dict(r)["action"] for r in self.rows(repository)] == [
            "hold_matched", "hold_cheaper_not_worth_it", "repost"
        ]

    def test_往上調價那一列的理由是空的(self, repository):
        """**刻意的**：往上調價沒有判準可寫，那正是 D046 要記下來的事。
        硬填一句理由會讓事後看的人以為有東西判斷過。"""
        repository.record_repost_comparison(
            "USD", self.comparison(action="repost", action_reason=None)
        )

        assert dict(self.rows(repository)[0])["action_reason"] is None


class TestD064既有資料庫要補上新欄位:
    """🔴 **`CREATE TABLE IF NOT EXISTS` 對已經存在的表什麼都不做。**

    所以新欄位只會出現在全新的資料庫裡，而正式環境那個從 2026-08-01 跑到現在
    的檔案永遠等不到它——**這正是為什麼要有 `_ensure_columns()`**。
    """

    @staticmethod
    def _table_columns(connection, table):
        return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}

    def test_舊資料庫重開之後補上欄位而且資料還在(self, tmp_path):
        db_path = str(tmp_path / "lending.sqlite3")
        # 先造一個「沒有新欄位」的舊資料庫，並塞一列進去。
        repo = Repository(db_path)
        repo.connection.execute(
            "CREATE TABLE IF NOT EXISTS pricing_decisions_old AS "
            "SELECT * FROM pricing_decisions"
        )
        repo.connection.execute("DROP TABLE pricing_decisions")
        repo.connection.execute(
            """
            CREATE TABLE pricing_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decided_at TEXT NOT NULL,
                currency TEXT NOT NULL,
                strategy TEXT,
                chosen_rate REAL NOT NULL,
                chosen_effective REAL NOT NULL,
                candidate_count INTEGER NOT NULL,
                hold_hours_assumed REAL
            )
            """
        )
        repo.connection.execute(
            "INSERT INTO pricing_decisions "
            "(decided_at, currency, strategy, chosen_rate, chosen_effective, "
            " candidate_count, hold_hours_assumed) VALUES (?,?,?,?,?,?,?)",
            (now_iso(), "USD", "ExpectedValueStrategy", 0.00024, 0.0002, 110, 48.0),
        )
        repo.connection.commit()
        assert "pricing_knobs_json" not in self._table_columns(
            repo.connection, "pricing_decisions"
        )
        repo.connection.close()

        # 重開：這一次應該把欄位補上，**而且不能動到既有那一列**。
        reopened = Repository(db_path)
        assert "pricing_knobs_json" in self._table_columns(
            reopened.connection, "pricing_decisions"
        )
        rows = list(reopened.connection.execute("SELECT * FROM pricing_decisions"))
        assert len(rows) == 1
        assert rows[0]["chosen_rate"] == pytest.approx(0.00024)
        assert rows[0]["hold_hours_assumed"] == pytest.approx(48.0)
        # 🔴 **舊列的新欄位是 NULL，而 NULL 是「當時沒有這個東西」**
        # ——不是「當時是預設值」。這一層不替讀的人決定那件事。
        assert rows[0]["pricing_knobs_json"] is None

    def test_補欄位是冪等的(self, tmp_path):
        db_path = str(tmp_path / "lending.sqlite3")
        Repository(db_path).connection.close()
        for _ in range(3):
            repo = Repository(db_path)
            assert "pricing_knobs_json" in self._table_columns(
                repo.connection, "pricing_decisions"
            )
            repo.connection.close()

    def test_表不存在時不會順手把空表建起來(self, tmp_path):
        """🔴 **建表是 `ALL_STATEMENTS` 的事。**

        在這裡順手補一張空表，會把「schema 漏了一張表」這件事蓋掉
        ——而那是一個比缺欄位嚴重得多的問題。
        """
        db_path = str(tmp_path / "lending.sqlite3")
        repo = Repository(db_path)
        repo.connection.execute("DROP TABLE pricing_decisions")
        repo.connection.commit()
        repo._ensure_columns()  # 不該爆炸，也不該建表
        assert self._table_columns(repo.connection, "pricing_decisions") == set()
        repo.connection.close()


class TestD064定價旋鈕要跟著決策一起落地:
    def test_旋鈕整組寫進去而且鍵是排序過的(self, tmp_path):
        repo = Repository(str(tmp_path / "lending.sqlite3"))
        row_id = repo.record_pricing_decision(
            "USD",
            {
                "strategy": "ExpectedValueStrategy",
                "chosen_rate": 0.00024,
                "chosen_effective": 0.0002,
                "candidate_count": 110,
                "hold_hours_assumed": 12.0,
                # 故意不照字母序傳進去。
                "pricing_knobs": {"ev_plateau_tolerance_pct": 0.5, "assumed_hold_hours": 12.0},
            },
        )
        stored = repo.connection.execute(
            "SELECT pricing_knobs_json FROM pricing_decisions WHERE id = ?", (row_id,)
        ).fetchone()[0]
        # `sort_keys` 讓兩列可以直接字串比對「設定有沒有變」。
        assert stored == '{"assumed_hold_hours":12.0,"ev_plateau_tolerance_pct":0.5}'

    def test_沒有旋鈕的決策照樣寫得進去(self, tmp_path):
        """向前相容：不是每個策略都有 `pricing_knobs()`。"""
        repo = Repository(str(tmp_path / "lending.sqlite3"))
        row_id = repo.record_pricing_decision(
            "USD",
            {
                "strategy": "SomeOtherStrategy",
                "chosen_rate": 0.00024,
                "chosen_effective": 0.0002,
                "candidate_count": 3,
            },
        )
        stored = repo.connection.execute(
            "SELECT pricing_knobs_json FROM pricing_decisions WHERE id = ?", (row_id,)
        ).fetchone()[0]
        assert stored is None
