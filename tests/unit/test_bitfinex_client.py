# -*- coding: utf-8 -*-
"""`api/bitfinex_client.py` 的單元測試（不連網路）。

用假的 exchange 物件驗證三件事：ccxt 例外有沒有被正確分類成
`RetryableError` / `FatalError`、Bitfinex V2 的陣列式回應有沒有解析對、
以及 dry-run 模式是不是真的完全不碰交易所。

真正打 Bitfinex 的驗證留在 `tests/integration/test_bitfinex_public_api.py`。
"""

import ccxt
import pytest

from api.bitfinex_client import BitfinexClient
from api.rate_limiter import RetrySettings
from utils.exceptions import FatalError, RetryableError

# Bitfinex V2 funding offer 陣列：0=ID, 1=SYMBOL, 4=AMOUNT, 14=RATE, 15=PERIOD
# https://docs.bitfinex.com/reference/rest-auth-funding-offers
FUNDING_OFFER_FIELDS = 16


def make_offer_array(offer_id=101, symbol="fUSD", amount=200.0, rate=0.0004, period=2):
    """模擬 ccxt 回傳的 funding offer 陣列。

    **每個數值欄位都是字串**——實測 ccxt 對這個 implicit 端點回傳的就是
    `'5081103121'`、`'160'`、`'0.000523'`、`'2'`，不是數字。
    這個替身原本回傳原生型別，比真實 API「乾淨」，於是漏掉了「取消時 id 必須
    轉回整數」這個 bug：實單下每一輪都取消失敗（2026-08-15，見 DECISIONS.md D026）。
    替身要像真的，不然測試只是在驗證另一個世界。
    """
    offer = [None] * FUNDING_OFFER_FIELDS
    offer[0] = str(offer_id)
    offer[1] = symbol
    offer[4] = str(amount)
    offer[14] = str(rate)
    offer[15] = str(period)
    return offer


def make_submit_response(offer=None, status="SUCCESS", text="offer submitted"):
    # 通知信封：[4]=FUNDING_OFFER_ARRAY, [6]=STATUS, [7]=TEXT
    response = [None] * 8
    response[4] = offer if offer is not None else make_offer_array()
    response[6] = status
    response[7] = text
    return response


class FakeExchange:
    """只實作被用到的 implicit 方法；每個方法可設定回傳值或要拋的例外。"""

    def __init__(self, **behaviours):
        self.behaviours = behaviours
        self.calls = []

    def _respond(self, name, params):
        self.calls.append((name, params))
        behaviour = self.behaviours.get(name)
        if isinstance(behaviour, Exception):
            raise behaviour
        if callable(behaviour):
            return behaviour(params)
        return behaviour

    def fetch_balance(self, params=None):
        return self._respond("fetch_balance", params)

    def public_get_ticker_symbol(self, params=None):
        return self._respond("public_get_ticker_symbol", params)

    def private_post_auth_r_funding_offers_symbol(self, params=None):
        return self._respond("private_post_auth_r_funding_offers_symbol", params)

    def private_post_auth_w_funding_offer_cancel(self, params=None):
        return self._respond("private_post_auth_w_funding_offer_cancel", params)

    def private_post_auth_w_funding_offer_submit(self, params=None):
        return self._respond("private_post_auth_w_funding_offer_submit", params)

    def public_get_book_symbol_precision(self, params=None):
        return self._respond("public_get_book_symbol_precision", params)

    def public_get_trades_symbol_hist(self, params=None):
        return self._respond("public_get_trades_symbol_hist", params)

    def private_post_auth_r_funding_credits_symbol(self, params=None):
        return self._respond("private_post_auth_r_funding_credits_symbol", params)

    def private_post_auth_r_funding_loans_symbol(self, params=None):
        return self._respond("private_post_auth_r_funding_loans_symbol", params)


@pytest.fixture
def make_client(fake_logger):
    """建立一個接上假 exchange 的實盤模式 client（預設不重試，測試才跑得快）。"""

    def _build(exchange=None, config=None, max_attempts=1):
        base_config = {"bitfinex": {"dry_run_balance_usd": 344.12, "dry_run_frr": 0.0002}}
        base_config.update(config or {})
        client = BitfinexClient(base_config, fake_logger, dry_run=True)
        client.dry_run = False
        client.exchange = exchange
        client.retry_settings = RetrySettings(max_attempts=max_attempts, base_delay=0)
        return client

    return _build


