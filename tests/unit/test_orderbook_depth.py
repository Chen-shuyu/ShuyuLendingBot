# -*- coding: utf-8 -*-
"""`OrderBookDepthStrategy` 的單元測試（見 DECISIONS.md D030）。

這個策略只有一個判斷：**在「排在我們前面的錢不超過預算」的前提下，挑利率最高的那一檔。**
所以測試也圍著那句話打轉——邊界（剛好等於預算、超過一分錢）、方向（升冪、降冪）、
以及兩條「寧可不掛」的出口（拿不到市場深度、市場價低於底線）。

測試資料的形狀取自 2026-08-16 對 `/v2/book/fUSD/P0` 的實打：利率是 0.00024 這種量級、
天期以 2 天為主，供給側金額動輒數十萬。用真實量級而不是 1／2／3 這種漂亮數字，
是 D027 的教訓——測試看到的世界比真實世界乾淨時，bug 就從那道縫鑽過去。
"""

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
        plans = make_strategy(target_queue_usd=1_000_000).build_offer_plan(344.0, 0.0003, MARKET_BOOK)

        assert len(plans) == 1
        assert plans[0].rate == 0.00025

    def test_counts_the_level_itself_because_same_rate_is_time_priority(self, make_strategy):
        # 預算 900k：700k 那檔進得去（累積 700k），但 0.000245 那檔會讓累積變成 900k——
        # 剛好等於預算，仍算通過。**同一個利率上我們是新單，得排在該檔現有的錢後面**，
        # 所以累積要「先加當檔再判斷」；少加這一筆就會高估自己的位置。
        plans = make_strategy(target_queue_usd=900_000).build_offer_plan(344.0, 0.0003, MARKET_BOOK)

        assert plans[0].rate == 0.000245

    def test_one_dollar_over_budget_falls_back_to_the_cheaper_level(self, make_strategy):
        plans = make_strategy(target_queue_usd=899_999).build_offer_plan(344.0, 0.0003, MARKET_BOOK)

        assert plans[0].rate == 0.00024

    def test_tiny_budget_still_offers_at_the_front_of_the_book(self, make_strategy):
        # 預算比最前面那一檔還小：使用者要的是「快」，掛在簿子最前面是唯一合理的解讀。
        plans = make_strategy(target_queue_usd=1.0).build_offer_plan(344.0, 0.0003, MARKET_BOOK)

        assert plans[0].rate == 0.00024

    def test_huge_budget_stops_at_the_top_of_the_book(self, make_strategy):
        # 預算大過整個供給側也不會掛到簿子外面——那正是舊策略掛空 78 輪的原因。
        plans = make_strategy(target_queue_usd=10**9).build_offer_plan(344.0, 0.0003, MARKET_BOOK)

        assert plans[0].rate == max(item["rate"] for item in MARKET_BOOK)

    def test_frr_does_not_affect_the_price(self, make_strategy):
        strategy = make_strategy()
        cheap = strategy.build_offer_plan(344.0, 0.0001, MARKET_BOOK)
        expensive = strategy.build_offer_plan(344.0, 0.9, MARKET_BOOK)

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

        assert strategy.build_offer_plan(344.0, 0.0003, MARKET_BOOK) == []

    def test_balance_below_threshold_means_no_offer(self, make_strategy):
        assert make_strategy().build_offer_plan(149.0, 0.0003, MARKET_BOOK) == []


class TestAmountsAndPeriod:
    def test_single_offer_by_default(self, make_strategy):
        plans = make_strategy().build_offer_plan(344.0, 0.0003, MARKET_BOOK)

        assert len(plans) == 1
        assert plans[0].amount == 344.0

    def test_uses_configured_offer_period(self, make_strategy):
        plans = make_strategy(offer_period=30).build_offer_plan(344.0, 0.0003, MARKET_BOOK)

        assert plans[0].duration == 30

    def test_falls_back_to_short_duration_when_offer_period_absent(self):
        strategy = OrderBookDepthStrategy(
            {"strategy": {"short_duration": 7, "target_queue_usd": 1_000_000}}
        )
        plans = strategy.build_offer_plan(344.0, 0.0003, MARKET_BOOK)

        assert plans[0].duration == 7

    def test_total_never_exceeds_balance_with_realistic_precision(self, make_strategy):
        # 真實餘額不是漂亮數字（實單那次是 160.00861413，四捨五入後掛 160.01 被拒單，
        # 見 D025）。這裡刻意餵同樣形狀的輸入。
        balance = 344.12345678
        plans = make_strategy(spread_count=2).build_offer_plan(balance, 0.0003, MARKET_BOOK)

        assert sum(plan.amount for plan in plans) <= balance

    def test_spread_steps_up_from_the_depth_price(self, make_strategy):
        plans = make_strategy(spread_count=2, target_queue_usd=1_000_000).build_offer_plan(
            400.0, 0.0003, MARKET_BOOK
        )

        assert len(plans) == 2
        assert plans[1].rate == round(plans[0].rate * 1.15, 6)

    def test_spread_downgrades_when_balance_cannot_fill_every_slice(self, make_strategy):
        plans = make_strategy(spread_count=3).build_offer_plan(344.0, 0.0003, MARKET_BOOK)

        assert len(plans) == 2  # 344 只塞得下 2 筆 150


class TestLendLimits:
    def test_absolute_cap_reduces_the_offer(self, make_strategy):
        plans = make_strategy(max_to_lend_usd=200).build_offer_plan(344.0, 0.0003, MARKET_BOOK)

        assert plans[0].amount == 200.0

    def test_percentage_cap_reduces_the_offer(self, make_strategy):
        plans = make_strategy(max_percent_to_lend=50).build_offer_plan(400.0, 0.0003, MARKET_BOOK)

        assert plans[0].amount == 200.0

    def test_cap_below_minimum_loan_size_means_no_offer(self, make_strategy):
        assert make_strategy(max_to_lend_usd=100).build_offer_plan(344.0, 0.0003, MARKET_BOOK) == []


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

    def test_levels_at_or_above_our_rate_are_not_counted_as_ahead(self, make_strategy):
        book = [level(0.000240, 100_000), level(0.000250, 900_000)]
        queue = make_strategy().describe_queue(book, 0.000250)

        assert queue["all_periods"] == 100_000
