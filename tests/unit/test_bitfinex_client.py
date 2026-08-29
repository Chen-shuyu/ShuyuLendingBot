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
from utils.exceptions import FatalError, RetryableError, SkipCycleError

# Bitfinex V2 funding offer 陣列：0=ID, 1=SYMBOL, 2=MTS_CREATE, 3=MTS_UPDATE,
# 4=AMOUNT, 5=AMOUNT_ORIG, 6=TYPE, 10=STATUS, 14=RATE, 15=PERIOD
# https://docs.bitfinex.com/reference/rest-auth-funding-offers
#
# 🔴 **21 不是 16。** 這個常數原本寫 16，而 `_parse_offers()` 的 docstring
# 從 2026-08-16 起就寫著「21 欄」——**程式知道真相，替身不知道**，兩邊沒有人
# 去對過。目前讀到的最大索引是 15，所以還沒出事；但 [10]=STATUS 在 16 欄的
# 替身裡是 `None`，而真實回應是 `'ACTIVE'`。哪天要靠 STATUS 濾掉非作用中的
# 掛單，測試會拿 `None` 走完全程然後亮綠燈（2026-08-29 實打確認，B6）。
FUNDING_OFFER_FIELDS = 21


# https://docs.bitfinex.com/reference/rest-auth-funding-credits
#
# credits 是 **22 欄**（索引 0～21），比 loans 多最後那一欄 `POSITION_PAIR`
# ——2026-08-29 實打確認（B6）。`_parse_positions()` 的 docstring 從一開始就寫著
# 「credits 比 loans 多一個 21=POSITION_PAIR」，這次是第一次拿真實回應對上。
FUNDING_CREDIT_FIELDS = 22


# 2026-08-19 05:03:24 +0800，取自那天場上唯一一張單的真實回應（見 D038）。
OFFER_CREATED_MS = "1787087004000"


# 2026-08-29 17:56 +0800 對 `GET /v2/ticker/fUSD` 實打一次抄回來的（B6／D027 第 1 點）。
#
# **三件事只有實打才看得到，而三件事這個替身原本都不知道**：
#   1. **17 欄**，不是 4 欄。Bitfinex 文件只列到 [15]，實際還多一欄 [16]（毫秒時間戳）。
#   2. **除了兩個佔位以外全是字串**，包含 PERIOD 這種本質上是整數的欄位。
#   3. **[13][14] 是 `None`**——不是 0、不是空字串。任何「先轉型再判斷」的寫法
#      碰到它就會炸，而原本那個 `[0.00035, 1, 2, 3]` 的替身永遠測不到。
#
# **不要為了好寫而把它整理乾淨**（D027 第 3 點）——那正是 D025／D026 兩個 bug
# 用真錢換來的教訓。
REAL_TICKER_FUSD = [
    "0.0003119890410958904",  # [ 0] FRR ← get_frr() 只讀這一欄
    "0.000273972602739726",   # [ 1] BID
    "120",                    # [ 2] BID_PERIOD
    "18655088.09552367",      # [ 3] BID_SIZE
    "0.00016",                # [ 4] ASK
    "5",                      # [ 5] ASK_PERIOD
    "7346513.09807776",       # [ 6] ASK_SIZE
    "-0.00022404",            # [ 7] DAILY_CHANGE
    "-0.7518",                # [ 8] DAILY_CHANGE_PERC
    "0.00007397",             # [ 9] LAST_PRICE
    "120196467.90810657",     # [10] VOLUME
    "0.0003",                 # [11] HIGH
    "0.0000258",              # [12] LOW
    None,                     # [13] _PLACEHOLDER ← 真的是 None
    None,                     # [14] _PLACEHOLDER ← 真的是 None
    "271504913.17164093",     # [15] FRR_AMOUNT_AVAILABLE
    "1469734163000",          # [16] 文件沒列，實際存在
]


def make_ticker_array(frr=None):
    """模擬 `/v2/ticker/fUSD` 的回應，形狀取自真實回應（見 `REAL_TICKER_FUSD`）。

    只換掉 [0]（FRR），其餘 16 欄維持實打抄回來的樣子——**測試要換的是被斷言的
    那個值，不是信封的形狀**。
    """
    ticker = list(REAL_TICKER_FUSD)
    if frr is not None:
        ticker[0] = str(frr)
    return ticker


