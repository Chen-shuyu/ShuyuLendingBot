# -*- coding: utf-8 -*-
"""Bitfinex 放貸機器人的主程式進入點。

這支檔案只負責 bootstrap：載入設定與 secrets、把各層元件組起來、交給
`core/bot_engine.py` 的主迴圈執行，最後把它回傳的離開碼交給作業系統。
巡檢流程、例外分類與離開碼語意都在 `BotEngine` 裡（見 DECISIONS.md D016、D017）。
"""

import os
import sys
from pathlib import Path

from api.bitfinex_client import BitfinexClient
from config.settings import load_config, load_secrets_from_disk, resolve_config_path
from core.bot_engine import EXIT_FATAL, EXIT_OK, EXIT_UNEXPECTED, BotEngine
from db.repository import Repository
from notify.line_messaging import LineNotifier
from strategies.frr_plus import FrrPlusStrategy
from utils.logger import BotLogger

__all__ = ["EXIT_OK", "EXIT_UNEXPECTED", "EXIT_FATAL", "main"]


def main() -> int:
    """組裝各層元件並啟動主迴圈。"""
    root = Path(__file__).resolve().parent
    load_secrets_from_disk(root)
    config_path = resolve_config_path(root)
    config = load_config(str(config_path))

    log_file = os.getenv("BFX_LOG_FILE") or config.get("logging", {}).get("file")
    logger = BotLogger(config.get("logging", {}), log_file)
    notifier = LineNotifier(config.get("line", {}))
    strategy = FrrPlusStrategy(config)
    repository = Repository.from_config(config)

    engine_config = config.get("engine", {})
    dry_run = bool(engine_config.get("dry_run", True))

    client = BitfinexClient(config, logger, dry_run=dry_run)
    engine = BotEngine(
        logger,
        notifier,
        strategy,
        client,
        repository,
        interval_seconds=int(engine_config.get("interval_seconds", 600)),
        cancel_settle_seconds=int(engine_config.get("cancel_settle_seconds", 3)),
        alert_after_failures=int(engine_config.get("alert_after_failures", 3)),
    )

    logger.info("開始執行 Bitfinex 放貸機器人")
    logger.info(f"資料庫位置：{repository.db_path}")

    return engine.run_forever()


if __name__ == "__main__":
    sys.exit(main())