class TestDryRun:
    """dry-run 必須完全不碰交易所，否則「安全驗證模式」名不副實。"""

    def test_balance_and_frr_come_from_config(self, fake_logger):
        client = BitfinexClient(
            {"bitfinex": {"dry_run_balance_usd": 500.0, "dry_run_frr": 0.0003}},
            fake_logger,
            dry_run=True,
        )
        assert client.get_available_balance("USD") == 500.0
        assert client.get_frr("USD") == 0.0003

    def test_exchange_is_never_created(self, fake_logger):
        client = BitfinexClient(
            {"bitfinex": {"api_key": "k", "api_secret": "s"}}, fake_logger, dry_run=True
        )
        assert client.exchange is None

    def test_test_connection_passes(self, fake_logger):
        assert BitfinexClient({}, fake_logger, dry_run=True).test_connection() is True

    def test_cancel_returns_empty_list(self, fake_logger):
        assert BitfinexClient({}, fake_logger, dry_run=True).cancel_active_offers("USD") == []

    def test_create_offer_returns_dry_run_payload(self, fake_logger):
        result = BitfinexClient({}, fake_logger, dry_run=True).create_loan_offer(
            "USD", 200.0, 0.0004, 2
        )
        assert result == {
            "status": "dry_run",
            "currency": "USD",
            "amount": 200.0,
            "rate": 0.0004,
            "duration": 2,
        }

    def test_defaults_apply_without_bitfinex_section(self, fake_logger):
        client = BitfinexClient({}, fake_logger, dry_run=True)
        assert client.get_available_balance("USD") == 344.12
        assert client.get_frr("USD") == 0.0002


class TestUninitialisedExchange:
    """沒有金鑰時 `self.exchange` 會是 None，所有實盤操作都要明確拋 FatalError。"""

    @pytest.mark.parametrize(
        "call",
        [
            lambda c: c.get_available_balance("USD"),
            lambda c: c.get_frr("USD"),
            lambda c: c.cancel_active_offers("USD"),
            lambda c: c.create_loan_offer("USD", 200.0, 0.0004, 2),
        ],
    )
    def test_raises_fatal_error(self, make_client, call):
        with pytest.raises(FatalError):
            call(make_client(exchange=None))

    def test_test_connection_returns_false(self, make_client):
        assert make_client(exchange=None).test_connection() is False

    def test_missing_credentials_leaves_exchange_none(self, fake_logger):
        assert BitfinexClient({"bitfinex": {}}, fake_logger, dry_run=False).exchange is None


class TestGetAvailableBalance:
    def test_queries_the_funding_wallet(self, make_client):
        """查錯錢包會讀到交易錢包的錢，掛單金額就整個算錯。"""
        exchange = FakeExchange(fetch_balance={"USD": {"free": 344.12}})
        assert make_client(exchange).get_available_balance("USD") == 344.12
        assert exchange.calls[0] == ("fetch_balance", {"type": "funding"})

    def test_missing_currency_returns_zero(self, make_client):
        assert make_client(FakeExchange(fetch_balance={})).get_available_balance("USD") == 0.0

    def test_none_free_returns_zero(self, make_client):
        exchange = FakeExchange(fetch_balance={"USD": {"free": None}})
        assert make_client(exchange).get_available_balance("USD") == 0.0

    @pytest.mark.parametrize(
        "error, expected",
        [
            (ccxt.NetworkError("連線中斷"), RetryableError),
            (ccxt.RateLimitExceeded("太頻繁"), RetryableError),
            (ccxt.AuthenticationError("金鑰無效"), FatalError),
            (ccxt.ExchangeError("交易所異常"), FatalError),
        ],
    )
    def test_classifies_ccxt_errors(self, make_client, error, expected):
        client = make_client(FakeExchange(fetch_balance=error))
        with pytest.raises(expected):
            client.get_available_balance("USD")


