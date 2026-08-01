# -*- coding: utf-8 -*-
"""三層測試共用的 fixture 與測試替身。

替身刻意寫得很薄：只記錄「被呼叫了什麼」，不模仿交易所的完整行為。
需要驗證真實 ccxt 行為的部分，一律留給 `tests/integration`。
"""

import logging

import pytest

from db.repository import Repository

# 與 config.yaml 一致的策略預設值，讓測試的基準跟正式設定同一組。
DEFAULT_STRATEGY = {
    "min_required_usd": 150,
    "min_loan_size_usd": 150,
    "short_duration": 2,
    "long_duration": 30,
    "premium_rate": 0.0002,
    "minimum_rate": 0.0001,
    "long_duration_threshold": 0.00082,
    "spread_count": 3,
    "spread_step_pct": 0.15,
    "max_to_lend_usd": 0,
    "max_percent_to_lend": 0,
}


class FakeLogger:
    """記錄各級別訊息，供測試斷言「有沒有留下該留的紀錄」。"""

    def __init__(self):
        self.messages = {"debug": [], "info": [], "warning": [], "error": [], "exception": []}

    def debug(self, message):
        self.messages["debug"].append(str(message))

    def info(self, message):
        self.messages["info"].append(str(message))

    def warning(self, message):
        self.messages["warning"].append(str(message))

    def error(self, message):
        self.messages["error"].append(str(message))

    def exception(self, message):
        self.messages["exception"].append(str(message))

    def all_messages(self):
        return [text for bucket in self.messages.values() for text in bucket]


class FakeNotifier:
    """記錄送出的通知內容；回傳值可設定，模擬 LINE 送出成功／失敗。"""

    def __init__(self, result=True):
        self.sent = []
        self.result = result

    def send(self, message: str) -> bool:
        self.sent.append(str(message))
        return self.result


@pytest.fixture
def fake_logger():
    return FakeLogger()


@pytest.fixture
def fake_notifier():
    return FakeNotifier()


@pytest.fixture
def repository(tmp_path):
    """每個測試一份全新的 SQLite 檔，測完關閉連線。"""
    repo = Repository(str(tmp_path / "data" / "test.sqlite3"))
    yield repo
    repo.close()


@pytest.fixture
def strategy_config():
    """回傳一份可自由覆寫的策略設定產生器。"""

    def _build(**overrides):
        strategy = dict(DEFAULT_STRATEGY)
        strategy.update(overrides)
        return {"strategy": strategy}

    return _build


@pytest.fixture(autouse=True)
def reset_bot_logger():
    """測試前後都清掉 `BotLogger` 共用的具名 logger。

    `BotLogger` 對 `logging.getLogger("bfx_lending_bot")` 做的是「已有 handler 就直接返回」，
    這是常駐程式該有的行為（避免重複掛 handler），但在測試裡會造成兩種污染：前一個測試留下
    的檔案 handler 會讓下一個測試的設定完全不生效，而且檔案句柄不關會卡住 tmp_path 清理。

    另外 pytest 8.4 起會對 `propagate=False` 的 logger 直接掛上 `LogCaptureHandler`，
    同樣會觸發上述早期返回，因此測試開始前也要清一次。需要在測試進行中重建 logger 的
    情境（`tests/unit/test_logger.py`），另有 `make_logger` fixture 負責即時清空。
    """
    _clear_bot_logger()
    yield
    _clear_bot_logger()


def _clear_bot_logger():
    logger = logging.getLogger("bfx_lending_bot")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