def make_offer_array(
    offer_id=101,
    symbol="fUSD",
    amount=200.0,
    rate=0.0004,
    period=2,
    created_at_ms=OFFER_CREATED_MS,
    status="ACTIVE",
):
    """模擬 ccxt 回傳的 funding offer 陣列。

    **每個數值欄位都是字串**——實測 ccxt 對這個 implicit 端點回傳的就是
    `'5081103121'`、`'160'`、`'0.000523'`、`'2'`，不是數字。
    這個替身原本回傳原生型別，比真實 API「乾淨」，於是漏掉了「取消時 id 必須
    轉回整數」這個 bug：實單下每一輪都取消失敗（2026-08-15，見 DECISIONS.md D026）。
    替身要像真的，不然測試只是在驗證另一個世界。

    `created_at_ms`（index 2 = MTS_CREATE）同樣以字串給，理由與上面完全一樣——
    它是閒置時間量測的基準，用原生 int 會讓 `_optional_millis()` 的字串轉換
    永遠測不到（D038）。
    """
    offer = [None] * FUNDING_OFFER_FIELDS
    offer[0] = str(offer_id)
    offer[1] = symbol
    offer[2] = created_at_ms
    offer[3] = created_at_ms  # MTS_UPDATE，沒被動過的單與 MTS_CREATE 同值（D038）
    offer[4] = str(amount)
    offer[5] = str(amount)    # AMOUNT_ORIG
    offer[6] = "LIMIT"        # TYPE
    offer[10] = status        # STATUS ← 真實回應是 'ACTIVE'，不是 None
    offer[14] = str(rate)
    offer[15] = str(period)
    offer[16] = "0"
    offer[17] = "0"
    offer[19] = "0"
    return offer


# 2026-08-29 17:5x 對 `POST /v2/auth/r/funding/offers/fUSD` 實打抄回來的整列（B6）。
# 抄得到是因為**當下場上剛好躺著一張單**——這個端點平常回空陣列，
# 沒有掛單的時候抄不到任何形狀。
REAL_FUNDING_OFFER = [
    "5096173429", "fUSD", "1787989255000", "1787989255000", "345.02", "345.02",
    "LIMIT", None, None, None, "ACTIVE", None, None, None, "0.0003", "2",
    "0", "0", None, "0", None,
]


# 2026-08-29 17:5x `fetch_balance({"type": "funding"})` 實打抄回來的（B6）。
#
# 🔴 **兩件替身原本不知道的事**：
#   1. `USD` 那一層有 `free`／`used`／`total` 三個鍵，而且 ccxt **已經轉成 float**
#      ——外層那三個同名鍵則是「幣別 → 數字」的字典，兩層同名但形狀不同。
#   2. **`info` 裡混著別的錢包。** 指定了 `type='funding'` 也一樣：這次回來的第二列
#      是 `exchange`／`UST`。任何直接讀 `info` 的程式碼都必須自己濾 `[0] == 'funding'`，
#      不濾就會把別的錢包的錢算進放貸餘額。
#
# 金額用真實精度（8 位小數）——D025 那個 bug 就是被兩位小數的測試資料放過去的。
REAL_FUNDING_BALANCE = {
    "USD": {"free": 0.00175079, "used": 345.02, "total": 345.02175079},
    "free": {"USD": 0.00175079},
    "used": {"USD": 345.02},
    "total": {"USD": 345.02175079},
    "info": [
        ["funding", "USD", "345.02175079", "0", "0.00175079", None, None],
        ["exchange", "UST", "0.01187148", "0", "0.01187148", "Affiliate Rebate", None],
    ],
}


