# -*- coding: utf-8 -*-
"""端到端 dry-run 整合測試。

把 `config.yaml` → 設定載入 → 交易所客戶端 → 策略 → 主迴圈單輪 → SQLite 落帳
整條串起來跑，全程 dry-run、不碰真實帳戶。這一份取代了原本寫在
`.github/workflows/python-app.yml` 裡的內嵌 heredoc smoke test——同樣的驗證
放在測試檔裡才改得動、看得懂，CI 也不必再維護兩份。
"""

from pathlib import Path

import pytest

import main
from config.settings import load_config
from db.repository import Repository
from modules.exchange_client import BitfinexClient
from modules.lending_strategy import LendingStrategy
from modules.line_notifier import LineNotifier
from utils.logger import BotLogger

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config():
    """讀專案實際使用的 config.yaml，順便驗證它本身是可用的。"""
    return load_config(str(PROJECT_ROOT / "config.yaml"))


@pytest.fixture
def bot(config, tmp_path, monkeypatch):
    """用真實元件組出一台 dry-run 機器人，只把 DB 與 log 導到暫存目錄。"""
    monkeypatch.setattr(main.time, "sleep", lambda seconds: None)

    logger = BotLogger(config.get("logging", {}), str(tmp_path / "logs" / "bot.log"))
    notifier = LineNotifier(config.get("line", {}))
    strategy = LendingStrategy(config)
    client = BitfinexClient(config, logger, dry_run=True)
    repository = Repository(str(tmp_path / "data" / "lending.sqlite3"))

    yield logger, notifier, strategy, client, repository
    repository.close()


class TestProjectConfig:
    def test_config_yaml_is_loadable(self, config):
        for section in ("bitfinex", "strategy", "engine", "database", "retry", "logging", "line"):
            assert section in config, f"config.yaml 缺少 {section} 區段"

    def test_ships_with_dry_run_enabled(self, config):
        """版控裡的設定檔必須是 dry-run，避免有人 clone 下來直接跑成實單。"""
        assert config["engine"]["dry_run"] is True

    def test_ships_without_credentials(self, config, monkeypatch):
        monkeypatch.delenv("BFX_API_KEY", raising=False)
        monkeypatch.delenv("BFX_API_SECRET", raising=False)
        fresh = load_config(str(PROJECT_ROOT / "config.yaml"))
        assert fresh["bitfinex"]["api_key"] == ""
        assert fresh["bitfinex"]["api_secret"] == ""


class TestDryRunCycle:
    def test_connection_check_passes(self, bot):
        _, _, _, client, _ = bot
        assert client.test_connection() is True

    def test_single_cycle_records_offers_and_heartbeat(self, bot):
        logger, notifier, strategy, client, repository = bot
        main.run_once(logger, notifier, strategy, client, repository, cancel_settle_seconds=0)

        rows = [dict(row) for row in repository.connection.execute("SELECT * FROM loan_offers")]
        assert rows, "dry-run 巡檢後應該要有掛單紀錄"
        assert {row["status"] for row in rows} == {"dry_run"}

        state = repository.get_state()
        assert state["last_run_at"] is not None
        assert state["last_frr"] > 0

    def test_offer_amounts_match_configured_balance(self, bot, config):
        """dry-run 餘額由設定檔給定，掛出的總額不得超過它。"""
        logger, notifier, strategy, client, repository = bot
        main.run_once(logger, notifier, strategy, client, repository, cancel_settle_seconds=0)

        total = repository.connection.execute("SELECT SUM(amount) FROM loan_offers").fetchone()[0]
        assert total <= config["bitfinex"]["dry_run_balance_usd"]

    def test_multiple_cycles_accumulate(self, bot):
        logger, notifier, strategy, client, repository = bot
        for _ in range(5):
            main.run_once(logger, notifier, strategy, client, repository, cancel_settle_seconds=0)

        count = repository.connection.execute("SELECT COUNT(*) FROM loan_offers").fetchone()[0]
        assert count >= 5

    def test_writes_to_the_log_file(self, bot, tmp_path):
        logger, notifier, strategy, client, repository = bot
        main.run_once(logger, notifier, strategy, client, repository, cancel_settle_seconds=0)

        content = (tmp_path / "logs" / "bot.log").read_text(encoding="utf-8")
        assert "目前 FRR" in content

    def test_database_file_is_created_on_disk(self, bot, tmp_path):
        assert (tmp_path / "data" / "lending.sqlite3").exists()

    def test_state_survives_reopen(self, bot, tmp_path):
        """容器重啟後要讀得回上次心跳，這是 healthcheck 的資料來源。"""
        logger, notifier, strategy, client, repository = bot
        main.run_once(logger, notifier, strategy, client, repository, cancel_settle_seconds=0)
        last_run_at = repository.get_state()["last_run_at"]

        reopened = Repository(str(tmp_path / "data" / "lending.sqlite3"))
        assert reopened.get_state()["last_run_at"] == last_run_at
        reopened.close()


class TestDryRunSafety:
    """dry-run 的唯一意義就是「絕對不動到真實資金」，這裡把它釘死。"""

    def test_no_exchange_object_is_created(self, bot):
        _, _, _, client, _ = bot
        assert client.exchange is None

    def test_offers_are_marked_dry_run(self, bot):
        logger, notifier, strategy, client, repository = bot
        main.run_once(logger, notifier, strategy, client, repository, cancel_settle_seconds=0)

        statuses = {
            row[0] for row in repository.connection.execute("SELECT DISTINCT status FROM loan_offers")
        }
        assert statuses == {"dry_run"}

    def test_no_exchange_offer_ids_recorded(self, bot):
        logger, notifier, strategy, client, repository = bot
        main.run_once(logger, notifier, strategy, client, repository, cancel_settle_seconds=0)

        ids = [row[0] for row in repository.connection.execute("SELECT offer_id FROM loan_offers")]
        assert all(offer_id is None for offer_id in ids)
