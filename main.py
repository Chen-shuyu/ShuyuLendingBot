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
from strategies.orderbook_depth import OrderBookDepthStrategy
from utils.logger import BotLogger

__all__ = ["EXIT_OK", "EXIT_UNEXPECTED", "EXIT_FATAL", "build_strategy", "main"]

# 可選的策略。`orderbook_depth` 是 2026-08-16 起的正式路線（見 DECISIONS.md D030）；
# `frr_plus` 保留下來不是為了備援，而是為了能一行設定切回去做對照——
# 它已知會把單子掛到市場之上（FRR 高過成交天花板），不該當成自動退路。
STRATEGIES = {
    "orderbook_depth": OrderBookDepthStrategy,
    "frr_plus": FrrPlusStrategy,
}

DEFAULT_STRATEGY = "orderbook_depth"


def build_strategy(config, logger):
    """依 `strategy.mode` 建立策略；設定寫錯就直接用預設值並留下警告。

    **寫錯設定不讓機器人停擺**是刻意的：這台機器人的失敗模式裡，
    「停著不動」跟「用錯策略」一樣糟——兩者都等於資金空轉。
    """
    mode = (config.get("strategy", {}) or {}).get("mode") or DEFAULT_STRATEGY
    strategy_class = STRATEGIES.get(mode)
    if strategy_class is None:
        logger.warning(
            f"設定的策略 `{mode}` 不存在，改用預設的 `{DEFAULT_STRATEGY}`。"
            f"可用值：{'、'.join(STRATEGIES)}"
        )
        strategy_class = STRATEGIES[DEFAULT_STRATEGY]
        mode = DEFAULT_STRATEGY
    logger.info(f"採用放貸策略：{mode}")
    return strategy_class(config)


def main() -> int:
    """組裝各層元件並啟動主迴圈。"""
    root = Path(__file__).resolve().parent
    load_secrets_from_disk(root)
    config_path = resolve_config_path(root)
    config = load_config(str(config_path))

    log_file = os.getenv("BFX_LOG_FILE") or config.get("logging", {}).get("file")
    logger = BotLogger(config.get("logging", {}), log_file)
    notifier = LineNotifier(config.get("line", {}), logger)
    strategy = build_strategy(config, logger)
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
        # 交易面通知的開關放在 line: 底下而不是 engine: ——它管的是「要不要推播」，
        # 不是機器人怎麼跑。關掉之後事件照樣寫日誌（見 `BotEngine._push_trade_event`）。
        push_trade_events=bool(config.get("line", {}).get("push_trade_events", True)),
        rate_tolerance_pct=float(engine_config.get("rate_tolerance_pct", 2.0)),
    )

    logger.info("開始執行 Bitfinex 放貸機器人")
    logger.info(f"資料庫位置：{repository.db_path}")

    return engine.run_forever()


if __name__ == "__main__":
    sys.exit(main())
