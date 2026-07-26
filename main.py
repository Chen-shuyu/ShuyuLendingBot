# -*- coding: utf-8 -*-
"""Bitfinex 放貸機器人的主程式進入點。

以 `while True` + `time.sleep(interval)` 常駐執行，每輪呼叫 `run_once()`
巡檢一次；依 `RetryableError` / `FatalError` / `SkipCycleError` 分類例外，
決定續跑、跳過本輪或直接停止。
"""

import os
import sys
import time
from pathlib import Path

from config.settings import load_config, load_secrets_from_disk, resolve_config_path
from modules.exchange_client import BitfinexClient
from modules.lending_strategy import LendingStrategy
from modules.line_notifier import LineNotifier
from utils.exceptions import FatalError, RetryableError, SkipCycleError
from utils.logger import BotLogger


def run_once(logger, notifier, strategy, client, cancel_settle_seconds: int = 3) -> None:
    """執行一輪巡檢流程：取消舊掛單、查餘額與 FRR、產生掛單計畫、掛單、送出通知。"""
    cancelled = client.cancel_active_offers("USD")
    if cancelled:
        # Bitfinex 取消掛單是非同步處理，回應成功不代表餘額已釋放；
        # 這裡稍等一下再查餘額，避免用到舊餘額把掛單金額算少。
        time.sleep(cancel_settle_seconds)

    balance_usd = client.get_available_balance("USD")
    frr = client.get_frr("USD")
    logger.info(f"目前可用 USD 餘額：{balance_usd}")
    logger.info(f"目前 FRR：{frr}")

    if frr is None or frr <= 0:
        raise SkipCycleError("FRR 無效（None 或非正值），跳過本輪，避免用錯誤利率掛單")

    plans = strategy.build_offer_plan(balance_usd, frr)
    if not plans:
        raise SkipCycleError("可放貸金額低於最低門檻或單筆最小量，跳過本輪")

    for plan in plans:
        logger.info(
            f"建立掛單方案：{plan.amount} {plan.currency}，利率 {plan.rate:.6f}，天期 {plan.duration} 天"
        )
        result = client.create_loan_offer(plan.currency, plan.amount, plan.rate, plan.duration)
        logger.info(f"掛單結果：{result}")

    notifier.send("Bitfinex 放貸機器人已完成一輪巡檢。")


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

    engine_config = config.get("engine", {})
    dry_run = bool(engine_config.get("dry_run", True))
    interval_seconds = int(engine_config.get("interval_seconds", 600))
    cancel_settle_seconds = int(engine_config.get("cancel_settle_seconds", 3))

    client = BitfinexClient(config, logger, dry_run=dry_run)

    logger.info("開始執行 Bitfinex 放貸機器人")
    if not client.test_connection():
        logger.error("啟動檢查失敗")
        return 1

    logger.info(f"進入常駐主迴圈，巡檢間隔 {interval_seconds} 秒")
    try:
        while True:
            try:
                run_once(logger, notifier, strategy, client, cancel_settle_seconds)
            except SkipCycleError as exc:
                logger.info(f"本輪略過：{exc}")
            except RetryableError as exc:
                logger.warning(f"暫時性錯誤，下一輪重試：{exc}")
            except FatalError as exc:
                logger.error(f"致命錯誤，機器人即將停止：{exc}")
                notifier.send(f"Bitfinex 放貸機器人發生致命錯誤，已停止運作：{exc}")
                return 1

            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        logger.info("收到中斷訊號，機器人正常結束。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