class TestGetFrr:
    def test_parses_first_element_of_ticker(self, make_client):
        """fUSD ticker 的 index 0 才是 FRR；先前誤用永續合約資金費率就是錯在這。"""
        exchange = FakeExchange(public_get_ticker_symbol=[0.00035, 1, 2, 3])
        assert make_client(exchange).get_frr("USD") == pytest.approx(0.00035)
        assert exchange.calls[0] == ("public_get_ticker_symbol", {"symbol": "fUSD"})

    def test_uses_funding_symbol_prefix(self, make_client):
        exchange = FakeExchange(public_get_ticker_symbol=[0.0001])
        make_client(exchange).get_frr("UST")
        assert exchange.calls[0][1] == {"symbol": "fUST"}

    @pytest.mark.parametrize("payload", [[], None, ["not-a-number"]])
    def test_unparsable_response_is_retryable(self, make_client, payload):
        """回應格式怪異多半是暫時性的，歸類為可重試而非致命。"""
        client = make_client(FakeExchange(public_get_ticker_symbol=payload))
        with pytest.raises(RetryableError):
            client.get_frr("USD")

    @pytest.mark.parametrize(
        "error, expected",
        [
            (ccxt.NetworkError("連線中斷"), RetryableError),
            (ccxt.AuthenticationError("金鑰無效"), FatalError),
            (ccxt.ExchangeError("交易所異常"), FatalError),
        ],
    )
    def test_classifies_ccxt_errors(self, make_client, error, expected):
        client = make_client(FakeExchange(public_get_ticker_symbol=error))
        with pytest.raises(expected):
            client.get_frr("USD")


class TestCancelActiveOffers:
    def test_cancels_every_open_offer(self, make_client):
        offers = [make_offer_array(101), make_offer_array(102)]
        exchange = FakeExchange(
            private_post_auth_r_funding_offers_symbol=offers,
            private_post_auth_w_funding_offer_cancel={},
        )
        cancelled = make_client(exchange).cancel_active_offers("USD")

        assert [item["id"] for item in cancelled] == [101, 102]
        cancel_calls = [c for c in exchange.calls if c[0].endswith("offer_cancel")]
        assert [c[1] for c in cancel_calls] == [{"id": 101}, {"id": 102}]
        # 送回 API 的 id 必須是 int：Bitfinex 收到字串會回 `id: invalid`（D026）
        assert all(isinstance(call[1]["id"], int) for call in cancel_calls)

    def test_all_cancels_failing_is_surfaced_as_failure(self, make_client):
        """查到掛單卻一筆都取消不掉，必須讓主迴圈知道。

        原本這裡只記 ERROR 就往下走，本輪仍算成功——連續失敗計數不動、不告警、
        心跳照常更新、健康檢查綠燈。**機器人看起來完全正常，實際上已經停止更新
        掛單利率**，2026-08-15 實單下連續兩輪沒有任何人發現（D026）。
        """
        exchange = FakeExchange(
            private_post_auth_r_funding_offers_symbol=[make_offer_array(101)],
            private_post_auth_w_funding_offer_cancel=ccxt.ExchangeError("id: invalid"),
        )
        with pytest.raises(RetryableError, match="一筆都取消不掉"):
            make_client(exchange).cancel_active_offers("USD")

    def test_partial_cancel_still_returns_the_successful_ones(self, make_client):
        """部分成功不算失敗：取消得掉的照樣回報，下一輪再處理剩下的。"""
        def cancel(params):
            if params["id"] == 101:
                raise ccxt.ExchangeError("id: invalid")
            return {}

        exchange = FakeExchange(
            private_post_auth_r_funding_offers_symbol=[
                make_offer_array(101), make_offer_array(102)
            ],
            private_post_auth_w_funding_offer_cancel=cancel,
        )
        cancelled = make_client(exchange).cancel_active_offers("USD")
        assert [item["id"] for item in cancelled] == [102]

    def test_parses_offer_fields(self, make_client):
        exchange = FakeExchange(
            private_post_auth_r_funding_offers_symbol=[
                make_offer_array(7, "fUSD", 150.5, 0.00042, 30)
            ],
            private_post_auth_w_funding_offer_cancel={},
        )
        assert make_client(exchange).cancel_active_offers("USD")[0] == {
            "id": 7,
            "symbol": "fUSD",
            "amount": 150.5,
            "rate": 0.00042,
            "period": 30,
        }

    def test_no_open_offers_returns_empty(self, make_client):
        exchange = FakeExchange(private_post_auth_r_funding_offers_symbol=[])
        assert make_client(exchange).cancel_active_offers("USD") == []

    def test_defaults_to_fusd_without_currency(self, make_client):
        exchange = FakeExchange(private_post_auth_r_funding_offers_symbol=[])
        make_client(exchange).cancel_active_offers()
        assert exchange.calls[0][1] == {"symbol": "fUSD"}

    def test_single_failure_does_not_stop_the_rest(self, make_client, fake_logger):
        """某筆取消失敗（例如剛好成交了）不能讓其他筆也不取消。"""
        state = {"count": 0}

        def cancel(params):
            state["count"] += 1
            if params["id"] == 101:
                raise ccxt.ExchangeError("offer not found")
            return {}

        exchange = FakeExchange(
            private_post_auth_r_funding_offers_symbol=[make_offer_array(101), make_offer_array(102)],
            private_post_auth_w_funding_offer_cancel=cancel,
        )
        cancelled = make_client(exchange).cancel_active_offers("USD")

        assert [item["id"] for item in cancelled] == [102]
        assert state["count"] == 2
        assert any("101" in text for text in fake_logger.messages["error"])

    def test_network_error_while_cancelling_is_retryable(self, make_client):
        exchange = FakeExchange(
            private_post_auth_r_funding_offers_symbol=[make_offer_array(101)],
            private_post_auth_w_funding_offer_cancel=ccxt.NetworkError("逾時"),
        )
        with pytest.raises(RetryableError):
            make_client(exchange).cancel_active_offers("USD")

    @pytest.mark.parametrize(
        "error, expected",
        [
            (ccxt.NetworkError("連線中斷"), RetryableError),
            (ccxt.AuthenticationError("金鑰無效"), FatalError),
            (ccxt.ExchangeError("交易所異常"), FatalError),
        ],
    )
    def test_classifies_query_errors(self, make_client, error, expected):
        client = make_client(FakeExchange(private_post_auth_r_funding_offers_symbol=error))
        with pytest.raises(expected):
            client.cancel_active_offers("USD")


