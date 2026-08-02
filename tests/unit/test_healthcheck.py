# -*- coding: utf-8 -*-
"""`scripts/healthcheck.py` 的單元測試。

健康檢查是唯一會自動判斷「機器人是不是還活著」的東西，判斷錯的代價是雙向的：
誤判成不健康會讓一個好好的容器被重啟，漏判則等於整個安全網形同虛設。
因此邊界情況（沒有心跳、時間格式壞掉、時鐘往前跳）都要逐一釘住。
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from db.repository import Repository
from scripts import healthcheck


def utc(offset_seconds=0):
    return datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)


def iso(offset_seconds=0):
    return utc(offset_seconds).isoformat(timespec="seconds")


class TestMaxSilenceSeconds:
    def test_default_is_three_cycles_plus_buffer(self):
        # 600 秒間隔 → 600*3 + 60
        assert healthcheck.max_silence_seconds({"interval_seconds": 600}) == 1860

    def test_missing_interval_falls_back_to_default(self):
        assert healthcheck.max_silence_seconds({}) == 600 * 3 + 60

    def test_none_config_falls_back_to_default(self):
        assert healthcheck.max_silence_seconds(None) == 600 * 3 + 60

    def test_zero_interval_falls_back_to_default(self):
        # 設定寫成 0 時不能算出 60 秒這種過嚴的門檻，否則每次都會誤判不健康
        assert healthcheck.max_silence_seconds({"interval_seconds": 0}) == 600 * 3 + 60

    def test_explicit_override_wins(self):
        config = {"interval_seconds": 600, "health_max_silence_seconds": 90}
        assert healthcheck.max_silence_seconds(config) == 90


class TestEvaluate:
    def test_missing_state_is_unhealthy(self):
        healthy, reason = healthcheck.evaluate(None, 1860)
        assert healthy is False
        assert "尚未寫入任何心跳" in reason

    def test_state_without_heartbeat_is_unhealthy(self):
        healthy, _ = healthcheck.evaluate({"last_run_at": None}, 1860)
        assert healthy is False

    def test_fresh_heartbeat_is_healthy(self):
        healthy, reason = healthcheck.evaluate({"last_run_at": iso(-30)}, 1860)
        assert healthy is True
        assert "心跳正常" in reason

    def test_stale_heartbeat_is_unhealthy(self):
        healthy, reason = healthcheck.evaluate({"last_run_at": iso(-2000)}, 1860)
        assert healthy is False
        assert "超過上限" in reason

    def test_exactly_at_limit_is_still_healthy(self):
        # 邊界取「超過才算壞」：剛好等於上限時判成不健康，會讓間隔設定卡在門檻上時反覆抖動
        # 心跳字串是秒精度，now 也要抹掉微秒，否則兩者相減永遠會多出不到一秒的零頭
        now = utc().replace(microsecond=0)
        state = {"last_run_at": (now - timedelta(seconds=100)).isoformat(timespec="seconds")}
        healthy, _ = healthcheck.evaluate(state, 100, now=now)
        assert healthy is True

    def test_unparsable_timestamp_is_unhealthy(self):
        healthy, reason = healthcheck.evaluate({"last_run_at": "not-a-time"}, 1860)
        assert healthy is False
        assert "無法解析" in reason

    def test_naive_timestamp_is_treated_as_utc(self):
        # 寫入端一律帶時區，這是防呆：沒有時區時直接相減會拋 TypeError
        naive = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
        healthy, _ = healthcheck.evaluate({"last_run_at": naive}, 1860)
        assert healthy is True

    def test_future_heartbeat_is_healthy(self):
        # 主機時鐘被校正時心跳會落在未來，那不是機器人的問題，不該重啟一個好好的容器
        healthy, reason = healthcheck.evaluate({"last_run_at": iso(300)}, 1860)
        assert healthy is True
        assert "時鐘偏移" in reason


class TestReadState:
    def test_reads_state_written_by_repository(self, tmp_path):
        db_path = tmp_path / "data" / "lending.sqlite3"
        repo = Repository(str(db_path))
        repo.save_state(last_frr=0.0002, last_action="掛出 2 筆掛單")
        repo.close()

        state = healthcheck.read_state(db_path)
        assert state["last_action"] == "掛出 2 筆掛單"
        assert state["last_run_at"] is not None
        assert state["consecutive_failures"] == 0

    def test_missing_database_raises_instead_of_creating_it(self, tmp_path):
        # 唯讀模式的重點：健康檢查絕不能順手把資料庫補回去，那會蓋掉「掛載掉了」這個真正的問題
        db_path = tmp_path / "never-created.sqlite3"
        with pytest.raises(sqlite3.OperationalError):
            healthcheck.read_state(db_path)
        assert not db_path.exists()


class TestResolveDbPath:
    def test_env_var_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BFX_DB_PATH", "/tmp/somewhere/lending.sqlite3")
        assert healthcheck.resolve_db_path(tmp_path) == healthcheck.Path("/tmp/somewhere/lending.sqlite3")

    def test_relative_config_path_is_resolved_against_root(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BFX_DB_PATH", raising=False)
        (tmp_path / "config.yaml").write_text("database:\n  path: data/lending.sqlite3\n", encoding="utf-8")
        monkeypatch.delenv("BFX_CONFIG", raising=False)
        assert healthcheck.resolve_db_path(tmp_path) == tmp_path / "data" / "lending.sqlite3"

    def test_falls_back_to_default_when_config_missing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BFX_DB_PATH", raising=False)
        monkeypatch.delenv("BFX_CONFIG", raising=False)
        assert healthcheck.resolve_db_path(tmp_path) == tmp_path / "data" / "lending.sqlite3"


class TestMain:
    @pytest.fixture
    def project(self, tmp_path, monkeypatch):
        """準備一個假的專案根目錄：一份 config.yaml，DB 由各測試自行決定要不要建。"""
        (tmp_path / "config.yaml").write_text(
            "database:\n  path: data/lending.sqlite3\nengine:\n  interval_seconds: 600\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("BFX_DB_PATH", raising=False)
        monkeypatch.delenv("BFX_CONFIG", raising=False)
        monkeypatch.setattr(healthcheck, "project_root", lambda: tmp_path)
        return tmp_path

    def test_missing_database_returns_unhealthy(self, project, capsys):
        assert healthcheck.main() == 1
        assert "找不到資料庫" in capsys.readouterr().err

    def test_fresh_heartbeat_returns_healthy(self, project, capsys):
        repo = Repository(str(project / "data" / "lending.sqlite3"))
        repo.save_state(last_action="掛出 2 筆掛單")
        repo.close()

        assert healthcheck.main() == 0
        assert "healthy" in capsys.readouterr().out

    def test_stale_heartbeat_returns_unhealthy(self, project, capsys):
        db_path = project / "data" / "lending.sqlite3"
        repo = Repository(str(db_path))
        repo.save_state(last_action="掛出 2 筆掛單")
        stale = (datetime.now(timezone.utc) - timedelta(seconds=5000)).isoformat(timespec="seconds")
        repo.connection.execute("UPDATE bot_state SET last_run_at = ? WHERE id = 1", (stale,))
        repo.connection.commit()
        repo.close()

        assert healthcheck.main() == 1
        assert "超過上限" in capsys.readouterr().err

    def test_never_ran_returns_unhealthy(self, project, capsys):
        # 資料表建好了但一輪都還沒跑完：--health-start-period 負責寬容這段時間，
        # 檢查本身仍要如實回報「還沒有心跳」
        Repository(str(project / "data" / "lending.sqlite3")).close()

        assert healthcheck.main() == 1
        assert "尚未寫入任何心跳" in capsys.readouterr().err