# 2026-08-29 21:5x 對 `POST /v2/auth/r/funding/credits/fUSD` 實打抄回來的整列（B6）。
# 抄得到是因為**當下剛好有一筆部位在生息**——08-29 17:5x 那次實打時帳號沒有部位，
# 這個端點回空陣列，所以 B6 當時只能把它留成 🟡。
#
# 🔴 **三件替身原本不知道的事**：
#   1. **credits 是 22 欄**（索引 0～21），最後一欄 `[21]` 是 `POSITION_PAIR`
#      ——這次拿到的是 `'tBTCUSD'`，也就是借款人把這筆錢用在哪個交易對上。
#   2. **`[8]` 是 `RATE_TYPE`，真實值 `'FIXED'`**，替身留 `None`。
#      這是 D027 那族坑的第三次現身（`REAL_FUNDING_OFFER[10]` 的 `'ACTIVE'` 是第二次）：
#      哪天要靠它濾掉 FRR 浮動利率的部位，測試會拿 `None` 走完全程然後亮綠燈。
#   3. **`[3]`／`[4]`（MTS_CREATE／MTS_UPDATE）有值且與 `[13]`（MTS_OPENING）相同**，
#      替身這三格只填了 `[13]`。三個時間戳同值是「掛單成交當下就開始計息」的樣子，
#      不是巧合——但**只有一個樣本，不能當成不變量**。
#
# 22 欄裡有 7 個 `None`，數值全是字串（含 `'345.02'`、`'0.0003'`、`'2'`）。
REAL_FUNDING_CREDIT = [
    "464812689", "fUSD", "1", "1788007933000", "1788007933000", "345.02", "0",
    "ACTIVE", "FIXED", None, None, "0.0003", "2", "1788007933000", None, None,
    "0", None, "0", None, "0", "tBTCUSD",
]


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
    def test_parses_the_real_captured_balance(self, make_client):
        """B6：直接吃 2026-08-29 實打抄回來的那一份，一個字都沒改。

        可用餘額 `0.00175079` 是**八位小數**——原本的替身給 `344.12`，兩位。
        D025 那個 bug（總額超過餘額）就是被兩位小數的測試資料放過去的：
        `floor` 與 `round` 在那種輸入下數學上必然相同，測試不可能失敗。
        """
        exchange = FakeExchange(fetch_balance=dict(REAL_FUNDING_BALANCE))
        assert make_client(exchange).get_available_balance("USD") == 0.00175079

    def test_info_carries_other_wallets_even_when_type_is_funding(self, make_client):
        """🔴 指定了 `type='funding'`，`info` 裡照樣有別的錢包。

        這次實打回來的第二列是 `exchange`／`UST`。**目前的解析走的是 ccxt 整理過的
        `balance['USD']['free']`，所以踩不到**——這條守的是以後：哪天有人為了拿
        原始精度而改讀 `info`，不濾 `[0] == 'funding'` 就會把交易錢包的錢
        算進放貸餘額。替身要留著這一列，不然那個 bug 只能用真錢換。
        """
        wallets = [row[0] for row in REAL_FUNDING_BALANCE["info"]]
        assert "funding" in wallets and "exchange" in wallets
        # ccxt 整理過的那一層只認 funding，數字對得上
        assert REAL_FUNDING_BALANCE["USD"]["free"] == 0.00175079

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
        exchange = FakeExchange(public_get_ticker_symbol=make_ticker_array(0.00035))
        assert make_client(exchange).get_frr("USD") == pytest.approx(0.00035)
        assert exchange.calls[0] == ("public_get_ticker_symbol", {"symbol": "fUSD"})

    def test_parses_the_real_seventeen_field_envelope(self, make_client):
        """B6：直接吃 2026-08-29 實打抄回來的那一份，一個字都沒改。

        原本這一組測試餵的是 `[0.00035, 1, 2, 3]`——**4 欄、原生 float/int、
        沒有 None**。三個性質都跟真實回應不同，而 `float(ticker[0])` 剛好兩種
        都吃得下，所以測試一直是綠的。**綠燈不代表驗過真實世界**（D027）。
        """
        exchange = FakeExchange(public_get_ticker_symbol=list(REAL_TICKER_FUSD))
        assert make_client(exchange).get_frr("USD") == pytest.approx(0.0003119890410958904)

    def test_placeholder_nulls_do_not_break_parsing(self, make_client):
        """[13][14] 真的是 `None`——不是 0、不是空字串。

        `get_frr()` 只讀 [0] 所以現在踩不到，這條守的是**以後**：任何往後
        索引的新程式碼，會在這裡先撞到 None，而不是在實盤那一刻。
        """
        ticker = make_ticker_array(0.00035)
        assert ticker[13] is None and ticker[14] is None
        assert make_client(FakeExchange(public_get_ticker_symbol=ticker)).get_frr("USD") == (
            pytest.approx(0.00035)
        )

    def test_uses_funding_symbol_prefix(self, make_client):
        exchange = FakeExchange(public_get_ticker_symbol=make_ticker_array(0.0001))
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
            "created_at_ms": 1787087004000,
            "amount": 150.5,
            "rate": 0.00042,
            "period": 30,
        }

    def test_missing_or_broken_created_at_becomes_none(self, make_client):
        """時間戳壞掉不能讓查詢掛單失敗，也不能默默變成 0（那會是 1970 年掛的單）。"""
        exchange = FakeExchange(
            private_post_auth_r_funding_offers_symbol=[
                make_offer_array(7, created_at_ms=None),
                make_offer_array(8, created_at_ms="not-a-number"),
            ],
            private_post_auth_w_funding_offer_cancel={},
        )
        parsed = make_client(exchange).cancel_active_offers("USD")
        assert [offer["created_at_ms"] for offer in parsed] == [None, None]

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

    # B5／D025：ccxt 把 Bitfinex 的「餘額不足」歸類成 `AuthenticationError`，
    # 於是它走 FatalError 那一支——機器人**永久停止**，日誌還寫「認證失敗」。
    # 這一組守住兩件事：分類看訊息而不是型別，以及真正的認證問題仍然停機。
    @pytest.mark.parametrize(
        "error",
        [
            # 取自 D025 首次實單的真實回應原文
            ccxt.AuthenticationError(
                "Invalid offer: not enough USD balance available in deposit wallet"
            ),
            ccxt.ExchangeError("Insufficient funds"),
        ],
    )
    def test_insufficient_balance_is_skip_not_fatal(self, make_client, error):
        client = make_client(FakeExchange(private_post_auth_w_funding_offer_submit=error))
        with pytest.raises(SkipCycleError):
            client.create_loan_offer("USD", 200.0, 0.0004, 2)

    def test_insufficient_balance_log_says_balance_not_auth(self, make_client, fake_logger):
        """半夜看到「認證失敗」會往金鑰權限查，而真正的問題在金額——B5 的成本就是這個。"""
        client = make_client(
            FakeExchange(
                private_post_auth_w_funding_offer_submit=ccxt.AuthenticationError(
                    "Invalid offer: not enough USD balance available in deposit wallet"
                )
            )
        )
        with pytest.raises(SkipCycleError):
            client.create_loan_offer("USD", 200.0, 0.0004, 2)

        assert any("餘額不足" in text for text in fake_logger.messages["warning"])
        assert not any("認證失敗" in text for text in fake_logger.all_messages())

    @pytest.mark.parametrize(
        "message",
        ["apikey: invalid", "Invalid X-BFX-SIGNATURE", "permission denied"],
    )
    def test_real_auth_error_is_still_fatal(self, make_client, message):
        """只有訊息說餘額不足才降級。誤把金鑰問題當成「本輪略過」，
        機器人會拿無效金鑰空轉一整天——這個方向的誤判貴得多。"""
        client = make_client(
            FakeExchange(
                private_post_auth_w_funding_offer_submit=ccxt.AuthenticationError(message)
            )
        )
        with pytest.raises(FatalError):
            client.create_loan_offer("USD", 200.0, 0.0004, 2)

    def test_insufficient_balance_in_envelope_is_also_skip(self, make_client):
        """拒單也可能走回應信封而不是例外，兩條路要問同一個問題。"""
        exchange = FakeExchange(
            private_post_auth_w_funding_offer_submit=make_submit_response(
                status="ERROR",
                text="Invalid offer: not enough USD balance available in deposit wallet",
            )
        )
        with pytest.raises(SkipCycleError):
            make_client(exchange).create_loan_offer("USD", 200.0, 0.0004, 2)

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