class TestCreateLoanOffer:
    def test_submits_limit_offer_with_string_amounts(self, make_client):
        exchange = FakeExchange(private_post_auth_w_funding_offer_submit=make_submit_response())
        make_client(exchange).create_loan_offer("USD", 200.0, 0.0004, 2)
        assert exchange.calls[0][1] == {
            "type": "LIMIT",
            "symbol": "fUSD",
            "amount": "200.0",
            "rate": "0.0004",
            "period": 2,
        }

    def test_parses_successful_response(self, make_client):
        offer = make_offer_array(555, "fUSD", 200.0, 0.00045, 30)
        exchange = FakeExchange(
            private_post_auth_w_funding_offer_submit=make_submit_response(offer)
        )
        # id 維持交易所回傳的字串：ccxt 對這個端點每個欄位都是字串，而 DB 的
        # offer_id 欄位本來就是 TEXT。需要轉成整數的只有取消端點（見 D026）。
        assert make_client(exchange).create_loan_offer("USD", 200.0, 0.0004, 2) == {
            "status": "submitted",
            "id": "555",
            "symbol": "fUSD",
            "amount": 200.0,
            "rate": 0.00045,
            "period": 30,
        }

    def test_non_success_status_raises_fatal_with_text(self, make_client):
        """交易所回 ERROR 時要把原因帶出來，不然日誌上只看得到一句失敗。"""
        exchange = FakeExchange(
            private_post_auth_w_funding_offer_submit=make_submit_response(
                status="ERROR", text="funding: invalid amount"
            )
        )
        with pytest.raises(FatalError, match="funding: invalid amount"):
            make_client(exchange).create_loan_offer("USD", 1.0, 0.0004, 2)

    def test_truncated_response_raises_fatal(self, make_client):
        exchange = FakeExchange(private_post_auth_w_funding_offer_submit=[1, 2, 3])
        with pytest.raises(FatalError):
            make_client(exchange).create_loan_offer("USD", 200.0, 0.0004, 2)

    @pytest.mark.parametrize(
        "error, expected",
        [
            (ccxt.NetworkError("連線中斷"), RetryableError),
            (ccxt.RateLimitExceeded("太頻繁"), RetryableError),
            (ccxt.AuthenticationError("金鑰無效"), FatalError),
            (ccxt.ExchangeError("交易所異常"), FatalError),
        ],
    )
    def test_classifies_ccxt_errors(self, make_client, error, expected):
        client = make_client(FakeExchange(private_post_auth_w_funding_offer_submit=error))
        with pytest.raises(expected):
            client.create_loan_offer("USD", 200.0, 0.0004, 2)

    def test_submit_is_called_exactly_once_on_failure(self, make_client):
        """守住「掛單不重試」：逾時後重送等於實盤重複借出（DECISIONS.md D013）。"""
        exchange = FakeExchange(
            private_post_auth_w_funding_offer_submit=ccxt.NetworkError("回應逾時")
        )
        client = make_client(exchange, max_attempts=5)
        with pytest.raises(RetryableError):
            client.create_loan_offer("USD", 200.0, 0.0004, 2)
        assert len(exchange.calls) == 1


