# -*- coding: utf-8 -*-
"""`scripts/notify_failure.py` 的單元測試。

這支腳本只在「機器人已經死了、systemd 也放棄了」的時候執行，等於整條可靠性鏈
的最後一環。它自己失效的話沒有下一道防線，而且失效方式很安靜——不會有人發現
「本來應該收到的告警沒有來」。所以三件事要逐一釘住：訊息寫得出去、
一個管道壞掉不影響其他管道、以及**絕對不能更新心跳**。
"""

import sqlite3

import pytest

from db.repository import Repository
from scripts import notify_failure


GAVE_UP = {"ActiveState": "failed", "SubState": "failed", "NRestarts": "4"}
RETRYING = {"ActiveState": "activating", "SubState": "auto-restart", "NRestarts": "1"}
# 部署／手動 `systemctl restart` 造成的觸發：等 2 秒再查時單元已經在跑了。
# 這正是實際發生三次的假警報（TASKS.md B4），六個欄位全都說單元是好的。
RESTARTED = {
    "Result": "success",
    "ExecMainStatus": "0",
    "NRestarts": "0",
    "ActiveState": "active",
    "SubState": "running",
}
# 真的失敗過、但在查詢前就已經被 systemd 拉回來了
RECOVERED = dict(RESTARTED, NRestarts="2")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("BFX_UNIT", "BFX_LOG_FILE", "BFX_DB_PATH"):
        monkeypatch.delenv(name, raising=False)
    # 測試不要真的等狀態沉澱
    monkeypatch.setenv("BFX_ALERT_SETTLE_SECONDS", "0")
    # 預設當成「已放棄」，各測試要驗細節時再自行覆寫
    monkeypatch.setattr(notify_failure, "collect_unit_state", lambda unit: dict(GAVE_UP))


class TestHasGivenUp:
    """`OnFailure=` 每次失敗都會觸發，所以分辨「重試中」與「已放棄」是這支腳本的職責。"""

    def test_failed_means_given_up(self):
        assert notify_failure.has_given_up(GAVE_UP) is True

    def test_auto_restart_means_still_retrying(self):
        assert notify_failure.has_given_up(RETRYING) is False

    def test_unknown_state_is_treated_as_given_up(self):
        # 寧可多喊一次狼來了，也不要在機器人真的死掉時因為查不到狀態而靜悄悄放過
        assert notify_failure.has_given_up({}) is True

    def test_running_unit_is_neither_given_up_nor_retrying(self):
        # B4：這是原本缺的第三種狀態，它以前落進「重試中」的 else
        assert notify_failure.has_given_up(RESTARTED) is False
        assert notify_failure.classify(RESTARTED) == notify_failure.STATE_RUNNING_NOW


class TestClassifyThreeStates:
    """三種狀態各自對應一種處置，順序不能顛倒（見 `classify()` docstring）。"""

    def test_gave_up(self):
        assert notify_failure.classify(GAVE_UP) == notify_failure.STATE_GAVE_UP

    def test_retrying(self):
        assert notify_failure.classify(RETRYING) == notify_failure.STATE_RETRYING

    def test_running_now(self):
        assert notify_failure.classify(RESTARTED) == notify_failure.STATE_RUNNING_NOW

    def test_auto_restart_wins_over_active(self):
        # 重啟途中若同時出現 active 與 auto-restart，必須判成「重試中」而非「已恢復」
        mixed = {"ActiveState": "active", "SubState": "auto-restart", "NRestarts": "1"}
        assert notify_failure.classify(mixed) == notify_failure.STATE_RETRYING

    def test_missing_state_still_means_gave_up(self):
        assert notify_failure.classify({}) == notify_failure.STATE_GAVE_UP


