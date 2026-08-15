# -*- coding: utf-8 -*-
"""對 Bitfinex 公開端點的整合測試（唯讀，不需金鑰）。

**安全界線**：這裡只呼叫公開的 `GET /v2/ticker/f{CCY}`，不帶 API 金鑰、不查帳戶、
永遠不掛單也不取消掛單。任何需要簽章的端點都不屬於自動化測試的範圍。

存在的理由：這個專案最大的已知風險就是「ccxt 對 Bitfinex funding 的支援不可靠」
（見 DECISIONS.md D010 與 `.project-docs/CCXT_BITFINEX_API_INVESTIGATION.md`）。
`get_frr()` 走的是 implicit API 加陣列索引，ccxt 或 Bitfinex 任一端改了回應格式，
離線測試完全看不出來，只會在實盤那一刻爆掉。

連不上網路時一律 `skip` 而非 `fail`——CI 不該因為外部服務抖動就變紅燈。
"""

import ccxt
import pytest

from api.bitfinex_client import BitfinexClient
from utils.exceptions import RetryableError

pytestmark = pytest.mark.live

# FRR 是「日利率」，量級約在 0.00001 ~ 0.005 之間（年化約 0.4% ~ 全年數倍）。
# 這裡的區間刻意放寬，只用來擋「抓到完全不同性質的數字」，例如永續合約
# 資金費率或價格——先前 get_frr() 的 bug 正是抓到了錯的欄位。
FRR_LOWER_BOUND = 0.0
FRR_UPPER_BOUND = 0.01


@pytest.fixture(scope="module")
def public_exchange():
    return ccxt.bitfinex({"enableRateLimit": True, "timeout": 10000})


@pytest.fixture(scope="module")
def fusd_ticker(public_exchange):
    """抓 fUSD 的 ticker；連不上就整個模組 skip。"""
    try:
        return public_exchange.public_get_ticker_symbol({"symbol": "fUSD"})
    except (ccxt.NetworkError, ccxt.ExchangeError, OSError) as exc:
        pytest.skip(f"連不上 Bitfinex 公開端點，略過連線測試：{exc}")


class TestTickerContract:
    """守住 `get_frr()` 依賴的回應格式。"""

    def test_response_is_an_array(self, fusd_ticker):
        assert isinstance(fusd_ticker, list)

    def test_response_has_enough_fields(self, fusd_ticker):
        # funding ticker 官方定義為 13 個欄位
        # https://docs.bitfinex.com/reference/rest-public-ticker
        assert len(fusd_ticker) >= 13, f"fUSD ticker 只回傳 {len(fusd_ticker)} 個欄位，格式可能已變更"

    def test_first_field_is_a_plausible_frr(self, fusd_ticker):
        """index 0 必須是 FRR：這正是先前抓錯欄位的地方。"""
        frr = float(fusd_ticker[0])
        assert FRR_LOWER_BOUND < frr < FRR_UPPER_BOUND, (
            f"fUSD ticker[0] = {frr}，不像日利率。可能是欄位順序變了，"
            f"或又抓到了永續合約資金費率"
        )


class TestGetFrrAgainstLiveApi:
    """用真實回應跑一次 `get_frr()`，確認解析邏輯到今天仍然成立。"""

    def test_returns_a_plausible_daily_rate(self, fake_logger, fusd_ticker):
        client = BitfinexClient({}, fake_logger, dry_run=True)
        client.dry_run = False
        client.exchange = ccxt.bitfinex({"enableRateLimit": True, "timeout": 10000})

        try:
            frr = client.get_frr("USD")
        except RetryableError as exc:
            pytest.skip(f"Bitfinex 公開端點暫時無法取得 FRR，略過：{exc}")

        assert isinstance(frr, float)
        assert FRR_LOWER_BOUND < frr < FRR_UPPER_BOUND

    def test_matches_the_raw_ticker(self, fake_logger, fusd_ticker, public_exchange):
        """封裝後的結果要與 raw 回應一致，證明沒有多做手腳。"""
        client = BitfinexClient({}, fake_logger, dry_run=True)
        client.dry_run = False
        client.exchange = public_exchange

        try:
            frr = client.get_frr("USD")
        except RetryableError as exc:
            pytest.skip(f"Bitfinex 公開端點暫時無法取得 FRR，略過：{exc}")

        # FRR 會隨時間變動，只比對量級是否一致（同一個欄位、同一種單位）
        assert frr == pytest.approx(float(fusd_ticker[0]), rel=0.5)


class TestUnsupportedCurrencyIsHandled:
    def test_unknown_symbol_does_not_crash_the_client(self, fake_logger):
        """不存在的幣別要被分類成我們自己的例外，不能讓 ccxt 原始例外漏出去。"""
        client = BitfinexClient({}, fake_logger, dry_run=True)
        client.dry_run = False
        client.exchange = ccxt.bitfinex({"enableRateLimit": True, "timeout": 10000})
        client.retry_settings.max_attempts = 1

        from utils.exceptions import FatalError

        try:
            client.get_frr("NOTACURRENCY")
        except (RetryableError, FatalError):
            pass  # 兩種分類都是可接受的結果，重點是沒有 ccxt 例外漏出來
        except (ccxt.NetworkError, OSError) as exc:
            pytest.skip(f"連不上 Bitfinex 公開端點，略過：{exc}")