# 2026-08-29 17:56 +0800 對 `GET /v2/book/fUSD/P0` 實打抄回來的兩列（B6）。
# 供給側 AMOUNT 為正、需求側為負；**四欄全是字串**，PERIOD 也是。
# 需求側那一列的 PERIOD 是 `'120'`——**天期不是只有 2**，寫死 2 的替身看不到這件事。
REAL_BOOK_ROW_SUPPLY = ["0.00015955", "2", "2", "956.79220808"]
REAL_BOOK_ROW_DEMAND = ["0.000273972602739726", "120", "1", "-2324092.18650454"]


def make_book_row(rate, period, amount, count=1):
    """模擬 `/v2/book/fUSD/P0` 的一列：[RATE, PERIOD, COUNT, AMOUNT]。

    **每個欄位都是字串**，利率還是 `'0.000273972602739726'` 這種長浮點——
    形狀取自 2026-08-16 的實打回應，**2026-08-29 重打一次確認沒變**（B6）。
    負的 AMOUNT 是借款需求側，實例見 `REAL_BOOK_ROW_DEMAND`。
    """
    return [str(rate), str(period), str(count), str(amount)]


def make_position_array(position_id="1", symbol="fUSD", amount=160.0, rate=0.00025, period=2,
                        opened_at=1786872920000, length=22):
    """模擬 funding credits／loans 的一列。

    欄位（官方文件）：0=ID, 1=SYMBOL, 5=AMOUNT, 7=STATUS, 11=RATE, 12=PERIOD, 13=MTS_OPENING。

    **credits 那一半已於 2026-08-29 實打校正**（見 `REAL_FUNDING_CREDIT`）：
    22 欄、數值全是字串、`[8]=RATE_TYPE` 是 `'FIXED'` 而不是 `None`。
    ⚠ **loans 那一半仍未校正**——它要「已借走但還沒用掉」的時刻，實打當下錢已經
    被借走了，端點回空陣列。`length=21` 這個預設值仍取自官方文件，不是抄來的。
    """
    row = [None] * length
    row[0] = str(position_id)
    row[1] = symbol
    row[2] = "1"              # SIDE
    row[3] = str(opened_at) if opened_at is not None else None   # MTS_CREATE
    row[4] = str(opened_at) if opened_at is not None else None   # MTS_UPDATE
    row[5] = str(amount)
    row[6] = "0"
    row[7] = "ACTIVE"         # STATUS
    row[8] = "FIXED"          # RATE_TYPE ← 真實回應是 'FIXED'，不是 None
    row[11] = str(rate)
    row[12] = str(period)
    row[13] = str(opened_at) if opened_at is not None else None  # MTS_OPENING
    row[16] = "0"
    row[18] = "0"
    row[20] = "0"
    if length > 21:
        row[21] = "tBTCUSD"   # POSITION_PAIR，只有 credits 有這一欄
    return row


