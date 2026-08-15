# -*- coding: utf-8 -*-
"""`BotEngine.run_once()` 的功能測試：一整輪巡檢的流程與落帳。

用真的策略層與真的 SQLite，只把交易所換成替身——要驗證的是「各步驟有沒有
照順序發生、資料有沒有正確落地」，而不是單一函式的計算結果。
"""

import pytest

from core import bot_engine
from core.bot_engine import BotEngine
from strategies.frr_plus import FrrPlusStrategy
from utils.exceptions import FatalError, RetryableError, SkipCycleError


def run_once(logger, notifier, strategy, client, repository, cancel_settle_seconds=3):
    """組一台引擎跑單輪，讓下面的測試專注在流程與落帳本身。"""
    BotEngine(
        logger,
        notifier,
        strategy,
        client,
        repository,
        cancel_settle_seconds=cancel_settle_seconds,
    ).run_once()


class FakeClient:
    """可設定餘額、FRR、取消結果與掛單行為的交易所替身。"""

    def __init__(self, balance=600.0, frr=0.0002, cancelled=None, offer_effects=None):
        self.balance = balance
        self.frr = frr
        self.cancelled = cancelled if cancelled is not None else []
        # offer_effects：每次掛單要拋的例外或回傳值；不設定就一律成功
        self.offer_effects = list(offer_effects) if offer_effects else None
        self.offers = []
        self.cancel_calls = 0

    def cancel_active_offers(self, currency):
        self.cancel_calls += 1
        return self.cancelled

    def get_available_balance(self, currency):
        return self.balance

    def get_frr(self, currency):
        return self.frr

    def create_loan_offer(self, currency, amount, rate, duration):
        self.offers.append((currency, amount, rate, duration))
        if self.offer_effects:
            effect = self.offer_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            if effect is not None:
                return effect
        return {
            "status": "submitted",
            "id": 1000 + len(self.offers),
            "symbol": f"f{currency}",
            "amount": amount,
            "rate": rate,
            "period": duration,
        }


@pytest.fixture
def strategy():
    return FrrPlusStrategy(
        {
            "strategy": {
                "min_required_usd": 150,
                "min_loan_size_usd": 150,
                "spread_count": 3,
                "spread_step_pct": 0.15,
                "premium_rate": 0.0002,
                "minimum_rate": 0.0001,
                "long_duration_threshold": 0.00082,
                "short_duration": 2,
                "long_duration": 30,
            }
        }
    )


@pytest.fixture
def no_sleep(monkeypatch):
    """攔下等待餘額釋放的 sleep，記錄秒數。"""
    calls = []
    monkeypatch.setattr(bot_engine.time, "sleep", lambda seconds: calls.append(seconds))
    return calls


def offers_in_db(repository):
    return [dict(row) for row in repository.connection.execute("SELECT * FROM loan_offers ORDER BY id")]


