# -*- coding: utf-8 -*-
"""Bitfinex 放貸機器人的主程式進入點。

以 `while True` + `time.sleep(interval)` 常駐執行，每輪呼叫 `run_once()`
巡檢一次；依 `RetryableError` / `FatalError` / `SkipCycleError` 分類例外，
決定續跑、跳過本輪或直接停止。

每輪的結果都會寫進 SQLite：掛單流水逐筆落帳（含 dry-run 與失敗），
`bot_state.last_run_at` 則兼作心跳時間戳，連續失敗次數也一併寫入，
讓外部健康檢查不必啟動 Python 就能判斷機器人是否還健康。
"""

import os
import sys
import time
from pathlib import Path

from config.settings import load_config, load_secrets_from_disk, resolve_config_path
from db.repository import Repository
from modules.exchange_client import BitfinexClient
from modules.lending_strategy import LendingStrategy
from modules.line_notifier import LineNotifier
from utils.exceptions import FatalError, RetryableError, SkipCycleError
from utils.logger import BotLogger


class FailureTracker:
    """追蹤連續失敗輪數，跨過門檻時告警，恢復正常時再通知一次。

    只在「剛跨過門檻」與「剛恢復」這兩個時間點送出通知，中間持續失敗不再重送，
    避免交易所長時間異常時把通知管道洗版。

    注意：通知目前走的 `LineNotifier` 因 LINE Notify 已停用而永遠回傳 False，
    告警實際上只會留在日誌裡；待 M4 改寫為 LINE Messaging API 後即自動生效。
    """

    def __init__(self, logger, notifier, repository, alert_after: int = 3):
        self.logger = logger
        self.notifier = notifier
        self.repository = repository
        self.alert_after = max(1, int(alert_after))
        self.consecutive_failures = 0
        self.alerted = False

    def record_success(self) -> None:
        """本輪順利完成（含正常略過），重置計數並在剛恢復時通知。"""
        recovered = self.alerted
        self.consecutive_failures = 0
        self.alerted = False
        self.repository.save_state(consecutive_failures=0)

        if recovered:
            message = "Bitfinex 放貸機器人已恢復正常巡檢。"
            self.logger.info(message)
            self.notifier.send(message)

    def record_failure(self, reason: str) -> None:
        """本輪巡檢失敗，累計次數並在跨過門檻時告警。"""
        self.consecutive_failures += 1
        self.repository.save_state(
            last_action=f"巡檢失敗：{reason}",
            consecutive_failures=self.consecutive_failures,
        )

        if self.consecutive_failures >= self.alert_after and not self.alerted:
            self.alerted = True
            message = (
                f"Bitfinex 放貸機器人已連續 {self.consecutive_failures} 輪巡檢失敗，"
                f"請確認交易所連線與 API 金鑰狀態。最近一次原因：{reason}"
            )
            self.logger.error(message)
            self.notifier.send(message)


def run_once(logger, notifier, strategy, client, repository, cancel_settle_seconds: int = 3) -> None:
    """執行一輪巡檢流程：取消舊掛單、查餘額與 FRR、產生掛單計畫、掛單、落帳、送出通知。"""
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
        # 略過也要寫狀態：機器人是活著且判斷正確的，心跳不該因此中斷。
        repository.save_state(last_action="FRR 無效，略過本輪")
        raise SkipCycleError("FRR 無效（None 或非正值），跳過本輪，避免用錯誤利率掛單")

    plans = strategy.build_offer_plan(balance_usd, frr)
    if not plans:
        repository.save_state(last_frr=frr, last_action="可放貸金額不足，略過本輪")
        raise SkipCycleError("可放貸金額低於最低門檻或單筆最小量，跳過本輪")

    for plan in plans:
        logger.info(
            f"建立掛單方案：{plan.amount} {plan.currency}，利率 {plan.rate:.6f}，天期 {plan.duration} 天"
        )
        try:
            result = client.create_loan_offer(plan.currency, plan.amount, plan.rate, plan.duration)
        except (RetryableError, FatalError) as exc:
            # 掛單 API 無法 rollback：同一輪若前幾筆已成功，錢就已經出去了。
            # 失敗這筆也要留痕，事後才對得出當下的真實狀態。
            repository.record_offer_failure(plan, str(exc))
            raise
        logger.info(f"掛單結果：{result}")
        repository.record_offer(plan, result)

    total_amount = round(sum(plan.amount for plan in plans), 2)
    repository.save_state(
        last_frr=frr,
        last_action=f"掛出 {len(plans)} 筆掛單，合計 {total_amount} USD",
    )
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
    repository = Repository.from_config(config)

    engine_config = config.get("engine", {})
    dry_run = bool(engine_config.get("dry_run", True))
    interval_seconds = int(engine_config.get("interval_seconds", 600))
    cancel_settle_seconds = int(engine_config.get("cancel_settle_seconds", 3))
    alert_after_failures = int(engine_config.get("alert_after_failures", 3))

    client = BitfinexClient(config, logger, dry_run=dry_run)
    failures = FailureTracker(logger, notifier, repository, alert_after_failures)

    logger.info("開始執行 Bitfinex 放貸機器人")
    logger.info(f"資料庫位置：{repository.db_path}")

    try:
        if not client.test_connection():
            logger.error("啟動檢查失敗")
            return 1

        logger.info(f"進入常駐主迴圈，巡檢間隔 {interval_seconds} 秒")
        while True:
            try:
                run_once(logger, notifier, strategy, client, repository, cancel_settle_seconds)
            except SkipCycleError as exc:
                # 略過不算失敗：能走到判斷這一步，代表交易所 API 本身是通的。
                logger.info(f"本輪略過：{exc}")
                failures.record_success()
            except RetryableError as exc:
                logger.warning(f"暫時性錯誤，下一輪重試：{exc}")
                failures.record_failure(str(exc))
            except FatalError as exc:
                logger.error(f"致命錯誤，機器人即將停止：{exc}")
                notifier.send(f"Bitfinex 放貸機器人發生致命錯誤，已停止運作：{exc}")
                return 1
            else:
                failures.record_success()

            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        logger.info("收到中斷訊號，機器人正常結束。")
        return 0
    finally:
        repository.close()


if __name__ == "__main__":
    sys.exit(main())