class TestGetFundingBook:
    def test_parses_the_real_captured_rows(self, make_client):
        """B6：直接吃 2026-08-29 實打抄回來的兩列，一個字都沒改。"""
        exchange = FakeExchange(public_get_book_symbol_precision=[
            list(REAL_BOOK_ROW_SUPPLY),
            list(REAL_BOOK_ROW_DEMAND),
        ])
        levels = make_client(exchange).get_funding_book("USD")

        # 需求側（負 AMOUNT）被丟掉，只剩供給側那一列
        assert len(levels) == 1
        assert levels[0] == {"rate": 0.00015955, "period": 2, "amount": 956.79220808}

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
    def test_parses_the_real_captured_credit(self, make_client):
        """B6：直接吃 2026-08-29 實打抄回來的整列（22 欄），一個字都沒改。

        抄得到是因為當下剛好有一筆部位在生息。**這一列走完整條鏈路核對過**：
        交易所原始列 → `_parse_positions()` → DB 的 `funding_positions`，
        三處的 `amount`／`rate`／`period`／`opened_at` 完全一致。
        """
        exchange = FakeExchange(
            private_post_auth_r_funding_credits_symbol=[list(REAL_FUNDING_CREDIT)],
            private_post_auth_r_funding_loans_symbol=[],
        )
        positions = make_client(exchange).get_active_positions("USD")

        assert positions == [{
            "id": "464812689",
            "symbol": "fUSD",
            "amount": 345.02,
            "rate": 0.0003,
            "period": 2,
            "opened_at": 1788007933000,   # 2026-08-29T20:52:13+08:00
            "kind": "credit",
        }]

    def test_real_credit_has_twenty_two_fields_with_rate_type(self):
        """欄數、STATUS、RATE_TYPE 都要對得上真實回應，否則替身只是另一個世界。

        **`[8]` 這一格是這次實打的收穫**：真實是 `'FIXED'`，替身留 `None`。
        與 `REAL_FUNDING_OFFER[10]` 的 `'ACTIVE'` 同一族——欄位存在、
        替身卻用 `None` 走完全程，是 D027 記的那個坑。
        """
        assert len(REAL_FUNDING_CREDIT) == FUNDING_CREDIT_FIELDS == 22
        assert REAL_FUNDING_CREDIT[7] == "ACTIVE"
        assert REAL_FUNDING_CREDIT[8] == "FIXED"
        assert REAL_FUNDING_CREDIT[21] == "tBTCUSD"   # credits 比 loans 多的那一欄
        assert len(make_position_array()) == FUNDING_CREDIT_FIELDS

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
    def test_parses_the_real_captured_offer(self, make_client):
        """B6：直接吃 2026-08-29 實打抄回來的整列（21 欄），一個字都沒改。

        抄得到是因為當下場上剛好躺著一張單——這個端點平常回空陣列。
        **21 欄裡有 8 個 `None`**，而替身原本只有 16 欄、[10] 也是 `None`
        而不是 `'ACTIVE'`。
        """
        exchange = FakeExchange(
            private_post_auth_r_funding_offers_symbol=[list(REAL_FUNDING_OFFER)]
        )
        offers = make_client(exchange).get_active_offers("USD")

        assert offers == [{
            "id": 5096173429,          # 字串轉整數——取消端點只收整數（D026）
            "symbol": "fUSD",
            "created_at_ms": 1787989255000,
            "amount": 345.02,
            "rate": 0.0003,
            "period": 2,
        }]

    def test_real_envelope_has_twenty_one_fields_with_active_status(self):
        """欄數與 STATUS 都要對得上真實回應，否則替身只是另一個世界。"""
        assert len(REAL_FUNDING_OFFER) == FUNDING_OFFER_FIELDS == 21
        assert REAL_FUNDING_OFFER[10] == "ACTIVE"
        assert make_offer_array()[10] == "ACTIVE"

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


