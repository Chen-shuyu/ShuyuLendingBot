# -*- coding: utf-8 -*-
"""`notify/messages.py` 的單元測試：三段式格式與圖示規則。

這些測試釘住的是**格式契約**而不是措辭：第一行必須帶得走結論、時間永遠在第一個欄位、
最後一行只有兩種可能。措辭改了不該讓測試紅燈，但格式被破壞一定要當場紅燈——
因為格式壞掉的代價是「手機上分不出哪則要處理」，而那不會有人回報給我們。
"""

from strategies.base import OfferPlan

from notify import messages


def plan(amount=160.0, rate=0.000273, duration=2, currency="USD"):
    return OfferPlan(currency=currency, amount=amount, rate=rate, duration=duration)


class TestThreePartStructure:
    """每一則訊息都是：結論行 → 欄位若干行 → 二選一的結尾行。"""

    def test_first_line_carries_icon_category_and_conclusion(self):
        text = messages.build("系統", "機器人已停止", {"原因": "金鑰無效"}, level="CRITICAL")
        first_line = text.splitlines()[0]

        assert first_line == "🔴【系統】機器人已停止"

    def test_time_is_always_the_first_field(self):
        text = messages.build("交易", "掛單已重新上線", {"金額": "160.00 USD"})
        assert text.splitlines()[1].startswith("時間：")

    def test_timestamp_carries_offset(self):
        """時區偏移一定要在（D028）：日誌曾經混過兩個時區，訊息不該讓人自己猜。"""
        text = messages.build("系統", "測試")
        time_line = text.splitlines()[1]

        assert "+" in time_line or "-" in time_line

    def test_last_line_is_one_of_exactly_two(self):
        needs = messages.build("系統", "壞了", action_required=True)
        no_need = messages.build("系統", "沒事", action_required=False)

        assert needs.splitlines()[-1] == messages.FOOTER_ACTION_REQUIRED
        assert no_need.splitlines()[-1] == messages.FOOTER_NO_ACTION

    def test_fields_keep_insertion_order(self):
        text = messages.build("交易", "掛單", {"金額": "1", "利率": "2", "天期": "3"})
        labels = [line.split("：")[0] for line in text.splitlines()[1:-1]]

        assert labels == ["時間", "金額", "利率", "天期"]

    def test_none_valued_fields_are_dropped(self):
        """寧可少一行，也不要出現「原因：None」這種讓人以為程式壞了的輸出。"""
        text = messages.build("系統", "啟動檢查失敗", {"原因": None, "影響": "沒有掛單"})

        assert "None" not in text
        assert "影響：沒有掛單" in text


class TestIconRules:
    """正常事件看分類、異常事件看等級——只有五個圖示，不要一個事件配一個。"""

    def test_normal_events_use_category_icon(self):
        assert messages.icon("系統", "INFO") == "🔵"
        assert messages.icon("交易", "INFO") == "💰"
        assert messages.icon("收益", "INFO") == "📊"

    def test_abnormal_events_use_level_icon_regardless_of_category(self):
        assert messages.icon("系統", "CRITICAL") == "🔴"
        assert messages.icon("交易", "CRITICAL") == "🔴"
        assert messages.icon("交易", "ERROR") == "🟠"
        assert messages.icon("收益", "WARNING") == "🟡"

    def test_unknown_category_falls_back_instead_of_raising(self):
        """通知層自己不該是壞掉的原因（與 `LineNotifier.send()` 同一個原則）。"""
        assert messages.icon("沒看過的分類", "INFO") == "🔵"


class TestRateFormatting:
    def test_shows_daily_and_annualised(self):
        """只給日利率看不出划不划算，只給年化又對不上交易所畫面。"""
        text = messages.format_rate(0.000273)

        assert "0.000273" in text
        assert "9.96%" in text  # 0.000273 × 365 × 100

    def test_amount_has_thousands_separator_and_currency(self):
        assert messages.format_amount(1234.5, "USD") == "1,234.50 USD"


class TestSystemEvents:
    def test_fatal_error_demands_human_action(self):
        text = messages.fatal_error("API 金鑰無效")

        assert text.startswith("🔴【系統】")
        assert "API 金鑰無效" in text
        assert text.endswith(messages.FOOTER_ACTION_REQUIRED)

    def test_fatal_error_says_it_will_not_restart_itself(self):
        """離開碼 2 被 `RestartPreventExitStatus=2` 擋下，人不介入就不會好（D017）。"""
        assert "不會自行重啟" in messages.fatal_error("金鑰無效")

    def test_unexpected_error_says_systemd_will_retry(self):
        """與致命錯誤的差別就在這句：這種還有機會自己好。"""
        assert "自動重啟" in messages.unexpected_error("KeyError: 'rate'")

    def test_recovery_needs_no_action(self):
        text = messages.recovered()

        assert text.startswith("🔵【系統】")
        assert text.endswith(messages.FOOTER_NO_ACTION)

    def test_consecutive_failures_reports_count_and_reason(self):
        text = messages.consecutive_failures(3, "查詢餘額逾時")

        assert "3 輪" in text
        assert "查詢餘額逾時" in text
        assert text.endswith(messages.FOOTER_ACTION_REQUIRED)