class TestTestConnection:
    def test_checks_the_funding_wallet(self, make_client):
        exchange = FakeExchange(fetch_balance={"USD": {"free": 0.0}})
        assert make_client(exchange).test_connection() is True
        assert exchange.calls[0] == ("fetch_balance", {"type": "funding"})

    def test_returns_false_on_any_error(self, make_client, fake_logger):
        client = make_client(FakeExchange(fetch_balance=ccxt.AuthenticationError("金鑰無效")))
        assert client.test_connection() is False
        assert fake_logger.messages["error"]


class TestCcxtContract:
    """守住 DECISIONS.md D010 的前提：這些 implicit 方法必須存在於 ccxt。

    不需要網路——只是建立物件檢查方法有沒有被 ccxt 改名或移除。ccxt 升版把任何
    一個拿掉，實盤就會在執行到那一行時才爆掉，這裡先擋下來。
    """

    @pytest.mark.parametrize(
        "method_name",
        [
            "public_get_ticker_symbol",
            "private_post_auth_r_funding_offers_symbol",
            "private_post_auth_w_funding_offer_cancel",
            "private_post_auth_w_funding_offer_submit",
            "public_get_book_symbol_precision",
            "private_post_auth_r_funding_credits_symbol",
            "private_post_auth_r_funding_loans_symbol",
        ],
    )
    def test_implicit_method_exists(self, method_name):
        assert hasattr(ccxt.bitfinex(), method_name), (
            f"ccxt {ccxt.__version__} 已無 {method_name}，需重新盤點 "
            f".project-docs/CCXT_BITFINEX_API_INVESTIGATION.md"
        )

    def test_bitfinex2_is_not_used(self):
        """ccxt 4.x 已把 V1/V2 合併為單一 `bitfinex`（見 DECISIONS.md D009）。"""
        assert not hasattr(ccxt, "bitfinex2")


# --- 市場深度與已借出部位（2026-08-16 新增，見 DECISIONS.md D030）-----------


def make_book_row(rate, period, amount, count=1):
    """模擬 `/v2/book/fUSD/P0` 的一列：[RATE, PERIOD, COUNT, AMOUNT]。

    **每個欄位都是字串**，利率還是 `'0.0002808219178082192'` 這種長浮點——
    形狀取自 2026-08-16 的實打回應。負的 AMOUNT 是借款需求側。
    """
    return [str(rate), str(period), str(count), str(amount)]


def make_position_array(position_id="1", symbol="fUSD", amount=160.0, rate=0.00025, period=2,
                        opened_at=1786872920000, length=22):
    """模擬 funding credits／loans 的一列。

    欄位（官方文件）：0=ID, 1=SYMBOL, 5=AMOUNT, 7=STATUS, 11=RATE, 12=PERIOD, 13=MTS_OPENING。
    **這個形狀還沒被真實回應驗證過**——探測當下帳號一筆都沒成交，兩個端點都是空清單
    （見 `BitfinexClient.get_active_positions()` 的註解）。
    """
    row = [None] * length
    row[0] = str(position_id)
    row[1] = symbol
    row[5] = str(amount)
    row[7] = "ACTIVE"
    row[11] = str(rate)
    row[12] = str(period)
    row[13] = str(opened_at) if opened_at is not None else None
    return row


