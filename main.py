# -*- coding: utf-8 -*-
"""Bitfinex 放貸機器人的主程式進入點。

這個版本先以 dry-run 方式啟動，目標是先把整個流程跑通，
包含讀取設定、初始化模組、判斷策略、產生掛單計畫，
並把執行結果輸出到日誌與終端機。
"""

import os
import sys
from pathlib import Path

from config.settings import load_config, load_secrets_from_disk, resolve_config_path
from modules.exchange_client import BitfinexClient
from modules.lending_strategy import LendingStrategy
from modules.line_notifier import LineNotifier
from utils.logger import BotLogger


def main() -> int:
    """主流程入口。"""
    root = Path(__file__).resolve().parent
    load_secrets_from_disk(root)
    config_path = resolve_config_path(root)
    config = load_config(str(config_path))

    log_file = os.getenv("BFX_LOG_FILE") or config.get("logging", {}).get("file")
    logger = BotLogger(config.get("logging", {}), log_file)
    notifier = LineNotifier(config.get("line", {}))
    strategy = LendingStrategy(config)
    client = BitfinexClient(config, logger, dry_run=True)

    logger.info("開始執行 Bitfinex 放貸機器人")
    if not client.test_connection():
        logger.error("啟動檢查失敗")
        return 1

    balance_usd = client.get_available_balance("USD")
    frr = client.get_frr("USD")
    logger.info(f"目前可用 USD 餘額：{balance_usd}")
    logger.info(f"目前 FRR：{frr}")

    plans = strategy.build_offer_plan(balance_usd, frr)
    if not plans:
        logger.info("餘額低於最低放貸門檻，沒有可掛出的方案。")
        return 0

    for plan in plans:
        logger.info(
            f"建立掛單方案：{plan.amount} {plan.currency}，利率 {plan.rate:.6f}，天期 {plan.duration} 天"
        )
        result = client.create_loan_offer(plan.currency, plan.amount, plan.rate, plan.duration)
        logger.info(f"掛單結果：{result}")

    notifier.send("Bitfinex 放貸機器人已完成一次 dry-run 流程。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
