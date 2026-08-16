# -*- coding: utf-8 -*-
"""`OrderBookDepthStrategy` 的單元測試（見 DECISIONS.md D030）。

這個策略只有一個判斷：**在「排在我們前面的錢不超過預算」的前提下，挑利率最高的那一檔。**
所以測試也圍著那句話打轉——邊界（剛好等於預算、超過一分錢）、方向（升冪、降冪）、
以及兩條「寧可不掛」的出口（拿不到市場深度、市場價低於底線）。

測試資料的形狀取自 2026-08-16 對 `/v2/book/fUSD/P0` 的實打：利率是 0.00024 這種量級、
天期以 2 天為主，供給側金額動輒數十萬。用真實量級而不是 1／2／3 這種漂亮數字，
是 D027 的教訓——測試看到的世界比真實世界乾淨時，bug 就從那道縫鑽過去。
"""

import statistics

import pytest

from strategies.orderbook_depth import OrderBookDepthStrategy


def level(rate, amount, period=2):
    return {"rate": rate, "period": period, "amount": amount}


# 形狀取自真實簿子：由低利率往高排，最前面幾檔就吃掉大部分金額。
MARKET_BOOK = [
    level(0.000240, 700_000),
    level(0.000245, 200_000),
    level(0.000250, 100_000),
    level(0.000255, 2_000_000),
    level(0.000260, 250_000),
    level(0.000270, 400_000),
]

# 2026-08-16 19:30:00 +0800，剛好落在 5 分鐘分桶的邊界上，桶號才好在測試裡數。
T0_MS = 1_786_879_800_000


def trade(minutes_after, rate, amount=25_000.0, period=2):
    return {
        "mts": T0_MS + int(minutes_after * 60_000),
        "amount": amount,
        "rate": rate,
        "period": period,
    }


# 形狀取自真實的 `/v2/trades/fUSD/hist`：同一小時內同天期成交緊貼在一個窄帶裡，
# 而長天期明顯更高（2026-08-16 實測 2 天期中位數 0.000261、30 天期 0.000319）。
def market_trades(rate=0.00025, count=60, period=2, amount=25_000.0):
    """一批同天期、等額的成交，金額加權中位數剛好等於 `rate`。

    **筆數一定要夠**（`min_trade_samples`）：實測 1000 筆成交在活躍時段只涵蓋
    1.2 分鐘，樣本不足時策略會整輪不掛單——測試若餵不夠，測到的是那條出口。
    """
    offsets = (-0.000002, 0.0, 0.000002)
    return [
        trade(index * 0.25, rate + offsets[index % 3], amount=amount, period=period)
        for index in range(count)
    ]


MARKET_TRADES = market_trades()


def trades_for(period, rate=0.00025):
    """某個天期的成交樣本。

    天期不是 2 天的測試要用這個——策略只採計同天期的成交（D033），
    餵 `MARKET_TRADES` 給 30 天期的策略會得到「樣本不足、本輪不掛」。
    """
    return market_trades(rate=rate, period=period)


@pytest.fixture
def make_strategy():
    def _build(**overrides):
        strategy = {
            "min_required_usd": 150,
            "min_loan_size_usd": 150,
            "minimum_rate": 0.0001,
            "spread_count": 1,
            "spread_step_pct": 0.15,
            "offer_period": 2,
            "target_queue_usd": 1_000_000,
            "max_to_lend_usd": 0,
            "max_percent_to_lend": 0,
        }
        strategy.update(overrides)
        return OrderBookDepthStrategy({"strategy": strategy})

    return _build