class TestGetFundingBook:
    def test_keeps_only_the_supply_side(self, make_client):
        # 負數是借款需求側：對放貸方來說那是買家不是競爭者，
        # 混進來會把「前面排了多少錢」算大好幾倍，掛單價位就整個歪掉。
        exchange = FakeExchange(public_get_book_symbol_precision=[
            make_book_row(0.00025, 2, 500_000),
            make_book_row(0.00028, 120, -9_825_986),
            make_book_row(0.00024, 2, 700_000),
        ])
        book = make_client(exchange).get_funding_book("USD")

        assert len(book) == 2
        assert all(level["amount"] > 0 for level in book)

    def test_sorted_by_rate_ascending(self, make_client):
        exchange = FakeExchange(public_get_book_symbol_precision=[
            make_book_row(0.00026, 2, 100),
            make_book_row(0.00024, 2, 100),
            make_book_row(0.00025, 2, 100),
        ])
        book = make_client(exchange).get_funding_book("USD")

        assert [level["rate"] for level in book] == [0.00024, 0.00025, 0.00026]

    def test_string_fields_are_converted(self, make_client):
        exchange = FakeExchange(public_get_book_symbol_precision=[
            make_book_row(0.0002808219178082192, 120, 12345.67)
        ])
        level = make_client(exchange).get_funding_book("USD")[0]

        assert isinstance(level["rate"], float)
        assert isinstance(level["period"], int)
        assert isinstance(level["amount"], float)
        assert level["period"] == 120

    def test_requests_deep_enough_book(self, make_client):
        """len 預設只給 25 檔（約 3 萬 USD），算不出排隊位置。"""
        exchange = FakeExchange(public_get_book_symbol_precision=[])
        make_client(exchange).get_funding_book("USD")

        _, params = exchange.calls[0]
        assert params["len"] == 250
        assert params["symbol"] == "fUSD"

    def test_network_error_is_retryable(self, make_client):
        exchange = FakeExchange(public_get_book_symbol_precision=ccxt.NetworkError("timeout"))
        with pytest.raises(RetryableError):
            make_client(exchange).get_funding_book("USD")

    def test_malformed_row_is_retryable(self, make_client):
        exchange = FakeExchange(public_get_book_symbol_precision=[["only-one-field"]])
        with pytest.raises(RetryableError):
            make_client(exchange).get_funding_book("USD")

    def test_works_without_credentials(self, fake_logger, monkeypatch):
        """行情是公開資料，dry-run 也該拿得到——否則 dry-run 驗不了定價邏輯。"""
        client = BitfinexClient({}, fake_logger, dry_run=True)
        exchange = FakeExchange(public_get_book_symbol_precision=[make_book_row(0.00025, 2, 100)])
        monkeypatch.setattr(client, "_public_exchange", lambda: exchange)

        assert client.get_funding_book("USD")[0]["rate"] == 0.00025


class TestGetActivePositions:
    def test_merges_credits_and_loans(self, make_client):
        # 兩個端點都要查：credits 是「借款人已拿去用」，loans 是「借走但還沒用掉」，
        # 對放貸方而言兩者都是錢已經出去、正在生息。只查一個會漏掉另一半。
        exchange = FakeExchange(
            private_post_auth_r_funding_credits_symbol=[make_position_array(position_id="1")],
            private_post_auth_r_funding_loans_symbol=[make_position_array(position_id="2", length=21)],
        )
        positions = make_client(exchange).get_active_positions("USD")

        assert [item["id"] for item in positions] == ["1", "2"]
        assert [item["kind"] for item in positions] == ["credit", "loan"]

    def test_string_fields_are_converted(self, make_client):
        exchange = FakeExchange(
            private_post_auth_r_funding_credits_symbol=[
                make_position_array(amount=160.5, rate=0.000273, period=7)
            ],
            private_post_auth_r_funding_loans_symbol=[],
        )
        position = make_client(exchange).get_active_positions("USD")[0]

        assert position["amount"] == 160.5
        assert position["rate"] == 0.000273
        assert position["period"] == 7
        assert isinstance(position["opened_at"], int)

    def test_amount_is_always_positive(self, make_client):
        exchange = FakeExchange(
            private_post_auth_r_funding_credits_symbol=[make_position_array(amount=-160.0)],
            private_post_auth_r_funding_loans_symbol=[],
        )
        assert make_client(exchange).get_active_positions("USD")[0]["amount"] == 160.0

    def test_unparsable_row_is_logged_not_raised(self, make_client, fake_logger):
        """一筆壞資料不該害整輪失敗，但**一定要留下原始內容**。

        欄位索引還沒被真實回應驗證過，萬一猜錯，這行日誌就是唯一的線索——
        沒有它就變成「成交了卻沒人知道」的翻版，只是換個地方發生。
        """
        exchange = FakeExchange(
            private_post_auth_r_funding_credits_symbol=[["too", "short"]],
            private_post_auth_r_funding_loans_symbol=[],
        )
        assert make_client(exchange).get_active_positions("USD") == []
        assert any("無法解析已借出部位" in message for message in fake_logger.messages["error"])
        assert any("too" in message for message in fake_logger.messages["error"])

    def test_dry_run_never_queries(self, fake_logger):
        assert BitfinexClient({}, fake_logger, dry_run=True).get_active_positions("USD") == []

    def test_auth_error_is_fatal(self, make_client):
        exchange = FakeExchange(
            private_post_auth_r_funding_credits_symbol=ccxt.AuthenticationError("bad key")
        )
        with pytest.raises(FatalError):
            make_client(exchange).get_active_positions("USD")


