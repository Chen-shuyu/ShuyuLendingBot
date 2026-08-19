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
from datetime import datetime
from typing import Optional

from notify import messages
from utils import clock
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
        rate_tolerance_pct: float = 2.0,
        queue_clear_usd_per_hour: float = 540_000.0,
    ):
        self.logger = logger
        self.notifier = notifier
        self.strategy = strategy
        self.client = client
        self.repository = repository
        self.interval_seconds = int(interval_seconds)
        self.cancel_settle_seconds = int(cancel_settle_seconds)
        self.push_trade_events = bool(push_trade_events)
        # 場上掛單與新計畫差多少以內算「沒變」，用來決定要不要重掛（見 `_plans_match`）。
        self.rate_tolerance_pct = float(rate_tolerance_pct)
        # 排隊的錢被吃掉的速率，用來把「前方多少錢」換算成「要等多久」
        # （見 `_cheaper_repost_is_not_worth_it`）。**只有一個校準樣本**，
        # 目前僅用於分母差異不大的比較，敏感度低；D032 會把它換成每輪自己算。
        self.queue_clear_usd_per_hour = float(queue_clear_usd_per_hour)
        self.failures = FailureTracker(logger, notifier, repository, alert_after_failures)
        # 場上有沒有我們的掛單：True 有、False 沒有、None 還不知道（剛啟動）。
        # 交易面通知推的是**這個值的變化**，不是每輪的結果——每輪全取消重掛若每次都推，
        # 一天 144 則、不到兩天就把每月 200 則的額度燒光（見 D024）。
        # 狀態只放記憶體、不落 DB：重啟後回到 None，下一次掛單成功會推一則
        # 「啟動後首輪」——那正是部署完最想確認的事，不算浪費額度。
        self._offers_live = None

    def run_once(self) -> None:
        """執行一輪巡檢：對帳部位、查市場、決定要不要重掛、掛單、落帳、送出通知。

        **順序上有一件事必須最先做**：核對已借出部位。取消掛單會讓場上狀態改變，
        先動手再對帳的話，「這一輪成交了嗎」就永遠答不出來。
        """
        filled = self._sync_positions()

        # 場上現有的掛單。**先看清楚再決定要不要動它**——這一步是後面
        # 「利率沒變就不重掛」的依據，而那正是保住排隊位置的關鍵（見 D030）。
        existing = self.client.get_active_offers("USD")

        balance_usd = self.client.get_available_balance("USD")
        frr = self.client.get_frr("USD")
        self.logger.info(f"目前可用 USD 餘額：{balance_usd}")
        self.logger.info(f"目前 FRR：{frr}")

        if frr is None or frr <= 0:
            # 略過也要寫狀態：機器人是活著且判斷正確的，心跳不該因此中斷。
            self.repository.save_state(last_action="FRR 無效，略過本輪")
            self._note_offers_absent("FRR 無效，本輪沒有掛單", explained=filled)
            raise SkipCycleError("FRR 無效（None 或非正值），跳過本輪，避免用錯誤利率掛單")

        book = self._fetch_book()
        trades = self._fetch_trades()
        candles = self._fetch_candles()
        self._log_market_rate(trades)

        # 掛在場上的錢也是我們的錢。只看 `get_available_balance()` 的話，單子一掛出去
        # 餘額就變成 0，策略會以為沒錢可放而回傳空計畫——於是每一輪都在「取消才有錢、
        # 有錢才算得出計畫」之間打轉，等於強迫自己每輪都重掛。
        committed_usd = sum(float(offer["amount"]) for offer in existing)
        disposable_usd = balance_usd + committed_usd
        plans = self.strategy.build_offer_plan(disposable_usd, frr, book, trades, candles)
        self._log_pricing_rationale()

        if not plans:
            skip_reason = self._strategy_skip_reason()
            if existing:
                # 策略說「這個市場現在不值得掛」，但場上已經有單了。
                # **不要撤**：那張單是用更早的（也就是更好的）市場條件掛出去的，
                # 撤掉只會把排隊位置還給市場，換來一輪空手。
                self.repository.save_state(
                    last_frr=frr, last_action=f"維持場上 {len(existing)} 筆既有掛單，本輪不重掛"
                )
                self.logger.info(
                    f"本輪不產生新計畫（{skip_reason}），"
                    f"但場上已有 {len(existing)} 筆掛單，維持不動以保住排隊位置。"
                )
                raise SkipCycleError("本輪無新掛單計畫，維持場上既有掛單")

            # **不要再寫死「可放貸金額不足」**（TASKS.md A1）。策略有六個出口會回傳
            # 空計畫，其中五個跟金額無關；最糟的是「價格低於年化 8% 地板」——
            # 帳上有 344 USD 卻寫「可放貸金額不足（目前 344.3 USD）」，
            # 自相矛盾，還把人指向「錢為什麼不見了」這個完全錯誤的方向。
            self.repository.save_state(last_frr=frr, last_action=f"本輪未掛單：{skip_reason}")
            self._note_offers_absent(f"本輪沒有掛單：{skip_reason}", explained=filled)
            raise SkipCycleError(f"本輪不掛單：{skip_reason}")

        self._log_queue_position(book, plans)
        # **在任何「要不要動這張單」的判斷之前先量測。** 閒置時間是這些判斷的輸入，
        # 放在後面的話，凡是提早 return 的路徑（維持不動、重掛不划算）就永遠量不到
        # ——而那正好是單子閒置最久的那些輪次（D038）。
        self._log_idle_time(existing)
        ahead_of_live = self._queue_ahead_of_live(book, existing)
        if ahead_of_live is not None:
            self.logger.info(f"場上掛單排隊位置：前方 {ahead_of_live:,.0f} USD")

        if existing and self._plans_match(existing, plans):
            # **這一輪什麼都不做才是對的。** 同利率下是時間優先（先掛先成交），
            # 取消重掛會把排隊位置歸零重來。以 600 秒巡檢一輪計，等於一天把自己
            # 送回隊伍末端 144 次——而這個價位的成交本來就是陣發的，
            # 每次歸零都可能正好錯過那一波。
            self.repository.save_state(
                last_frr=frr, last_action=f"掛單條件未變，維持場上 {len(existing)} 筆不動"
            )
            self.logger.info(
                f"掛單條件與場上 {len(existing)} 筆一致（利率容差 {self.rate_tolerance_pct}%），"
                "維持不動以保住排隊位置。"
            )
            return

        # **用確定的利息去換估出來的速度，要先證明划得來。** 這是 2026-08-16 19:31 的
        # 形狀：低價牆把候選價位往下拖，機器人送出取消，25 秒後那張單成交——
        # 是市場先一步吃單才沒把第一筆成交砍掉（D031／D034）。
        not_worth_it = self._cheaper_repost_is_not_worth_it(book, existing, plans)
        if not_worth_it:
            self.repository.save_state(
                last_frr=frr,
                last_action=f"往下重掛不划算，維持場上 {len(existing)} 筆不動",
            )
            self.logger.info(
                f"候選價位比場上那張單低，而排隊位置的改善補不回少收的利息"
                f"（{not_worth_it}），維持不動。"
            )
            return

        cancelled = self.client.cancel_active_offers("USD")
        if cancelled:
            # Bitfinex 取消掛單是非同步處理，回應成功不代表餘額已釋放；
            # 這裡稍等一下再查餘額，避免用到舊餘額把掛單金額算少。
            time.sleep(self.cancel_settle_seconds)

            # **等完還要問一次「單子真的離場了嗎」，不能用餘額回推。**
            # 這兩件事會分岔：2026-08-16 19:31 取消送出後餘額確實沒回來，
            # 但原因不是「還沒生效」而是「那張單根本沒被取消掉，25 秒後成交了」（D031）。
            # 只看餘額的話兩種情況長得一模一樣，而處置完全相反——
            # 單子還在場上時再掛一筆就是雙倍曝險。
            still_live = self.client.get_active_offers("USD")
            if still_live:
                self.repository.save_state(
                    last_frr=frr,
                    last_action=f"取消未生效，場上仍有 {len(still_live)} 筆掛單，本輪不重掛",
                )
                self.logger.warning(
                    f"已送出取消，但場上仍有 {len(still_live)} 筆掛單（可能尚未生效，"
                    "也可能已經成交）。本輪不重掛，等下一輪重新判斷。"
                )
                raise SkipCycleError("取消尚未生效，場上仍有掛單，本輪不重掛")

            # 取消後一定要用**真實餘額**重算，不能沿用 `disposable_usd`：
            # 那是估計值，而掛單金額只要多一分錢，交易所就會拒絕整筆（D025）。
            balance_usd = self.client.get_available_balance("USD")
            self.logger.info(f"取消後可用 USD 餘額：{balance_usd}")
            plans = self.strategy.build_offer_plan(balance_usd, frr, book, trades, candles)
            if not plans:
                self.repository.save_state(
                    last_frr=frr, last_action="取消後可放貸金額不足，本輪沒有重掛"
                )
                self._note_offers_absent(
                    f"取消後可放貸金額不足（目前 {balance_usd} USD），本輪沒有重掛",
                    explained=filled,
                )
                raise SkipCycleError("取消舊掛單後可放貸金額不足，本輪不重掛")

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
            self._record_wait_forecast(result)

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

    def _sync_positions(self) -> bool:
        """核對已借出部位，推出成交／收回通知。回傳「本輪是否偵測到新成交」。

        這是 TASKS.md P2-1：在它之前，錢借出去之後餘額歸零，機器人只會寫一句
        「可放貸金額不足，略過本輪」——**跟錢包本來就是空的一模一樣**。
        沒有通知、DB 也沒有任何一筆記錄說「這筆借出去了」，
        於是機器人在賺錢還是在空轉，從外面完全分不出來。

        成交每筆都推：它罕見、而且是這個專案存在的理由，屬於「額度絕對值得花」
        的事件（TASKS.md P2-4 的額度分配）。
        """
        positions = self.client.get_active_positions("USD")
        changes = self.repository.sync_positions("USD", positions)

        opened = changes["opened"]
        closed = changes["closed"]

        if opened:
            total = sum(float(item["amount"]) for item in opened)
            self.logger.info(
                f"偵測到新的已借出部位 {len(opened)} 筆，合計 {total:.2f} USD——資金已借出。"
            )
            self._push_trade_event(messages.positions_opened(opened))

        if closed:
            total = sum(float(item["amount"]) for item in closed)
            self.logger.info(
                f"已借出部位收回 {len(closed)} 筆，合計 {total:.2f} USD——資金已回到融資錢包。"
            )
            self._push_trade_event(messages.positions_closed(closed))

        return bool(opened)

    def _fetch_book(self):
        """取得市場深度；策略用不到就不打這個端點。

        用不到卻照打，等於白白多一個會失敗的地方——而這一支是每輪都會執行的路徑。
        """
        if not getattr(self.strategy, "requires_book", False):
            return None
        book = self.client.get_funding_book("USD")
        if not book:
            self.logger.warning("市場深度查詢回傳空清單，本輪將沒有掛單計畫。")
        return book

    def _fetch_candles(self):
        """取得利率 K 線；策略用不到就不打這個端點（同 `_fetch_book()` 的理由）。"""
        if not getattr(self.strategy, "requires_candles", False):
            return None
        candles = self.client.get_rate_candles(
            "USD",
            period=getattr(self.strategy, "offer_period", 2),
            timeframe=getattr(self.strategy, "candle_timeframe", "1h"),
            limit=getattr(self.strategy, "candle_limit", 240),
        )
        if not candles:
            self.logger.warning("利率 K 線查詢回傳空清單，本輪將沒有掛單計畫。")
        return candles

    def _fetch_trades(self):
        """取得近期成交紀錄；策略用不到就不打這個端點（同 `_fetch_book()` 的理由）。"""
        if not getattr(self.strategy, "requires_trades", False):
            return None
        # 抓幾筆由策略決定：太少會涵蓋不到足夠時間而算不出常態成交價
        # （實測 1000 筆在活躍時段只有 1.2 分鐘），策略才知道自己要多少。
        trades = self.client.get_recent_trades("USD", limit=getattr(self.strategy, "trade_limit", 10_000))
        if not trades:
            self.logger.warning("近期成交查詢回傳空清單，本輪將沒有掛單計畫。")
        return trades

    def _log_pricing_rationale(self) -> None:
        """把「這個價位是怎麼選出來的」寫進日誌（TASKS.md A1）。

        **這一行的存在理由，是 D033 的教訓在新定價鏈上原封不動重演了一次。**
        當時用半價把 344 USD 借出去，事後翻日誌只有「掛出 344.30 USD，
        利率 0.000150」——沒有任何數字能看出那是半價，於是補了 `_log_market_rate()`。
        定價基準換成期望值（D035）之後，日誌又變成只看得到結果、看不到推導：
        等待估計多久、窗內命中幾次、實質年化多少，一個都沒有。

        策略沒有這個能力就靜靜跳過——`frr_plus` 與 `orderbook_depth` 都沒有
        期望值評估，硬要它們回答只會多一個會爆的地方。
        """
        describe = getattr(self.strategy, "describe_decision", None)
        if describe is None:
            return
        line = describe()
        if line:
            self.logger.info(line)

    def _log_idle_time(self, existing) -> None:
        """把「場上這張單已經掛了多久」寫進日誌，並與掛單當初的預估對照（D038）。

        **為什麼需要這一行**：2026-08-19 那張單掛了 18 小時沒成交，而這段期間
        每一輪的日誌都長得一模一樣——「維持不動以保住排隊位置」。閒置資金的年化是
        **0%**，這是唯一一種「什麼都沒發生但確定在虧」的狀態，卻是整個系統裡
        唯一沒有任何一行日誌在計時的東西（D037 已預警，隔天就成真）。

        **這裡只量測，不做任何決策**：要不要因為等太久而降價是策略問題，
        得先有這些數字才談得上（D036 的順序）。直接拍一個「超過 N 小時就降價」
        的常數，就是 `target_queue_usd` 的死法。
        """
        for offer in existing:
            created_ms = offer.get("created_at_ms")
            if created_ms is None:
                # 講「不知道」，不要用本輪時間硬湊一個看起來很小的閒置時數。
                self.logger.info(
                    f"場上掛單 #{offer.get('id')} 沒有建立時間，無法計算已閒置多久。"
                )
                continue

            created_at = datetime.fromtimestamp(created_ms / 1000, tz=clock.get_timezone())
            idle_hours = (clock.now() - created_at).total_seconds() / 3600
            # 閒置成本用金額講，不然「18 小時」對人來說沒有重量。
            # 這段時間若已借出去、以這張單自己的利率計，本來會賺到的利息。
            forgone = offer["amount"] * offer["rate"] * idle_hours / 24

            forecast = self.repository.get_wait_forecast(offer.get("id"))
            if not forecast:
                self.logger.info(
                    f"場上掛單已閒置 {idle_hours:.1f} 小時"
                    f"（機會成本約 {forgone:.4f} USD），沒有留下當初的等待預估。"
                )
                continue

            if idle_hours > forecast["p75_hours"]:
                verdict = "已超出當初預估的四分之三分位，等待估計偏樂觀"
            elif idle_hours > forecast["median_hours"]:
                verdict = "已超過當初預估的中位數"
            else:
                verdict = "仍在當初預估的中位數之內"

            self.logger.info(
                f"場上掛單已閒置 {idle_hours:.1f} 小時（機會成本約 {forgone:.4f} USD）；"
                f"掛單當下預估 平均 {forecast['mean_hours']:.1f}h／"
                f"中位數 {forecast['median_hours']:.1f}h／"
                f"四分之三在 {forecast['p75_hours']:.1f}h 內 → {verdict}。"
            )

    def _record_wait_forecast(self, result) -> None:
        """把掛單當下的等待預估落 DB，供事後校準（D038）。

        策略沒有這個能力就靜靜跳過——`frr_plus` 與 `orderbook_depth` 不做期望值評估，
        硬要它們回答只會多一個會爆的地方（與 `_log_pricing_rationale()` 同一個判斷）。

        **落帳失敗不能拖垮掛單**：錢已經掛出去了，這裡只是校準資料。
        寫不進去就記一行警告，讓它變成看得見的缺口而不是靜默的空白。
        """
        forecast_of = getattr(self.strategy, "chosen_forecast", None)
        if forecast_of is None or not isinstance(result, dict):
            return
        offer_id = result.get("id")
        if offer_id is None:
            return
        forecast = forecast_of()
        if not forecast:
            return
        try:
            self.repository.record_wait_forecast(offer_id, forecast)
        except Exception as exc:  # noqa: BLE001 - 校準資料不值得讓一輪巡檢失敗
            self.logger.warning(f"掛單 #{offer_id} 的等待預估寫入失敗，事後無法校準：{exc}")

    def _strategy_skip_reason(self) -> str:
        """策略為什麼不掛單。策略沒說就退回一句中性的描述。

        **退路刻意寫得中性**：舊版寫死「可放貸金額不足」，而那句話在六個出口
        裡有五個是錯的。答不出來的時候，講「不知道」遠比講一個具體但錯誤的原因好
        ——後者會讓人朝錯的方向查（D026 的同一族問題）。
        """
        reason = getattr(self.strategy, "last_skip_reason", None)
        return reason or "策略未產生掛單計畫（未提供原因）"

    def _log_market_rate(self, trades) -> None:
        """把「借款人現在實際付多少」寫進日誌，與掛單利率對照。

        沒有這一行，2026-08-16 夜間那次事故在日誌上完全看不出異常：機器人只寫了
        「掛出 344.30 USD，利率 0.000150」，而當時市場成交價是 0.00026——
        **日誌裡沒有任何一個數字能讓人看出這個價位是半價**（D033）。
        """
        market_rate = getattr(self.strategy, "market_rate", None)
        if market_rate is None or not trades:
            return
        rate = market_rate(trades)
        if rate is None:
            self.logger.warning("近期成交樣本不足，無法算出常態成交價，本輪不掛單。")
            return
        self.logger.info(f"市場常態成交價：{rate:.8f}/日（年化 {rate * 365 * 100:.2f}%）")

    def _queue_ahead(self, book, rate, period) -> Optional[float]:
        """掛在 `rate`／`period` 時前面排著多少錢。拿不到就回 `None`。

        `same_period` 與 `all_periods` 取**小的那個**（也就是同天期）。
        兩個數字誰才對還沒有定論（見 `describe_queue`），而這裡只拿它做**比較**，
        兩邊用同一把尺，偏差會抵銷掉大半。
        """
        describe = getattr(self.strategy, "describe_queue", None)
        if describe is None or not book:
            return None
        queue = describe(book, float(rate), int(period))
        return min(float(queue["same_period"]), float(queue["all_periods"]))

    def _queue_ahead_of_live(self, book, existing) -> Optional[float]:
        """**場上那張單**前面還排著多少錢——不是本輪候選價位的，是已經在排隊的那張。

        這個區別是 D031 的核心。`_log_queue_position()` 描述的一直是**候選價位**
        （`plans[0].rate`），而「我們快成交了嗎」是**場上那張單**的性質，兩者在
        市場變動時會指向完全相反的方向：低價牆一出現，候選價位會被拉到簿子底端，
        而場上那張既有的單反而變成隊伍最前面最快成交的一張。

        取**多筆掛單裡利率最低的那筆**：利率越低排得越前面，最先成交的一定是它。
        """
        if not existing:
            return None
        front = min(existing, key=lambda offer: float(offer["rate"]))
        return self._queue_ahead(book, float(front["rate"]), int(front["period"]))

    def _cheaper_repost_is_not_worth_it(self, book, existing, plans) -> Optional[str]:
        """**把價格往下調**的重掛划不划算：划不來就回傳一句說明，否則回 `None`。

        ## 為什麼只管往下這個方向

        排隊金額對利率是單調的——掛得越便宜，排在前面的錢越少。所以重掛**永遠**是
        一個取捨，不存在「兩邊都更差」這種好判斷的情況。但兩個方向的不確定性擺放
        方式相反：

        - **往下調**：放棄的利息是**確定的**，換來的速度是**估的**
        - **往上調**：多賺的利息是**確定的**，付出的速度是**估的**

        而「估的」那一半正是目前最不可靠的東西：把排隊金額換算成等待時間只有
        **一個校準樣本**，而且實際比估計慢 1.7 倍（D031）。所以只在「不可靠的那半邊
        是行動的理由」時才要求它先過關；反過來時讓確定的那半邊說了算。
        這就是 D031「判斷不出來時偏向代價小的那一邊」按方向拆開之後的樣子。

        ## 判準是推導出來的，不是拍板的

        兩條路比的是**單位時間報酬**：`利息 ÷ (等待 + 借出期間)`。設 `r` 為利率、
        `W` 為等待天數、`P` 為天期，重掛較好的條件是

            r_new / (W_new + P) > r_live / (W_live + P)

        `W = 前方金額 ÷ 隊列消化速率`。以 2026-08-16 深夜的簿子代入，等待多在 0～6.4
        小時之間，而 `P` 是 48 小時——**分母幾乎不動**，於是利率那一項壓倒性地決定
        結果。把 19:31 那道牆放回簿子重演（當晚的候選價位沒有進日誌，這裡餵入牆價
        0.00014999，也就是 21:31 真的掛出去的那個價）：利率掉 40%，換來的是等待從
        3.9 小時降到 0——**在 48 小時的天期面前，省下那 3.9 小時遠遠補不回四成利息**。

        **這不是 D032 的替代品**：真正的期望值計算還要處理天期選擇、爆發桶剔除與
        持續校準（`queue_clear_usd_per_hour` 現在只有一個樣本）。這裡只用它最不需要
        精度的那一段——分母差異小的時候，結論對速率估得準不準並不敏感。

        金額變多時一律不否決：那代表錢包裡有新的錢要投入，而 `spread_count=1` 時
        重掛是唯一的投入手段，少賺的價差遠小於讓那筆錢繼續空轉。
        """
        if not existing or not plans or not book:
            return None

        live = min(existing, key=lambda offer: float(offer["rate"]))
        candidate = min(plans, key=lambda plan: plan.rate)

        live_total = sum(float(offer["amount"]) for offer in existing)
        plan_total = sum(plan.amount for plan in plans)
        if plan_total > live_total + max(1.0, live_total * 0.01):
            return None

        live_rate = float(live["rate"])
        if candidate.rate >= live_rate:
            return None

        ahead_live = self._queue_ahead(book, live_rate, int(live["period"]))
        ahead_candidate = self._queue_ahead(book, candidate.rate, candidate.duration)
        if ahead_live is None or ahead_candidate is None or self.queue_clear_usd_per_hour <= 0:
            return None

        def daily_yield(rate, ahead, period):
            wait_days = ahead / self.queue_clear_usd_per_hour / 24
            return rate * period / (wait_days + period)

        live_yield = daily_yield(live_rate, ahead_live, int(live["period"]))
        candidate_yield = daily_yield(candidate.rate, ahead_candidate, candidate.duration)
        if candidate_yield > live_yield:
            return None

        return (
            f"利率 {live_rate:.8f} → {candidate.rate:.8f}、"
            f"前方 {ahead_live:,.0f} → {ahead_candidate:,.0f} USD，"
            f"單位時間報酬 {live_yield:.10f} → {candidate_yield:.10f}"
        )

    def _log_queue_position(self, book, plans) -> None:
        """把「**本輪候選價位**掛下去時前面排了多少錢」寫進日誌，同天期與全天期各一份。

        **主詞是候選價位，不是場上那張單。** 這兩個數字在 2026-08-16 19:31 被讀成
        後者，於是「前方 0 USD」被當成「我們排到第一位了」——實際上它講的是
        「新算出來的價位落在簿子最低檔」，而當時舊版用 `<` 比較，最低檔自己那筆
        沒被算進去才會顯示 0。場上那張單的排隊位置請看 `_queue_ahead_of_live()`。

        兩個數字都留，是為了**讓第一筆真實成交來裁決一個還沒驗證的假設**：
        不同天期的掛單到底有沒有在同一個隊伍裡排。策略目前採保守解讀（全天期一起算），
        若實際成交速度明顯快過這個估計，就代表同天期那個數字才是對的。
        沒有這兩行，事後只會看到「成交了」，什麼都學不到。
        """
        if not book or not plans:
            return
        describe = getattr(self.strategy, "describe_queue", None)
        if describe is None:
            return
        queue = describe(book, plans[0].rate)
        self.logger.info(
            f"掛單排隊位置估計：同天期前方 {queue['same_period']:,.0f} USD、"
            f"全天期前方 {queue['all_periods']:,.0f} USD"
        )

    def _plans_match(self, existing, plans) -> bool:
        """場上現有掛單與本輪計畫是否「實質相同」（相同就不必重掛）。

        **一定要有容差，不能比對相等**：市場價位每輪都會有小數點後幾位的漂移，
        逐位元比對等於每輪都判定「不一樣」，這條保護就形同虛設——
        P2-4 實作交易面通知時已經踩過同一個坑（見 D029），那次是把額度燒光，
        這次會把排隊位置燒光。
        """
        if len(existing) != len(plans):
            return False

        existing_sorted = sorted(existing, key=lambda offer: float(offer["rate"]))
        plans_sorted = sorted(plans, key=lambda plan: plan.rate)

        for offer, plan in zip(existing_sorted, plans_sorted):
            if int(offer["period"]) != int(plan.duration):
                return False
            if plan.rate <= 0:
                return False
            rate_drift_pct = abs(float(offer["rate"]) - plan.rate) / plan.rate * 100
            if rate_drift_pct > self.rate_tolerance_pct:
                return False
            # 金額容差取「1 USD」與「1%」的較大者：小額時 1 USD 才有意義，
            # 金額變大之後固定值會過度敏感。
            amount_tolerance = max(1.0, plan.amount * 0.01)
            if abs(float(offer["amount"]) - plan.amount) > amount_tolerance:
                return False
        return True

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

    def _note_offers_absent(self, reason: str, explained: bool = False) -> None:
        """本輪沒有掛單：只有「原本場上有單 → 現在沒了」才推。

        `explained=True` 代表**本輪已經查明掛單消失的原因就是成交**，
        `_sync_positions()` 已經推過一則更準確的「資金已借出」。這時再推一則
        「掛單已不在場上」只是把同一件事講第二遍，白白多燒一則額度
        ——每月只有 200 則（D024）。

        剛啟動（`None`）時不推：那代表我們沒看過「有單」的狀態，不算轉換。
        """
        if self._offers_live is True and not explained:
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