class TestPricingFromDepth:
    def test_picks_highest_rate_whose_queue_fits_the_budget(self, make_strategy):
        # 預算 100 萬：累積到 0.000250 那檔剛好是 700k+200k+100k = 100 萬，仍在預算內；
        # 下一檔 0.000255 會讓前方累積變成 300 萬，超出。
        plans = make_strategy(target_queue_usd=1_000_000).build_offer_plan(344.0, 0.0003, MARKET_BOOK, MARKET_TRADES)

        assert len(plans) == 1
        assert plans[0].rate == 0.00025

    def test_counts_the_level_itself_because_same_rate_is_time_priority(self, make_strategy):
        # 預算 900k：700k 那檔進得去（累積 700k），但 0.000245 那檔會讓累積變成 900k——
        # 剛好等於預算，仍算通過。**同一個利率上我們是新單，得排在該檔現有的錢後面**，
        # 所以累積要「先加當檔再判斷」；少加這一筆就會高估自己的位置。
        plans = make_strategy(target_queue_usd=900_000).build_offer_plan(344.0, 0.0003, MARKET_BOOK, MARKET_TRADES)

        assert plans[0].rate == 0.000245

    def test_one_dollar_over_budget_falls_back_to_the_cheaper_level(self, make_strategy):
        plans = make_strategy(target_queue_usd=899_999).build_offer_plan(344.0, 0.0003, MARKET_BOOK, MARKET_TRADES)

        assert plans[0].rate == 0.00024

    def test_tiny_budget_still_offers_at_the_front_of_the_book(self, make_strategy):
        # 預算比最前面那一檔還小：使用者要的是「快」，掛在簿子最前面是唯一合理的解讀。
        plans = make_strategy(target_queue_usd=1.0).build_offer_plan(344.0, 0.0003, MARKET_BOOK, MARKET_TRADES)

        assert plans[0].rate == 0.00024

    def test_huge_budget_stops_at_the_top_of_the_book(self, make_strategy):
        # 預算大過整個供給側也不會掛到簿子外面——那正是舊策略掛空 78 輪的原因。
        plans = make_strategy(target_queue_usd=10**9).build_offer_plan(344.0, 0.0003, MARKET_BOOK, MARKET_TRADES)

        assert plans[0].rate == max(item["rate"] for item in MARKET_BOOK)

    def test_frr_does_not_affect_the_price(self, make_strategy):
        strategy = make_strategy()
        cheap = strategy.build_offer_plan(344.0, 0.0001, MARKET_BOOK, MARKET_TRADES)
        expensive = strategy.build_offer_plan(344.0, 0.9, MARKET_BOOK, MARKET_TRADES)

        assert cheap[0].rate == expensive[0].rate


class TestRefusalPaths:
    """兩條「寧可不掛」的出口。掛一張不會成交的單，比不掛更糟——它看起來像有在放貸。"""

    def test_no_book_means_no_offer(self, make_strategy):
        assert make_strategy().build_offer_plan(344.0, 0.0003, []) == []
        assert make_strategy().build_offer_plan(344.0, 0.0003, None) == []

    def test_market_below_minimum_rate_means_no_offer(self, make_strategy):
        # minimum_rate 的語意是「低於這個價我就不借」，**不是「把價格拉高到這裡」**。
        # 舊策略的 max(base, minimum_rate) 會把單子推到簿子之外，變成永遠不成交的死單。
        strategy = make_strategy(minimum_rate=0.0005)

        assert strategy.build_offer_plan(344.0, 0.0003, MARKET_BOOK, MARKET_TRADES) == []

    def test_balance_below_threshold_means_no_offer(self, make_strategy):
        assert make_strategy().build_offer_plan(149.0, 0.0003, MARKET_BOOK, MARKET_TRADES) == []


class TestAmountsAndPeriod:
    def test_single_offer_by_default(self, make_strategy):
        plans = make_strategy().build_offer_plan(344.0, 0.0003, MARKET_BOOK, MARKET_TRADES)

        assert len(plans) == 1
        assert plans[0].amount == 344.0

    def test_uses_configured_offer_period(self, make_strategy):
        strategy = make_strategy(offer_period=30)
        plans = strategy.build_offer_plan(344.0, 0.0003, MARKET_BOOK, trades_for(30))

        assert plans[0].duration == 30

    def test_falls_back_to_short_duration_when_offer_period_absent(self):
        strategy = OrderBookDepthStrategy(
            {"strategy": {"short_duration": 7, "target_queue_usd": 1_000_000}}
        )
        plans = strategy.build_offer_plan(344.0, 0.0003, MARKET_BOOK, trades_for(7))

        assert plans[0].duration == 7

    def test_total_never_exceeds_balance_with_realistic_precision(self, make_strategy):
        # 真實餘額不是漂亮數字（實單那次是 160.00861413，四捨五入後掛 160.01 被拒單，
        # 見 D025）。這裡刻意餵同樣形狀的輸入。
        balance = 344.12345678
        plans = make_strategy(spread_count=2).build_offer_plan(balance, 0.0003, MARKET_BOOK, MARKET_TRADES)

        assert sum(plan.amount for plan in plans) <= balance

    def test_spread_steps_up_from_the_depth_price(self, make_strategy):
        strategy = make_strategy(spread_count=2, target_queue_usd=1_000_000)
        plans = strategy.build_offer_plan(400.0, 0.0003, MARKET_BOOK, MARKET_TRADES)

        assert len(plans) == 2
        # 階梯也要走 `_quantize`（無條件捨去），不能用 round——理由見 TestRateQuantization。
        assert plans[1].rate == strategy._quantize(plans[0].rate * 1.15)

    def test_spread_downgrades_when_balance_cannot_fill_every_slice(self, make_strategy):
        plans = make_strategy(spread_count=3).build_offer_plan(344.0, 0.0003, MARKET_BOOK, MARKET_TRADES)

        assert len(plans) == 2  # 344 只塞得下 2 筆 150