class TestGetActiveOffers:
    def test_returns_parsed_offers_without_cancelling(self, make_client):
        exchange = FakeExchange(
            private_post_auth_r_funding_offers_symbol=[make_offer_array(offer_id=5081917947)]
        )
        offers = make_client(exchange).get_active_offers("USD")

        assert offers[0]["id"] == 5081917947
        assert isinstance(offers[0]["id"], int)
        # 唯讀：整個呼叫過程不該碰到取消端點
        assert all(name != "private_post_auth_w_funding_offer_cancel" for name, _ in exchange.calls)

    def test_dry_run_returns_empty(self, fake_logger):
        assert BitfinexClient({}, fake_logger, dry_run=True).get_active_offers("USD") == []


def make_trade_row(trade_id=1, mts=1_786_879_800_000, amount=-25_000.0, rate=0.00025, period=2):
    """模擬 `/v2/trades/fUSD/hist` 的一列。

    欄位：0=ID, 1=MTS, 2=AMOUNT, 3=RATE, 4=PERIOD。形狀取自 2026-08-16 的實打回應
    ——**AMOUNT 有正有負**（表示吃單方向），而成交價是同一個數字，兩邊看到的都一樣。
    """
    return [str(trade_id), str(mts), str(amount), str(rate), str(period)]


class TestGetRecentTrades:
    def test_amount_sign_is_dropped_because_it_only_means_direction(self, make_client):
        exchange = FakeExchange(public_get_trades_symbol_hist=[
            make_trade_row(amount=-25_000.0),
            make_trade_row(amount=18_000.0),
        ])
        trades = make_client(exchange).get_recent_trades("USD")

        assert [trade["amount"] for trade in trades] == [25_000.0, 18_000.0]

    def test_sorted_by_time_ascending(self, make_client):
        exchange = FakeExchange(public_get_trades_symbol_hist=[
            make_trade_row(mts=300), make_trade_row(mts=100), make_trade_row(mts=200),
        ])
        trades = make_client(exchange).get_recent_trades("USD")

        assert [trade["mts"] for trade in trades] == [100, 200, 300]

    def test_string_fields_are_converted(self, make_client):
        exchange = FakeExchange(public_get_trades_symbol_hist=[
            make_trade_row(rate=0.0002808219178082192, period=120)
        ])
        trade = make_client(exchange).get_recent_trades("USD")[0]

        assert isinstance(trade["mts"], int)
        assert isinstance(trade["rate"], float)
        assert isinstance(trade["period"], int)
        assert trade["period"] == 120

    def test_non_positive_rate_is_skipped(self, make_client):
        exchange = FakeExchange(public_get_trades_symbol_hist=[
            make_trade_row(rate=0.0), make_trade_row(rate=0.00025),
        ])

        assert len(make_client(exchange).get_recent_trades("USD")) == 1

    def test_network_error_is_retryable(self, make_client):
        exchange = FakeExchange(public_get_trades_symbol_hist=ccxt.NetworkError("timeout"))
        with pytest.raises(RetryableError):
            make_client(exchange).get_recent_trades("USD")

    def test_malformed_row_is_retryable(self, make_client):
        exchange = FakeExchange(public_get_trades_symbol_hist=[["only-one-field"]])
        with pytest.raises(RetryableError):
            make_client(exchange).get_recent_trades("USD")

    def test_works_without_credentials(self, fake_logger, monkeypatch):
        """與掛單簿同一個理由：dry-run 也要能用真實市場資料驗定價。"""
        client = BitfinexClient({}, fake_logger, dry_run=True)
        exchange = FakeExchange(public_get_trades_symbol_hist=[make_trade_row(rate=0.00025)])
        monkeypatch.setattr(client, "_public_exchange", lambda: exchange)

        assert client.get_recent_trades("USD")[0]["rate"] == 0.00025