# 2026-08-29 17:56 +0800 對 `GET /v2/trades/fUSD/hist` 實打抄回來的兩列（B6）。
# **五欄全是字串**；AMOUNT 正負都出現，PERIOD 同樣不是只有 2。
REAL_TRADE_ROW_POSITIVE = ["430955886", "1787997395000", "500", "0.00007397", "2"]
REAL_TRADE_ROW_NEGATIVE = ["430955884", "1787997234000", "-155513.4357044", "0.00019", "5"]


def make_trade_row(trade_id=1, mts=1_786_879_800_000, amount=-25_000.0, rate=0.00025, period=2):
    """模擬 `/v2/trades/fUSD/hist` 的一列。

    欄位：0=ID, 1=MTS, 2=AMOUNT, 3=RATE, 4=PERIOD。形狀取自 2026-08-16 的實打回應，
    **2026-08-29 重打一次確認五欄真的全是字串**（B6）——在那之前
    `get_recent_trades()` 的註解寫的是「欄位**可能**是字串」，那個「可能」
    是猜的，現在不是了。
    **AMOUNT 有正有負**（表示吃單方向），而成交價是同一個數字，兩邊看到的都一樣。
    """
    return [str(trade_id), str(mts), str(amount), str(rate), str(period)]


class TestGetRecentTrades:
    def test_parses_the_real_captured_rows(self, make_client):
        """B6：直接吃 2026-08-29 實打抄回來的兩列，一個字都沒改。

        `make_trade_row()` 的形狀本來就對，但**沒有任何一條測試吃過未經加工的
        真實列**——「照抄」與「照抄後還是綠的」是兩件事。
        """
        exchange = FakeExchange(public_get_trades_symbol_hist=[
            list(REAL_TRADE_ROW_NEGATIVE),
            list(REAL_TRADE_ROW_POSITIVE),
        ])
        trades = make_client(exchange).get_recent_trades("USD")

        assert [t["rate"] for t in trades] == [0.00019, 0.00007397]
        # 正負都被取絕對值——方向不影響成交價
        assert [t["amount"] for t in trades] == [155513.4357044, 500.0]
        # PERIOD 不是只有 2
        assert [t["period"] for t in trades] == [5, 2]

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