class TestLendLimits:
    def test_absolute_cap_reduces_the_offer(self, make_strategy):
        plans = make_strategy(max_to_lend_usd=200).build_offer_plan(344.0, 0.0003, MARKET_BOOK, MARKET_TRADES)

        assert plans[0].amount == 200.0

    def test_percentage_cap_reduces_the_offer(self, make_strategy):
        plans = make_strategy(max_percent_to_lend=50).build_offer_plan(400.0, 0.0003, MARKET_BOOK, MARKET_TRADES)

        assert plans[0].amount == 200.0

    def test_cap_below_minimum_loan_size_means_no_offer(self, make_strategy):
        assert make_strategy(max_to_lend_usd=100).build_offer_plan(344.0, 0.0003, MARKET_BOOK, MARKET_TRADES) == []


class TestDescribeQueue:
    """兩個排隊數字是留給第一筆真實成交去裁決的——沒有它們，事後什麼都學不到。"""

    def test_reports_same_period_and_all_periods_separately(self, make_strategy):
        book = [
            level(0.000240, 500_000, period=2),
            level(0.000242, 300_000, period=30),
            level(0.000245, 100_000, period=2),
        ]
        queue = make_strategy().describe_queue(book, 0.000250)

        assert queue["same_period"] == 600_000  # 只算 2 天期
        assert queue["all_periods"] == 900_000  # 全部天期一起算

    def test_same_rate_money_counts_as_ahead_because_of_time_priority(self, make_strategy):
        """同價位的錢要算進「前面」——我們是後到的，排在那一檔既有金額的後面。

        這條原本是反的（只算 `rate <`），與 `_price_from_depth()` 的算法互相矛盾。
        2026-08-16 夜間的後果：日誌報「前方 1,026 USD」，真實情況是 182 萬（D033）。
        """
        book = [level(0.000240, 100_000), level(0.000250, 900_000)]
        queue = make_strategy().describe_queue(book, 0.000250)

        assert queue["all_periods"] == 1_000_000

    def test_levels_above_our_rate_are_not_counted_as_ahead(self, make_strategy):
        book = [level(0.000240, 100_000), level(0.000250, 900_000)]
        queue = make_strategy().describe_queue(book, 0.000245)

        assert queue["all_periods"] == 100_000


class TestMarketRate:
    """常態成交價：借款人實際付了多少。訂單簿答不出這件事（D033）。"""

    def test_is_the_volume_weighted_median(self, make_strategy):
        assert make_strategy().market_rate(MARKET_TRADES) == pytest.approx(0.00025)

    def test_many_tiny_trades_cannot_outvote_the_money(self, make_strategy):
        """2026-08-16 夜間的真實形狀：一道低價牆被上百筆小額慢慢啃掉。

        實測整段 43 分鐘裡，利率低於 0.00016 的成交**佔筆數 11.5%、佔金額 29.9%**。
        按筆數算就會得到牆的價格（年化 5.47%），下限因此形同虛設——
        這正是最早那版「按時間分桶、每桶一票」失敗的原因。
        """
        nibbles = [trade(index * 0.05, 0.00015, amount=150.0) for index in range(200)]
        real = [trade(10 + index * 0.05, 0.00026, amount=25_000.0) for index in range(60)]

        assert statistics.median([item["rate"] for item in nibbles + real]) == 0.00015
        assert make_strategy().market_rate(nibbles + real) == pytest.approx(0.00026)

    def test_a_dead_period_barely_counts(self, make_strategy):
        """成交冷清的時段權重趨近於零，不能跟幾百萬 USD 的活躍時段平起平坐。"""
        quiet = [trade(index * 0.5, 0.00015, amount=150.0) for index in range(20)]

        assert make_strategy().market_rate(MARKET_TRADES + quiet) == pytest.approx(0.00025)

    def test_other_periods_are_ignored(self, make_strategy):
        """長天期的價格明顯較高，混進來會把短天期的下限拉高而掛空。"""
        long_only = trades_for(30, rate=0.00032)

        assert make_strategy(offer_period=2).market_rate(long_only) is None
        assert make_strategy(offer_period=30).market_rate(long_only) == pytest.approx(0.00032)

    def test_too_few_samples_means_no_answer(self, make_strategy):
        assert make_strategy().market_rate(market_trades(count=10)) is None

    def test_stale_trades_outside_the_window_are_dropped(self, make_strategy):
        """市場冷清時，半天前的成交不能拿來當「現在的價格」。"""
        stale = [trade(-60 * 10 + index * 0.25, 0.00025) for index in range(60)]

        assert make_strategy(trade_window_hours=6).market_rate(stale + [trade(0, 0.00031)]) is None

    def test_no_trades_means_no_answer(self, make_strategy):
        assert make_strategy().market_rate(None) is None
        assert make_strategy().market_rate([]) is None


