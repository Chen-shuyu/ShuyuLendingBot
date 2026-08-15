# -*- coding: utf-8 -*-
"""`core.bot_engine.FailureTracker` 的功能測試：連續失敗告警的去重與恢復通知。

交易所長時間異常時每輪都送告警會把通知管道洗版，反而讓人忽略；因此規則是
「剛跨過門檻」與「剛恢復」各送一次（DECISIONS.md D013）。失敗次數同時要寫進
DB，未來的容器 healthcheck 才能不啟動 Python 就判斷健康狀態。
"""

import pytest

from core.bot_engine import FailureTracker


@pytest.fixture
def tracker(fake_logger, fake_notifier, repository):
    def _build(alert_after=3):
        return FailureTracker(fake_logger, fake_notifier, repository, alert_after)

    return _build


class TestAlertThreshold:
    def test_no_alert_below_threshold(self, tracker, fake_notifier):
        failures = tracker(alert_after=3)
        failures.record_failure("逾時")
        failures.record_failure("逾時")
        assert fake_notifier.sent == []

    def test_alerts_exactly_at_threshold(self, tracker, fake_notifier):
        failures = tracker(alert_after=3)
        for _ in range(3):
            failures.record_failure("交易所異常")

        assert len(fake_notifier.sent) == 1
        assert "連續 3 輪" in fake_notifier.sent[0]
        assert "交易所異常" in fake_notifier.sent[0]

    def test_does_not_repeat_alert_while_still_failing(self, tracker, fake_notifier):
        failures = tracker(alert_after=3)
        for _ in range(10):
            failures.record_failure("逾時")
        assert len(fake_notifier.sent) == 1

    def test_alert_after_one_alerts_immediately(self, tracker, fake_notifier):
        failures = tracker(alert_after=1)
        failures.record_failure("逾時")
        assert len(fake_notifier.sent) == 1

    @pytest.mark.parametrize("value", [0, -5])
    def test_threshold_never_below_one(self, tracker, fake_notifier, value):
        """設 0 不能變成「永遠不告警」或「還沒失敗就告警」。"""
        failures = tracker(alert_after=value)
        assert failures.alert_after == 1
        assert fake_notifier.sent == []
        failures.record_failure("逾時")
        assert len(fake_notifier.sent) == 1

    def test_alert_is_also_logged_as_error(self, tracker, fake_logger):
        failures = tracker(alert_after=1)
        failures.record_failure("逾時")
        assert any("連續 1 輪" in text for text in fake_logger.messages["error"])


class TestRecovery:
    def test_sends_recovery_notice_once(self, tracker, fake_notifier):
        failures = tracker(alert_after=2)
        failures.record_failure("逾時")
        failures.record_failure("逾時")
        failures.record_success()

        assert len(fake_notifier.sent) == 2
        assert "恢復正常" in fake_notifier.sent[1]

    def test_no_recovery_notice_without_prior_alert(self, tracker, fake_notifier):
        """沒告警過就沒有「恢復」可言，不該無故送一則通知。"""
        failures = tracker(alert_after=3)
        failures.record_failure("逾時")
        failures.record_success()
        assert fake_notifier.sent == []

    def test_repeated_success_sends_nothing(self, tracker, fake_notifier):
        failures = tracker(alert_after=1)
        failures.record_failure("逾時")
        failures.record_success()
        failures.record_success()
        failures.record_success()
        assert len(fake_notifier.sent) == 2  # 一則告警 + 一則恢復

    def test_can_alert_again_after_recovery(self, tracker, fake_notifier):
        failures = tracker(alert_after=2)
        for _ in range(2):
            failures.record_failure("第一次故障")
        failures.record_success()
        for _ in range(2):
            failures.record_failure("第二次故障")

        assert len(fake_notifier.sent) == 3
        assert "第二次故障" in fake_notifier.sent[2]

    def test_counter_resets_on_success(self, tracker):
        failures = tracker(alert_after=3)
        failures.record_failure("逾時")
        failures.record_failure("逾時")
        failures.record_success()
        assert failures.consecutive_failures == 0


class TestPersistence:
    """失敗次數落 DB，而非只存在記憶體——重啟後歸零的計數對外沒有意義。"""

    def test_failure_count_is_written(self, tracker, repository):
        failures = tracker(alert_after=5)
        failures.record_failure("逾時")
        failures.record_failure("逾時")
        assert repository.get_state()["consecutive_failures"] == 2

    def test_success_writes_zero(self, tracker, repository):
        failures = tracker(alert_after=5)
        failures.record_failure("逾時")
        failures.record_success()
        assert repository.get_state()["consecutive_failures"] == 0

    def test_failure_reason_is_written_to_state(self, tracker, repository):
        tracker().record_failure("查詢餘額逾時")
        assert repository.get_state()["last_action"] == "巡檢失敗：查詢餘額逾時"

    def test_both_paths_update_heartbeat(self, tracker, repository):
        """成功與失敗都要更新 last_run_at，心跳不能只在順利時才跳。"""
        failures = tracker()
        failures.record_failure("逾時")
        assert repository.get_state()["last_run_at"] is not None

        repository.save_state(last_action="重置")
        failures.record_success()
        assert repository.get_state()["last_run_at"] is not None
