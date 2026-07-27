# -*- coding: utf-8 -*-
"""交易所 API 呼叫的重試機制（指數退避）。

`modules/exchange_client.py` 的每個方法已經把 ccxt 的原始例外分類成
`RetryableError` / `FatalError`，所以這裡只要攔 `RetryableError` 重試即可，
不需要再認得 ccxt 的例外型別；`FatalError`（金鑰無效、權限不足）重試沒有意義，
一律直接往外拋。

**寫入類、不冪等的操作不可套用**：`create_loan_offer()` 若請求其實已送達
Bitfinex、只是回應逾時，重試就會重複掛單，實盤下是真的多借出去。掛單失敗
改由主迴圈下一輪的「全取消重掛」自然補回（見 DECISIONS.md D013）。
"""

import time
from functools import wraps

from utils.exceptions import RetryableError

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BASE_DELAY = 2.0
DEFAULT_MAX_DELAY = 60.0


class RetrySettings:
    """重試參數，對應 config.yaml 的 `retry:` 區段。"""

    def __init__(
        self,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
    ):
        # max_attempts 是「總嘗試次數」而非「額外重試次數」，設 1 等於不重試
        self.max_attempts = max(1, int(max_attempts))
        self.base_delay = max(0.0, float(base_delay))
        self.max_delay = max(0.0, float(max_delay))

    @classmethod
    def from_config(cls, config) -> "RetrySettings":
        retry_config = (config or {}).get("retry", {}) or {}
        return cls(
            max_attempts=retry_config.get("max_attempts", DEFAULT_MAX_ATTEMPTS),
            base_delay=retry_config.get("base_delay", DEFAULT_BASE_DELAY),
            max_delay=retry_config.get("max_delay", DEFAULT_MAX_DELAY),
        )

    def delay_for(self, attempt: int) -> float:
        """第 `attempt` 次嘗試失敗後要等幾秒（attempt 由 1 起算），上限 `max_delay`。"""
        return min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)


def with_retry(max_attempts=None, base_delay=None, max_delay=None):
    """把「讀取類或冪等」的交易所呼叫包上指數退避重試。

    參數留空時採用被包裝物件的 `retry_settings`（由 config.yaml 載入）；
    傳入值則覆寫該方法自己的重試行為。只能用在具有 `retry_settings` 與
    `logger` 屬性的物件方法上（即 `BitfinexClient`）。
    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            settings = getattr(self, "retry_settings", None) or RetrySettings()
            if max_attempts is not None or base_delay is not None or max_delay is not None:
                settings = RetrySettings(
                    max_attempts=max_attempts if max_attempts is not None else settings.max_attempts,
                    base_delay=base_delay if base_delay is not None else settings.base_delay,
                    max_delay=max_delay if max_delay is not None else settings.max_delay,
                )
            logger = getattr(self, "logger", None)

            for attempt in range(1, settings.max_attempts + 1):
                try:
                    return func(self, *args, **kwargs)
                except RetryableError as exc:
                    if attempt >= settings.max_attempts:
                        if logger:
                            logger.error(
                                f"{func.__name__} 重試 {settings.max_attempts} 次仍失敗，交回主迴圈：{exc}"
                            )
                        raise
                    delay = settings.delay_for(attempt)
                    if logger:
                        logger.warning(
                            f"{func.__name__} 第 {attempt}/{settings.max_attempts} 次嘗試失敗，"
                            f"{delay:.1f} 秒後重試：{exc}"
                        )
                    time.sleep(delay)

        return wrapper

    return decorator