class TestMarketFloor:
    """訂單簿被一筆低價大單佔住時，成交價下限要把我們拉回市場（D033）。"""

    # 重現 2026-08-16 21:21 的簿子：最底端一道 182 萬 USD 的低價牆，
    # 而同一時間 2 天期的實際成交在 0.00025 附近。
    WALL_BOOK = [
        level(0.00014999, 775.90),
        level(0.000149995, 250.00),
        level(0.00015, 1_821_212.68),
        level(0.00025, 500_000),
        level(0.00027, 400_000),
    ]

    def test_a_cheap_wall_no_longer_drags_the_offer_to_half_the_market_rate(self, make_strategy):
        """事故重現：修好之前這裡會掛出 0.00015（年化 5.47%），市場卻在 0.00025。"""
        plans = make_strategy().build_offer_plan(344.30, 0.0003, self.WALL_BOOK, MARKET_TRADES)

        assert len(plans) == 1
        # 常態成交價 0.00025 × market_floor_pct 0.85 = 0.0002125
        assert plans[0].rate == pytest.approx(0.0002125, rel=1e-6)

    def test_the_floor_never_pushes_the_price_down(self, make_strategy):
        """排隊規則算出來的價位比下限好時，下限不該把它砍低。"""
        plans = make_strategy().build_offer_plan(344.0, 0.0003, MARKET_BOOK, MARKET_TRADES)

        assert plans[0].rate == 0.00025

    def test_floor_pct_one_means_never_below_the_market(self, make_strategy):
        plans = make_strategy(market_floor_pct=1.0).build_offer_plan(
            344.30, 0.0003, self.WALL_BOOK, MARKET_TRADES
        )

        assert plans[0].rate == pytest.approx(0.00025, rel=1e-6)

    def test_no_trades_means_no_offer(self, make_strategy):
        """看不見成交價就不掛。代價不對稱：少掛一輪損失幾毫，掛錯價位是半價鎖住好幾天。"""
        assert make_strategy().build_offer_plan(344.0, 0.0003, MARKET_BOOK, None) == []
        assert make_strategy().build_offer_plan(344.0, 0.0003, MARKET_BOOK, []) == []


class TestRateQuantization:
    """送出前一律無條件捨去。四捨五入會把我們推到牆的後面（D033）。"""

    def test_rounds_down_never_up(self, make_strategy):
        strategy = make_strategy()

        # 事故當天的實際數字：round(0.000149995, 6) = 0.00015，正好等於那道牆的利率。
        assert round(0.000149995, 6) == 0.00015
        assert strategy._quantize(0.000149995) == 0.00014999

    def test_the_offer_stays_in_front_of_a_wall_at_the_next_tick(self, make_strategy):
        """捨去後的價位必須嚴格低於牆，否則時間優先會讓我們排到 182 萬後面。"""
        wall_rate = 0.00015
        book = [level(0.000149995, 250.0), level(wall_rate, 1_821_212.68)]
        plans = make_strategy(target_queue_usd=1_000).build_offer_plan(
            344.30, 0.0003, book, market_trades(rate=0.000160)
        )

        assert plans[0].rate < wall_rate

    def test_precision_is_configurable(self, make_strategy):
        assert make_strategy(rate_decimals=6)._quantize(0.000149995) == 0.000149