class TestBuildMessage:
    def test_given_up_message_asks_for_intervention(self):
        message = notify_failure.build_message("shuyu-lending-bot.service", GAVE_UP)
        assert "shuyu-lending-bot.service" in message
        assert "不會再自動重啟" in message
        # 告警要能直接照著做，不然半夜看到只會更慌
        assert "reset-failed" in message
        assert notify_failure.log_level(GAVE_UP) == "CRITICAL"

    def test_retrying_message_does_not_claim_it_gave_up(self):
        # 中途那幾次若也寫成「不會再自動重啟」，看到的人會做出錯誤判斷
        message = notify_failure.build_message("shuyu-lending-bot.service", RETRYING)
        assert "正在自動重試" in message
        assert "不會再自動重啟" not in message
        assert "已重啟 1 次" in message
        assert notify_failure.log_level(RETRYING) == "ERROR"

    def test_restart_trigger_does_not_claim_a_failure(self):
        # B4 的核心：單元好好的時候，訊息不可以說「啟動失敗」，等級也不可以是 ERROR
        message = notify_failure.build_message("shuyu-lending-bot.service", RESTARTED)
        assert "啟動失敗" not in message
        assert "不會再自動重啟" not in message
        assert "正常運作中" in message
        assert "不需人工介入" in message
        assert notify_failure.log_level(RESTARTED) == "INFO"

    def test_recovered_unit_is_reported_as_warning(self):
        # 確實重啟過，就不能講成「什麼事都沒發生」——但也還不到要人半夜爬起來
        message = notify_failure.build_message("shuyu-lending-bot.service", RECOVERED)
        assert "已自動恢復" in message
        assert "已重啟 2 次" in message
        assert "不需人工介入" in message
        assert notify_failure.log_level(RECOVERED) == "WARNING"

    def test_non_numeric_restart_count_falls_back_to_info(self):
        # NRestarts 問不到時不該讓腳本自己爆掉
        odd = dict(RESTARTED, NRestarts="")
        assert notify_failure.log_level(odd) == "INFO"

    def test_unit_state_is_appended_when_available(self):
        message = notify_failure.build_message(
            "shuyu-lending-bot.service",
            dict(GAVE_UP, Result="start-limit-hit", ExecMainStatus="1"),
        )
        assert "start-limit-hit" in message
        assert "最後離開碼=1" in message
        assert "已重啟次數=4" in message


class TestAppendToLog:
    def test_appends_without_truncating(self, tmp_path):
        log_file = tmp_path / "bfx_lending_bot.log"
        log_file.write_text("2026-08-09 12:00:00,000 INFO 既有內容\n", encoding="utf-8")

        notify_failure.append_to_log(str(log_file), "機器人停了")

        content = log_file.read_text(encoding="utf-8")
        assert "既有內容" in content
        assert "CRITICAL 機器人停了" in content

    def test_creates_log_when_missing(self, tmp_path):
        # 日誌檔可能因為輪替或全新部署而不存在，這時仍要留下痕跡
        log_file = tmp_path / "bfx_lending_bot.log"
        notify_failure.append_to_log(str(log_file), "機器人停了")
        assert "CRITICAL 機器人停了" in log_file.read_text(encoding="utf-8")

    def test_level_is_configurable(self, tmp_path):
        # 重試中的訊息用 ERROR，才能跟「真的死了」在日誌裡分得開
        log_file = tmp_path / "bfx_lending_bot.log"
        notify_failure.append_to_log(str(log_file), "正在重試", "ERROR")
        assert "ERROR 正在重試" in log_file.read_text(encoding="utf-8")


class TestRecordInDatabase:
    def test_updates_last_action(self, tmp_path):
        db_path = tmp_path / "lending.sqlite3"
        repo = Repository(str(db_path))
        repo.save_state(last_action="掛出 2 筆掛單")
        repo.close()

        notify_failure.record_in_database(str(db_path), "機器人停了")

        repo = Repository(str(db_path))
        assert repo.get_state()["last_action"] == "機器人停了"
        repo.close()

    def test_never_touches_the_heartbeat(self, tmp_path):
        """心跳絕對不能被告警更新——機器人已經死了，更新它等於偽造它還活著。"""
        db_path = tmp_path / "lending.sqlite3"
        repo = Repository(str(db_path))
        repo.save_state(last_action="掛出 2 筆掛單")
        before = repo.get_state()["last_run_at"]
        repo.close()

        notify_failure.record_in_database(str(db_path), "機器人停了")

        repo = Repository(str(db_path))
        assert repo.get_state()["last_run_at"] == before
        repo.close()

    def test_does_not_create_a_missing_database(self, tmp_path):
        # 與 healthcheck 同一個原則：DB 掛載掉的時候順手把它建回來，
        # 只會把真正的問題蓋掉
        db_path = tmp_path / "never-created.sqlite3"
        with pytest.raises(sqlite3.OperationalError):
            notify_failure.record_in_database(str(db_path), "機器人停了")
        assert not db_path.exists()