class TestHappyPath:
    def test_places_every_planned_offer(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        client = FakeClient(balance=600.0, frr=0.0002)
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert len(client.offers) == 3
        assert [amount for _, amount, _, _ in client.offers] == [200.0, 200.0, 200.0]

    def test_records_every_offer_in_db(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        client = FakeClient(balance=600.0, frr=0.0002)
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        rows = offers_in_db(repository)
        assert len(rows) == 3
        assert {row["status"] for row in rows} == {"submitted"}
        assert [row["offer_id"] for row in rows] == ["1001", "1002", "1003"]

    def test_writes_state_with_frr_and_summary(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        client = FakeClient(balance=600.0, frr=0.0002)
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        state = repository.get_state()
        assert state["last_frr"] == pytest.approx(0.0002)
        assert state["last_run_at"] is not None
        assert "掛出 3 筆掛單" in state["last_action"]
        assert "600.0 USD" in state["last_action"]

    def test_routine_cycle_does_not_push_to_line(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """例行巡檢只寫日誌，不推 LINE（見 DECISIONS.md D024）。

        LINE 免費方案每月 200 則，巡檢間隔 600 秒等於一天 144 輪——每輪推一則
        不到兩天就把額度用光，之後真正的故障告警一則都送不出去。
        這條測試就是釘住「不要再把例行事件接回通知管道」。
        """
        run_once(fake_logger, fake_notifier, strategy, FakeClient(), repository)
        assert fake_notifier.sent == []
        assert any("本輪巡檢完成" in text for text in fake_logger.messages["info"])

    def test_logs_balance_and_frr(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        run_once(fake_logger, fake_notifier, strategy, FakeClient(), repository)
        joined = "\n".join(fake_logger.messages["info"])
        assert "可用 USD 餘額" in joined
        assert "目前 FRR" in joined


class TestCancelBeforeReoffer:
    """每輪全取消重掛（DECISIONS.md D011）：取消後必須等餘額釋放再查餘額。"""

    def test_always_cancels_first(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        client = FakeClient()
        run_once(fake_logger, fake_notifier, strategy, client, repository)
        assert client.cancel_calls == 1

    def test_waits_for_settlement_when_something_was_cancelled(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(cancelled=[{"id": 1}])
        run_once(fake_logger, fake_notifier, strategy, client, repository, cancel_settle_seconds=5)
        assert no_sleep == [5]

    def test_no_wait_when_nothing_was_cancelled(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """沒有舊掛單就不必空等，否則每輪都白白多花幾秒。"""
        run_once(fake_logger, fake_notifier, strategy, FakeClient(cancelled=[]), repository)
        assert no_sleep == []


class TestSkipPaths:
    """略過本輪的兩條路徑：心跳仍要更新，因為機器人是活著且判斷正確的。"""

    @pytest.mark.parametrize("frr", [None, 0.0, -0.0001])
    def test_invalid_frr_skips_cycle(
        self, frr, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(frr=frr)
        with pytest.raises(SkipCycleError, match="FRR 無效"):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.offers == []
        state = repository.get_state()
        assert state["last_run_at"] is not None
        assert state["last_action"] == "FRR 無效，略過本輪"

    def test_insufficient_balance_skips_cycle(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(balance=100.0, frr=0.0002)
        with pytest.raises(SkipCycleError, match="低於最低門檻"):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.offers == []
        state = repository.get_state()
        assert state["last_run_at"] is not None
        assert state["last_frr"] == pytest.approx(0.0002)
        assert "略過本輪" in state["last_action"]

    def test_skip_writes_no_offers(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        client = FakeClient(balance=100.0)
        with pytest.raises(SkipCycleError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)
        assert offers_in_db(repository) == []

    def test_skip_sends_no_notification(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        with pytest.raises(SkipCycleError):
            run_once(fake_logger, fake_notifier, strategy, FakeClient(frr=None), repository)
        assert fake_notifier.sent == []


class TestOfferFailure:
    """掛單 API 無法 rollback：同一輪前幾筆若已成功，錢就已經出去了。"""

    @pytest.mark.parametrize("error", [RetryableError("逾時"), FatalError("金鑰無效")])
    def test_failure_is_recorded_then_raised(
        self, error, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(balance=600.0, offer_effects=[None, error])
        with pytest.raises(type(error)):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        rows = offers_in_db(repository)
        assert [row["status"] for row in rows] == ["submitted", "failed"]
        assert rows[1]["offer_id"] is None
        assert str(error) in rows[1]["detail"]

    def test_remaining_offers_are_not_attempted(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(balance=600.0, offer_effects=[None, RetryableError("逾時")])
        with pytest.raises(RetryableError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)
        assert len(client.offers) == 2  # 第三筆不再嘗試

    def test_failed_round_does_not_write_success_state(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(balance=600.0, offer_effects=[RetryableError("逾時")])
        with pytest.raises(RetryableError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        state = repository.get_state()
        assert state["last_action"] is None
        assert state["last_frr"] is None

    def test_failed_round_sends_no_success_notification(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(offer_effects=[RetryableError("逾時")])
        with pytest.raises(RetryableError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)
        assert fake_notifier.sent == []

    def test_first_offer_failure_records_only_one_row(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(offer_effects=[FatalError("拒單")])
        with pytest.raises(FatalError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)
        assert len(offers_in_db(repository)) == 1


class TestExchangeReportedValues:
    def test_db_uses_exchange_values_not_plan(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """部分成交時交易所回報的金額會與計畫不同，落帳要以交易所為準。"""
        client = FakeClient(
            balance=600.0,
            offer_effects=[
                {"status": "submitted", "id": 9, "symbol": "fUSD", "amount": 150.0,
                 "rate": 0.00051, "period": 30},
                None,
                None,
            ],
        )
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        first = offers_in_db(repository)[0]
        assert (first["amount"], first["rate"], first["duration"]) == (150.0, 0.00051, 30)


class TestConsecutiveRounds:
    def test_offers_accumulate_across_rounds(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(balance=600.0)
        for _ in range(3):
            run_once(fake_logger, fake_notifier, strategy, client, repository)
        assert len(offers_in_db(repository)) == 9

    def test_state_reflects_the_latest_round(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(balance=600.0)
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        client.balance = 300.0
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert "掛出 2 筆掛單" in repository.get_state()["last_action"]
