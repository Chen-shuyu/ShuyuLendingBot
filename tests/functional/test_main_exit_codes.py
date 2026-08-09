# -*- coding: utf-8 -*-
"""`main.main()` 的離開碼與退出前落帳的功能測試。

容器的 restart policy 只看離開碼是不是 0，而日誌在這個部署環境不一定拿得到
（見 DECISIONS.md D016），所以「退出時回什麼碼」與「退出前有沒有把原因寫進 DB」
是事後唯一能追查的線索，兩者都要釘住。

這裡把 `main()` 的外部依賴全部換成替身，只保留主迴圈本身的控制流程。
"""

import sqlite3

import pytest

import main
from db.repository import Repository
from utils.exceptions import FatalError


class StubClient:
    """只負責決定啟動檢查通不通過、以及巡檢時要不要拋例外。"""

    def __init__(self, config, logger, dry_run=True):
        self.connected = StubClient.connect_result
        self.cycle_effect = StubClient.cycle_effect

    # 以類別屬性設定行為，免得還要為了注入而改 main() 的建構流程
    connect_result = True
    cycle_effect = None

    def test_connection(self):
        return self.connected

    def cancel_active_offers(self, currency):
        if isinstance(self.cycle_effect, Exception):
            raise self.cycle_effect
        return []

    def get_available_balance(self, currency):
        return 600.0

    def get_frr(self, currency):
        return 0.0002

    def create_loan_offer(self, currency, amount, rate, duration):  # pragma: no cover - 用不到
        raise AssertionError("這組測試的策略一律回傳空計畫，不該走到掛單")


class StubStrategy:
    """一律回傳空的掛單計畫，讓 `run_once()` 走「略過本輪」那條最短路徑。"""

    def __init__(self, config):
        pass

    def build_offer_plan(self, balance, frr):
        return []


@pytest.fixture
def run_main(tmp_path, monkeypatch, fake_logger, fake_notifier):
    """組好一個可執行的 `main()`，回傳 (執行函式, 讀回狀態的函式)。"""
    db_path = tmp_path / "data" / "lending.sqlite3"
    repository = Repository(str(db_path))

    config = {
        "engine": {"interval_seconds": 1, "dry_run": True, "cancel_settle_seconds": 0},
        "logging": {"level": "INFO"},
        "line": {"enabled": False},
        "database": {"path": str(db_path)},
    }

    class RepositoryStub:
        @staticmethod
        def from_config(_config):
            return repository

    monkeypatch.setattr(main, "load_secrets_from_disk", lambda root: None)
    monkeypatch.setattr(main, "resolve_config_path", lambda root: tmp_path / "config.yaml")
    monkeypatch.setattr(main, "load_config", lambda path: config)
    monkeypatch.setattr(main, "BotLogger", lambda *args, **kwargs: fake_logger)
    monkeypatch.setattr(main, "LineNotifier", lambda *args, **kwargs: fake_notifier)
    monkeypatch.setattr(main, "LendingStrategy", StubStrategy)
    monkeypatch.setattr(main, "Repository", RepositoryStub)
    monkeypatch.setattr(main, "BitfinexClient", StubClient)
    # 主迴圈跑完一輪就靠這裡結束，否則測試會永遠轉下去
    monkeypatch.setattr(main.time, "sleep", _raise_keyboard_interrupt)

    StubClient.connect_result = True
    StubClient.cycle_effect = None

    def read_state():
        # main() 的 finally 會關掉連線，另開一條唯讀不到的話就重建一個 Repository
        reopened = Repository(str(db_path))
        state = reopened.get_state()
        reopened.close()
        return state

    yield main.main, read_state

    StubClient.connect_result = True
    StubClient.cycle_effect = None


def _raise_keyboard_interrupt(_seconds):
    raise KeyboardInterrupt


