# -*- coding: utf-8 -*-
"""`api/rate_limiter.py` 的單元測試。

重點在兩件事：退避秒數算得對不對，以及**哪些方法刻意沒有被包上重試**——
`create_loan_offer()` 不冪等，被誤加重試等於實盤重複借出（見 DECISIONS.md D013），
所以那條界線本身就需要一個測試守著。
"""

import pytest

from api import rate_limiter
from api.rate_limiter import RetrySettings, with_retry
from api.bitfinex_client import BitfinexClient
from utils.exceptions import FatalError, RetryableError


@pytest.fixture
def sleep_calls(monkeypatch):
    """攔下退避用的 sleep，記錄秒數且不真的等待。"""
    calls = []
    monkeypatch.setattr(rate_limiter.time, "sleep", lambda seconds: calls.append(seconds))
    return calls


class Caller:
    """帶有 `retry_settings` 與 `logger` 的最小宿主，模擬 BitfinexClient。"""

    def __init__(self, outcomes, settings=None, logger=None):
        # outcomes：每次呼叫要「拋出的例外」或「回傳值」，依序取用
        self.outcomes = list(outcomes)
        self.retry_settings = settings or RetrySettings(max_attempts=3, base_delay=2.0)
        self.logger = logger
        self.call_count = 0

    @with_retry()
    def fetch(self):
        self.call_count += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TestRetrySettings:
    def test_defaults_when_config_is_empty(self):
        settings = RetrySettings.from_config({})
        assert settings.max_attempts == 5
        assert settings.base_delay == 2.0
        assert settings.max_delay == 60.0

    def test_reads_retry_section(self):
        settings = RetrySettings.from_config(
            {"retry": {"max_attempts": 2, "base_delay": 0.5, "max_delay": 5}}
        )
        assert (settings.max_attempts, settings.base_delay, settings.max_delay) == (2, 0.5, 5.0)

    def test_none_config_falls_back_to_defaults(self):
        assert RetrySettings.from_config(None).max_attempts == 5

    def test_max_attempts_never_below_one(self):
        """設 0 或負數不能讓方法變成一次都不執行。"""
        assert RetrySettings(max_attempts=0).max_attempts == 1
        assert RetrySettings(max_attempts=-3).max_attempts == 1

    def test_negative_delays_are_clamped_to_zero(self):
        settings = RetrySettings(base_delay=-1, max_delay=-1)
        assert settings.base_delay == 0.0
        assert settings.max_delay == 0.0

    def test_delay_doubles_each_attempt(self):
        settings = RetrySettings(base_delay=2.0, max_delay=60.0)
        assert [settings.delay_for(n) for n in range(1, 5)] == [2.0, 4.0, 8.0, 16.0]

    def test_delay_is_capped_by_max_delay(self):
        settings = RetrySettings(base_delay=10.0, max_delay=15.0)
        assert [settings.delay_for(n) for n in range(1, 5)] == [10.0, 15.0, 15.0, 15.0]


class TestWithRetry:
    def test_success_on_first_attempt_does_not_sleep(self, sleep_calls):
        caller = Caller(["ok"])
        assert caller.fetch() == "ok"
        assert caller.call_count == 1
        assert sleep_calls == []

    def test_recovers_after_transient_failures(self, sleep_calls):
        caller = Caller([RetryableError("逾時"), RetryableError("逾時"), "ok"])
        assert caller.fetch() == "ok"
        assert caller.call_count == 3
        assert sleep_calls == [2.0, 4.0]

    def test_raises_after_attempts_exhausted(self, sleep_calls):
        caller = Caller([RetryableError("一直逾時")] * 3)
        with pytest.raises(RetryableError, match="一直逾時"):
            caller.fetch()
        assert caller.call_count == 3
        # 最後一次失敗不再退避，直接交回主迴圈
        assert sleep_calls == [2.0, 4.0]

    def test_fatal_error_is_not_retried(self, sleep_calls):
        """金鑰無效這類錯誤重試沒有意義，必須立刻往外拋。"""
        caller = Caller([FatalError("金鑰無效"), "ok"])
        with pytest.raises(FatalError, match="金鑰無效"):
            caller.fetch()
        assert caller.call_count == 1
        assert sleep_calls == []

    def test_max_attempts_one_disables_retry(self, sleep_calls):
        caller = Caller([RetryableError("逾時")], settings=RetrySettings(max_attempts=1))
        with pytest.raises(RetryableError):
            caller.fetch()
        assert caller.call_count == 1
        assert sleep_calls == []

    def test_delay_respects_max_delay(self, sleep_calls):
        caller = Caller(
            [RetryableError("逾時")] * 4,
            settings=RetrySettings(max_attempts=4, base_delay=10.0, max_delay=15.0),
        )
        with pytest.raises(RetryableError):
            caller.fetch()
        assert sleep_calls == [10.0, 15.0, 15.0]

    def test_falls_back_to_defaults_without_retry_settings(self, sleep_calls):
        """宿主沒有 retry_settings 時仍要能運作，而不是 AttributeError。"""

        class Bare:
            logger = None

            @with_retry()
            def fetch(self):
                return "ok"

        assert Bare().fetch() == "ok"

    def test_logs_warning_between_attempts_and_error_at_the_end(self, sleep_calls, fake_logger):
        caller = Caller([RetryableError("逾時")] * 3, logger=fake_logger)
        with pytest.raises(RetryableError):
            caller.fetch()
        assert len(fake_logger.messages["warning"]) == 2
        assert len(fake_logger.messages["error"]) == 1
        assert "重試 3 次仍失敗" in fake_logger.messages["error"][0]

    def test_decorator_arguments_override_object_settings(self, sleep_calls):
        class Overridden:
            logger = None
            retry_settings = RetrySettings(max_attempts=5, base_delay=2.0)

            def __init__(self):
                self.call_count = 0

            @with_retry(max_attempts=2, base_delay=0.5)
            def fetch(self):
                self.call_count += 1
                raise RetryableError("逾時")

        caller = Overridden()
        with pytest.raises(RetryableError):
            caller.fetch()
        assert caller.call_count == 2
        assert sleep_calls == [0.5]

    def test_preserves_function_metadata(self):
        assert Caller.fetch.__name__ == "fetch"


class TestRetryCoverageBoundary:
    """守住「哪些方法有重試、哪些刻意沒有」這條界線（DECISIONS.md D013）。"""

    def test_read_and_cancel_methods_are_wrapped(self):
        for name in ("get_available_balance", "get_frr", "cancel_active_offers"):
            method = getattr(BitfinexClient, name)
            assert hasattr(method, "__wrapped__"), f"{name} 應該要套用 @with_retry"

    def test_create_loan_offer_is_deliberately_not_wrapped(self):
        """掛單不是冪等操作：回應逾時後重試，實盤下是真的重複借出去。"""
        assert not hasattr(BitfinexClient.create_loan_offer, "__wrapped__"), (
            "create_loan_offer() 不可套用 @with_retry，見 DECISIONS.md D013"
        )