class TestTradeEvents:
    def test_single_offer_is_flattened(self):
        """單筆是常態（160 USD 掛不出第二筆），攤平寫比逐筆列好讀。"""
        text = messages.offers_placed([plan()])

        assert "金額：160.00 USD" in text
        assert "天期：2 天" in text
        assert "筆數" not in text

    def test_multiple_offers_are_listed_one_by_one(self):
        text = messages.offers_placed([plan(amount=200.0), plan(amount=100.0, rate=0.0003)])

        assert "筆數：2 筆" in text
        assert "合計：300.00 USD" in text
        assert "第 1 筆：" in text
        assert "第 2 筆：" in text

    def test_first_cycle_is_labelled(self):
        """部署完最想確認的就是「機器人回來了而且真的掛上去了」。"""
        assert "啟動後首輪" in messages.offers_placed([plan()], first_cycle=True)
        assert "重新上線" in messages.offers_placed([plan()], first_cycle=False)

    def test_dry_run_is_marked(self):
        """不標的話會讓人以為錢已經在市場上了。"""
        assert "dry-run" in messages.offers_placed([plan()], dry_run=True)
        assert "dry-run" not in messages.offers_placed([plan()], dry_run=False)

    def test_offers_gone_never_claims_a_fill(self):
        """機器人還沒有查詢已借出部位的能力（P2-1），不能把餘額歸零寫死成「成交」。

        猜錯一次——例如其實是資金被搬到別的錢包——這個管道就再也不會被相信。
        """
        text = messages.offers_gone("可放貸金額不足（目前 0.0 USD），本輪沒有掛單")

        assert "掛單已不在場上" in text
        assert "可能" in text
        assert "成交了" not in text.splitlines()[0]

    def test_rejected_offer_says_whether_it_will_retry(self):
        retryable = messages.offer_failed(plan(), "逾時", retryable=True)
        fatal = messages.offer_failed(plan(), "餘額不足", retryable=False)

        assert "自動重算金額並重試" in retryable
        assert retryable.endswith(messages.FOOTER_NO_ACTION)
        assert fatal.endswith(messages.FOOTER_ACTION_REQUIRED)


class TestPositionEvents:
    """成交與收回（TASKS.md P2-1／P2-4）。

    成交是這個專案存在的理由，也是最值得花額度的一則——在成交偵測做出來之前，
    這件事發生時機器人只會寫「可放貸金額不足，略過本輪」。
    """

    @staticmethod
    def position(amount=160.0, rate=0.00025, period=2):
        return {"id": "1", "amount": amount, "rate": rate, "period": period}

    def test_opened_leads_with_the_conclusion(self):
        text = messages.positions_opened([self.position()])
        first_line = text.splitlines()[0]

        assert first_line.startswith("💰【交易】")
        assert "借出" in first_line

    def test_opened_shows_amount_rate_and_period(self):
        text = messages.positions_opened([self.position(amount=160.0, rate=0.00025, period=2)])

        assert "160.00 USD" in text
        assert "0.000250/日" in text
        assert "年化 9.12%" in text
        assert "2 天" in text

    def test_opened_can_report_remaining_balance(self):
        text = messages.positions_opened([self.position()], balance_usd=184.12)
        assert "剩餘可放貸：184.12 USD" in text

    def test_multiple_positions_are_listed(self):
        text = messages.positions_opened([self.position(amount=150.0), self.position(amount=194.0)])

        assert "筆數：2 筆" in text
        assert "合計：344.00 USD" in text
        assert "第 1 筆" in text and "第 2 筆" in text

    def test_closed_says_what_happens_next(self):
        text = messages.positions_closed([self.position()])

        assert text.splitlines()[0].startswith("💰【交易】")
        assert "收回" in text
        assert "下一輪會重新掛單" in text

    def test_both_are_no_action_required(self):
        for text in (messages.positions_opened([self.position()]),
                     messages.positions_closed([self.position()])):
            assert text.splitlines()[-1] == messages.FOOTER_NO_ACTION

    def test_accepts_database_rows_not_just_api_dicts(self):
        """收回的部位是從 DB 讀回來的，欄位型別可能是字串——不該因此炸掉。"""
        row = {"id": "1", "amount": "160.0", "rate": "0.00025", "period": "2"}
        assert "160.00 USD" in messages.positions_closed([row])


class TestOffersGoneAfterFillDetection:
    def test_states_that_a_fill_was_ruled_out(self):
        """有了成交偵測之後，這則訊息的意思變窄也變準了。"""
        text = messages.offers_gone("可放貸金額不足")

        assert "不是成交" in text
        assert "餘額被移走" in text
