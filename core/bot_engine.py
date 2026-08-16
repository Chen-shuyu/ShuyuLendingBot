# -*- coding: utf-8 -*-
"""放貸機器人的主迴圈狀態機。

`BotEngine` 以 `while True` + `time.sleep(interval)` 常駐執行，每輪呼叫
`run_once()` 巡檢一次；依 `RetryableError` / `FatalError` / `SkipCycleError`
分類例外，決定續跑、跳過本輪或直接停止。所有副作用（交易所讀寫、落帳、通知、
睡眠）都集中在這一層，策略層因此得以維持純函式。

每輪的結果都會寫進 SQLite：掛單流水逐筆落帳（含 dry-run 與失敗），
`bot_state.last_run_at` 則兼作心跳時間戳，連續失敗次數也一併寫入，
讓外部健康檢查不必啟動 Python 就能判斷機器人是否還健康。

離開碼分成三種（見 DECISIONS.md D016、D017）。容器生命週期改由 systemd 的 Quadlet
單元管理之後，離開碼不只是給人看的：單元用 `RestartPreventExitStatus=2` 表達
「`EXIT_FATAL` 就不要重啟」，重啟次數的節流則由 `StartLimitIntervalSec` /
`StartLimitBurst` 負責。因此**退出路徑上的任何失敗都不能改變離開碼**，
否則 systemd 會做出相反的重啟決定（見 `_record_exit_reason`）。
"""

import time

from notify import messages
from utils.exceptions import FatalError, RetryableError, SkipCycleError

# 離開碼語意
EXIT_OK = 0  # 正常結束（收到中斷訊號）
EXIT_UNEXPECTED = 1  # 未預期的例外，重啟有機會自行恢復
EXIT_FATAL = 2  # 金鑰無效這類問題，人不介入就不會好，重啟只會空轉