class TestExitCodes:
    def test_codes_are_distinct_and_ok_is_zero(self):
        # 0 有特殊意義：restart policy 的 on-failure 只有在非 0 時才會重啟
        assert main.EXIT_OK == 0
        assert len({main.EXIT_OK, main.EXIT_UNEXPECTED, main.EXIT_FATAL}) == 3

    def test_normal_shutdown_returns_ok(self, run_main):
        run, _ = run_main
        assert run() == main.EXIT_OK

    def test_failed_startup_check_returns_fatal(self, run_main, fake_notifier):
        run, read_state = run_main
        StubClient.connect_result = False

        assert run() == main.EXIT_FATAL
        assert "啟動檢查失敗" in read_state()["last_action"]
        assert any("啟動檢查失敗" in message for message in fake_notifier.sent)

    def test_fatal_error_returns_fatal_and_records_reason(self, run_main, fake_notifier):
        run, read_state = run_main
        StubClient.cycle_effect = FatalError("API 金鑰無效")

        assert run() == main.EXIT_FATAL
        state = read_state()
        assert "致命錯誤已停止" in state["last_action"]
        assert "API 金鑰無效" in state["last_action"]
        assert any("致命錯誤" in message for message in fake_notifier.sent)

    def test_unexpected_exception_returns_unexpected_and_leaves_traceback(
        self, run_main, fake_logger, fake_notifier
    ):
        # 沒被分類過的例外原本只會噴到 stderr，而容器 stderr 在這個環境拿不到
        run, read_state = run_main
        StubClient.cycle_effect = ValueError("沒人想過的狀況")

        assert run() == main.EXIT_UNEXPECTED
        assert "未預期的例外已停止" in read_state()["last_action"]
        assert any("未預期的例外" in message for message in fake_logger.messages["exception"])
        assert any("未預期的例外" in message for message in fake_notifier.sent)

    def test_heartbeat_is_written_even_when_startup_fails(self, run_main):
        # 健康檢查靠 last_run_at 判斷，啟動就失敗時也要有時間戳，
        # 否則檢查只會說「還沒跑過」，看不出是剛啟動還是啟動失敗
        run, read_state = run_main
        StubClient.connect_result = False

        run()
        assert read_state()["last_run_at"] is not None


class TestExitPathSurvivesBrokenDatabase:
    """資料庫故障時，退出路徑上的落帳不能反過來蓋掉真正的死因（TASKS.md A3）。

    「volume 掛載掉了」正是這個部署真實發生過的狀況（M3 起部署失敗的根因就是
    主機端目錄不存在），而那時候最需要的就是看到原始錯誤、收到通知、
    以及讓 systemd 拿到正確的離開碼——`RestartPreventExitStatus=2` 靠的就是它。
    """

    @pytest.fixture(autouse=True)
    def break_save_state(self, run_main, monkeypatch):
        """讓 `save_state()` 一定拋例外，模擬 DB 故障。"""
        run, _ = run_main
        self.run = run

        def explode(*args, **kwargs):
            raise sqlite3.OperationalError("disk I/O error")

        # main() 拿到的 repository 就是 fixture 建的那一個
        monkeypatch.setattr(Repository, "save_state", explode)

    def test_startup_failure_still_returns_fatal(self, fake_notifier, fake_logger):
        StubClient.connect_result = False

        assert self.run() == main.EXIT_FATAL
        assert any("啟動檢查失敗" in message for message in fake_notifier.sent)
        assert any("退出前落帳失敗" in message for message in fake_logger.messages["error"])

    def test_fatal_error_still_returns_fatal_and_keeps_original_reason(
        self, fake_notifier, fake_logger
    ):
        # 最容易出錯的一條：落帳拋出的新例外若沒攔住，會被外層的
        # `except Exception` 接住，EXIT_FATAL 直接變成 EXIT_UNEXPECTED
        StubClient.cycle_effect = FatalError("API 金鑰無效")

        assert self.run() == main.EXIT_FATAL
        assert any("API 金鑰無效" in message for message in fake_notifier.sent)
        # 原始死因必須留在日誌裡，不能被落帳的錯誤取代
        assert any(
            "致命錯誤已停止" in message and "API 金鑰無效" in message
            for message in fake_logger.messages["error"]
        )

    def test_unexpected_exception_still_returns_unexpected(self, fake_notifier):
        StubClient.cycle_effect = ValueError("沒人想過的狀況")

        assert self.run() == main.EXIT_UNEXPECTED
        assert any("沒人想過的狀況" in message for message in fake_notifier.sent)

    def test_close_failure_does_not_change_exit_code(self, monkeypatch, fake_logger):
        # finally 裡拋出的例外會取代回傳值，離開碼會變成 1 並印出無關的 traceback
        def explode(self):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(Repository, "close", explode)
        StubClient.connect_result = False

        assert self.run() == main.EXIT_FATAL
        assert any("關閉資料庫連線失敗" in message for message in fake_logger.messages["error"])