class TestMain:
    def test_writes_to_both_sinks_and_succeeds(self, tmp_path, monkeypatch, capsys):
        log_file = tmp_path / "bfx_lending_bot.log"
        db_path = tmp_path / "lending.sqlite3"
        Repository(str(db_path)).close()
        monkeypatch.setenv("BFX_LOG_FILE", str(log_file))
        monkeypatch.setenv("BFX_DB_PATH", str(db_path))

        assert notify_failure.main() == 0
        assert "CRITICAL" in log_file.read_text(encoding="utf-8")
        # 一定會有一份寫到 stdout：由 systemd 執行，這份會進 journal
        assert "不會再自動重啟" in capsys.readouterr().out

    def test_broken_database_does_not_stop_the_log(self, tmp_path, monkeypatch, capsys):
        # DB 掛載掉正是可能觸發這支腳本的原因之一，那時更不能連日誌也不留
        log_file = tmp_path / "bfx_lending_bot.log"
        monkeypatch.setenv("BFX_LOG_FILE", str(log_file))
        monkeypatch.setenv("BFX_DB_PATH", str(tmp_path / "missing.sqlite3"))

        assert notify_failure.main() == 0
        assert "CRITICAL" in log_file.read_text(encoding="utf-8")
        assert "告警寫入資料庫失敗" in capsys.readouterr().err

    def test_broken_log_does_not_stop_the_database(self, tmp_path, monkeypatch):
        db_path = tmp_path / "lending.sqlite3"
        Repository(str(db_path)).close()
        monkeypatch.setenv("BFX_LOG_FILE", str(tmp_path / "no-such-dir" / "bot.log"))
        monkeypatch.setenv("BFX_DB_PATH", str(db_path))

        assert notify_failure.main() == 0
        repo = Repository(str(db_path))
        assert "不會再自動重啟" in repo.get_state()["last_action"]
        repo.close()

    def test_returns_failure_when_nothing_was_delivered(self, tmp_path, monkeypatch, capsys):
        """一個管道都沒送成就要是紅的。

        「以為有人會被通知、其實沒有」正是 B2 本身的問題，
        不能在告警機制裡再犯一次——包含「環境變數忘了設」這種情況。
        """
        monkeypatch.delenv("BFX_LOG_FILE", raising=False)
        monkeypatch.delenv("BFX_DB_PATH", raising=False)

        assert notify_failure.main() == 1
        assert "所有告警管道都沒有送出" in capsys.readouterr().err

    def test_retrying_state_is_logged_as_error_not_critical(
        self, tmp_path, monkeypatch
    ):
        log_file = tmp_path / "bfx_lending_bot.log"
        monkeypatch.setenv("BFX_LOG_FILE", str(log_file))
        monkeypatch.setattr(notify_failure, "collect_unit_state", lambda unit: dict(RETRYING))

        assert notify_failure.main() == 0
        content = log_file.read_text(encoding="utf-8")
        assert "ERROR" in content
        assert "CRITICAL" not in content

    def test_line_channel_is_not_wired_yet(self):
        # 憑證到位前刻意回 False（不是失敗，是「還沒接上」）。
        # 這條測試在 LINE 接上時會失敗，正好提醒要回來更新這裡與 TASKS.md
        assert notify_failure.send_line_push("測試訊息") is False