class FailureTracker:
    """追蹤連續失敗輪數，跨過門檻時告警，恢復正常時再通知一次。

    只在「剛跨過門檻」與「剛恢復」這兩個時間點送出通知，中間持續失敗不再重送，
    避免交易所長時間異常時把通知管道洗版。

    「只在跨門檻與恢復時各送一次」這件事，在 LINE 接上之後從「避免洗版」
    升級成硬性需求：免費方案每月只有 200 則，持續失敗若每輪都推，
    額度會在故障期間被自己燒光（見 DECISIONS.md D024）。
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
            # 日誌寫一行、LINE 推三段式（見 `notify/messages.py`）。兩邊刻意不共用同一個
            # 字串：日誌是一筆一行的格式，塞進多行訊息會讓後續幾行看起來不像日誌，
            # `grep ERROR` 也會漏掉它們。
            self.logger.info("Bitfinex 放貸機器人已恢復正常巡檢。")
            self.notifier.send(messages.recovered())

    def record_failure(self, reason: str) -> None:
        """本輪巡檢失敗，累計次數並在跨過門檻時告警。"""
        self.consecutive_failures += 1
        self.repository.save_state(
            last_action=f"巡檢失敗：{reason}",
            consecutive_failures=self.consecutive_failures,
        )

        if self.consecutive_failures >= self.alert_after and not self.alerted:
            self.alerted = True
            self.logger.error(
                f"Bitfinex 放貸機器人已連續 {self.consecutive_failures} 輪巡檢失敗，"
                f"請確認交易所連線與 API 金鑰狀態。最近一次原因：{reason}"
            )
            self.notifier.send(messages.consecutive_failures(self.consecutive_failures, reason))


class BotEngine:
    """把交易所、策略、資料層與通知接起來的主迴圈。"""

    def __init__(
        self,
        logger,
        notifier,
        strategy,
        client,
        repository,
        interval_seconds: int = 600,
        cancel_settle_seconds: int = 3,
        alert_after_failures: int = 3,
        push_trade_events: bool = True,
    ):
        self.logger = logger
        self.notifier = notifier
        self.strategy = strategy
        self.client = client
        self.repository = repository
        self.interval_seconds = int(interval_seconds)
        self.cancel_settle_seconds = int(cancel_settle_seconds)
        self.push_trade_events = bool(push_trade_events)
        self.failures = FailureTracker(logger, notifier, repository, alert_after_failures)
        # 場上有沒有我們的掛單：True 有、False 沒有、None 還不知道（剛啟動）。
        # 交易面通知推的是**這個值的變化**，不是每輪的結果——每輪全取消重掛若每次都推，
        # 一天 144 則、不到兩天就把每月 200 則的額度燒光（見 D024）。
        # 狀態只放記憶體、不落 DB：重啟後回到 None，下一次掛單成功會推一則
        # 「啟動後首輪」——那正是部署完最想確認的事，不算浪費額度。
        self._offers_live = None

    def run_once(self) -> None:
        """執行一輪巡檢流程：取消舊掛單、查餘額與 FRR、產生掛單計畫、掛單、落帳、送出通知。"""
        cancelled = self.client.cancel_active_offers("USD")
        if cancelled:
            # Bitfinex 取消掛單是非同步處理，回應成功不代表餘額已釋放；
            # 這裡稍等一下再查餘額，避免用到舊餘額把掛單金額算少。
            time.sleep(self.cancel_settle_seconds)

        balance_usd = self.client.get_available_balance("USD")
        frr = self.client.get_frr("USD")
        self.logger.info(f"目前可用 USD 餘額：{balance_usd}")
        self.logger.info(f"目前 FRR：{frr}")

        if frr is None or frr <= 0:
            # 略過也要寫狀態：機器人是活著且判斷正確的，心跳不該因此中斷。
            self.repository.save_state(last_action="FRR 無效，略過本輪")
            self._note_offers_absent("FRR 無效，本輪沒有掛單")
            raise SkipCycleError("FRR 無效（None 或非正值），跳過本輪，避免用錯誤利率掛單")

        plans = self.strategy.build_offer_plan(balance_usd, frr)
        if not plans:
            self.repository.save_state(last_frr=frr, last_action="可放貸金額不足，略過本輪")
            self._note_offers_absent(f"可放貸金額不足（目前 {balance_usd} USD），本輪沒有掛單")
            raise SkipCycleError("可放貸金額低於最低門檻或單筆最小量，跳過本輪")

        dry_run = False
        for plan in plans:
            self.logger.info(
                f"建立掛單方案：{plan.amount} {plan.currency}，利率 {plan.rate:.6f}，天期 {plan.duration} 天"
            )
            try:
                result = self.client.create_loan_offer(
                    plan.currency, plan.amount, plan.rate, plan.duration
                )
            except (RetryableError, FatalError) as exc:
                # 掛單 API 無法 rollback：同一輪若前幾筆已成功，錢就已經出去了。
                # 失敗這筆也要留痕，事後才對得出當下的真實狀態。
                self.repository.record_offer_failure(plan, str(exc))
                # 拒單很罕見（實單至今只發生過一次，見 D025），所以每次都推——
                # 這是少數「額度絕對值得花」的交易面事件。
                self._push_trade_event(
                    messages.offer_failed(plan, str(exc), retryable=isinstance(exc, RetryableError))
                )
                # 這一輪的掛單已經全被取消，而重掛失敗了：場上沒有我們的單。
                # 標成 False 是為了讓下一輪成功時推得出「掛單已重新上線」。
                self._offers_live = False
                raise
            self.logger.info(f"掛單結果：{result}")
            # dry-run 由交易所回應自己表明（`status: dry_run`），不必再從別處傳一個旗標
            # 進來——資料怎麼說就怎麼寫，少一條會走岔的路。
            if isinstance(result, dict) and result.get("status") == "dry_run":
                dry_run = True
            self.repository.record_offer(plan, result)

        self._note_offers_placed(plans, dry_run)
        total_amount = round(sum(plan.amount for plan in plans), 2)
        self.repository.save_state(
            last_frr=frr,
            last_action=f"掛出 {len(plans)} 筆掛單，合計 {total_amount} USD",
        )
        # 這裡刻意**不送 LINE**：例行巡檢結果只寫日誌。
        # LINE 免費方案是每月 200 則，而巡檢間隔 600 秒等於一天 144 輪——
        # 每輪推一則的話不到兩天就把整個月的額度用光，之後真正的故障告警
        # 一則都送不出去（見 DECISIONS.md D024）。
        self.logger.info(f"本輪巡檢完成：掛出 {len(plans)} 筆，合計 {total_amount} USD")

    def _push_trade_event(self, message: str) -> None:
        """送出一則交易面通知，並在日誌留下同一件事的單行版本。

        `push_trade_events` 是留給額度的安全閥：真的燒太快時可以只留系統面告警，
        交易面退回只寫日誌。日誌不受這個開關影響——**關掉的是通知，不是紀錄**。
        """
        first_line = message.splitlines()[0]
        self.logger.info(f"交易面事件：{first_line}")
        if self.push_trade_events:
            self.notifier.send(message)

    def _note_offers_placed(self, plans, dry_run: bool = False) -> None:
        """本輪掛單成功：只有「原本場上沒單 → 現在有了」才推。

        `None`（剛啟動）算成需要推，訊息會寫「啟動後首輪」——部署完最想確認的
        就是機器人回來了而且真的把單掛上去了。
        """
        if self._offers_live is not True:
            self._push_trade_event(
                messages.offers_placed(plans, first_cycle=self._offers_live is None, dry_run=dry_run)
            )
        self._offers_live = True

    def _note_offers_absent(self, reason: str) -> None:
        """本輪沒有掛單：只有「原本場上有單 → 現在沒了」才推。

        這一則是目前唯一能察覺「錢可能借出去了」的訊號。機器人還沒有查詢已借出部位的
        能力（TASKS.md P2-1），所以訊息只講事實、不寫死成「成交」——餘額歸零也可能是
        資金被搬到別的錢包。**猜錯一次，這個管道就再也不會被相信。**

        剛啟動（`None`）時不推：那代表我們沒看過「有單」的狀態，不算轉換。
        """
        if self._offers_live is True:
            self._push_trade_event(messages.offers_gone(reason))
        self._offers_live = False

    def run_forever(self) -> int:
        """啟動檢查後進入常駐主迴圈，回傳離開碼。"""
        try:
            if not self.client.test_connection():
                self.logger.error("啟動檢查失敗")
                # 落帳再退出：容器收掉之後日誌也可能一起看不到（見 D016），
                # DB 是唯一一定留得下來的地方，健康檢查與事後追查都靠它。
                self._record_exit_reason("啟動檢查失敗，機器人未進入主迴圈")
                self.notifier.send(messages.startup_check_failed("交易所連線或金鑰檢查沒有通過"))
                return EXIT_FATAL

            self.logger.info(f"進入常駐主迴圈，巡檢間隔 {self.interval_seconds} 秒")
            while True:
                try:
                    self.run_once()
                except SkipCycleError as exc:
                    # 略過不算失敗：能走到判斷這一步，代表交易所 API 本身是通的。
                    self.logger.info(f"本輪略過：{exc}")
                    self.failures.record_success()
                except RetryableError as exc:
                    self.logger.warning(f"暫時性錯誤，下一輪重試：{exc}")
                    self.failures.record_failure(str(exc))
                except FatalError as exc:
                    self.logger.error(f"致命錯誤，機器人即將停止：{exc}")
                    self._record_exit_reason(f"致命錯誤已停止：{exc}")
                    self.notifier.send(messages.fatal_error(str(exc)))
                    return EXIT_FATAL
                else:
                    self.failures.record_success()

                time.sleep(self.interval_seconds)
        except KeyboardInterrupt:
            self.logger.info("收到中斷訊號，機器人正常結束。")
            return EXIT_OK
        except Exception as exc:  # noqa: BLE001 - 最外層攔截，只為了留下痕跡再往下走
            # 沒被分類過的例外原本會直接把 traceback 印到 stderr，而容器的 stderr
            # 在這個部署環境裡拿不到（見 D016），等於崩潰現場完全消失。
            # 這裡改寫進日誌檔與 DB，兩者都掛載在主機上。
            self.logger.exception(f"未預期的例外，機器人即將停止：{exc}")
            self._record_exit_reason(f"未預期的例外已停止：{exc}")
            self.notifier.send(messages.unexpected_error(f"{type(exc).__name__}: {exc}"))
            return EXIT_UNEXPECTED
        finally:
            # 同 `_record_exit_reason` 的理由：DB 故障時 close() 也可能拋例外，
            # 而 finally 拋出的例外會取代原本的回傳值，離開碼直接變成 1 並印出
            # 一份跟真正死因無關的 traceback。收尾動作不該有這種話語權。
            try:
                self.repository.close()
            except Exception as exc:  # noqa: BLE001 - 收尾失敗只留痕，不影響離開碼
                self.logger.error(f"關閉資料庫連線失敗：{exc}")

    def _record_exit_reason(self, reason: str) -> None:
        """退出前把原因寫進 `bot_state`，寫不進去就只記日誌。

        三條退出路徑都是「先落帳、再通知、最後回傳離開碼」。問題在於**資料庫本身故障**
        （磁碟滿、DB 損毀、volume 掛載掉了）正是這個部署真實會發生的狀況之一
        ——M3 起部署一路失敗的根因就是主機端目錄不存在——而那時候 `save_state()`
        自己就會拋例外，後果是三層的：原始錯誤訊息遺失、後面的 `notifier.send()`
        不會執行、離開碼從刻意設計的 `EXIT_FATAL` 變成 `EXIT_UNEXPECTED`。
        `FatalError` 那條路徑更糟：新例外會被外層的 `except Exception` 接住，
        直接被誤判成「未預期的例外」。

        落帳是輔助手段，不該反過來決定機器人怎麼退出，更不該蓋掉真正的死因
        ——而那正是最需要看到它的時候（見 TASKS.md A3）。
        """
        try:
            self.repository.save_state(last_action=reason)
        except Exception as exc:  # noqa: BLE001 - 落帳失敗不能影響離開碼與通知
            self.logger.error(f"退出前落帳失敗，原始原因仍為「{reason}」，落帳錯誤：{exc}")
