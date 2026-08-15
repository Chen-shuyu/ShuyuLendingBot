# -*- coding: utf-8 -*-
"""`strategies/frr_plus.py` 的單元測試。

策略層是純函式，是整支程式最值得測、也最容易測的一層：掛錯利率或算錯金額
會直接變成真金白銀的損失，而這裡不需要任何交易所連線就能完整驗證。
"""

import pytest

from strategies.base import OfferPlan
from strategies.frr_plus import FrrPlusStrategy


class TestMinimumThreshold:
    """餘額門檻：低於門檻就整輪不掛單。"""

    def test_balance_below_min_required_returns_empty(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config(min_required_usd=150))
        assert strategy.build_offer_plan(149.99, 0.0002) == []

    def test_balance_exactly_at_min_required_still_lends(self, strategy_config):
        # 邊界值：判斷式是 `<` 而非 `<=`，剛好等於門檻要能掛單
        strategy = FrrPlusStrategy(strategy_config(min_required_usd=150, min_loan_size_usd=150))
        plans = strategy.build_offer_plan(150.0, 0.0002)
        assert len(plans) == 1
        assert plans[0].amount == 150.0

    def test_zero_balance_returns_empty(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config())
        assert strategy.build_offer_plan(0.0, 0.0002) == []

    def test_lendable_below_min_loan_size_returns_empty(self, strategy_config):
        """過了 min_required_usd 但不足單筆最小量，一樣不掛。"""
        strategy = FrrPlusStrategy(strategy_config(min_required_usd=100, min_loan_size_usd=150))
        assert strategy.build_offer_plan(120.0, 0.0002) == []


class TestRateLadder:
    """spread 階梯利率：基準利率 + 逐階百分比遞增。"""

    def test_base_rate_is_frr_plus_premium(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config(spread_count=1))
        plans = strategy.build_offer_plan(200.0, 0.0002)
        assert plans[0].rate == pytest.approx(0.0004)

    def test_minimum_rate_acts_as_floor(self, strategy_config):
        """FRR 崩到極低時，掛單利率不得低於 minimum_rate。"""
        strategy = FrrPlusStrategy(
            strategy_config(spread_count=1, premium_rate=0.0, minimum_rate=0.0003)
        )
        plans = strategy.build_offer_plan(200.0, 0.00001)
        assert plans[0].rate == pytest.approx(0.0003)

    def test_negative_frr_still_respects_minimum_rate(self, strategy_config):
        """FRR 理論上不會是負數，但真的拿到負值也不能掛出負利率。"""
        strategy = FrrPlusStrategy(strategy_config(spread_count=1, minimum_rate=0.0001))
        plans = strategy.build_offer_plan(200.0, -0.5)
        assert plans[0].rate == pytest.approx(0.0001)

    def test_rates_increase_by_step_percentage(self, strategy_config):
        # frr 0.0002 + premium 0.0002 = 0.0004，每階 ×1.15
        strategy = FrrPlusStrategy(strategy_config())
        plans = strategy.build_offer_plan(600.0, 0.0002)
        assert [plan.rate for plan in plans] == [0.0004, 0.00046, 0.000529]

    def test_rates_are_strictly_ascending(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config())
        rates = [plan.rate for plan in strategy.build_offer_plan(600.0, 0.0004)]
        assert rates == sorted(rates)
        assert len(set(rates)) == len(rates)

    def test_zero_step_pct_gives_flat_ladder(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config(spread_step_pct=0.0))
        rates = [plan.rate for plan in strategy.build_offer_plan(600.0, 0.0002)]
        assert rates == [0.0004, 0.0004, 0.0004]


class TestSpreadCount:
    """筆數自動降階：金額不夠拆滿時逐階退回，確保每筆都達到交易所最小單量。"""

    def test_full_count_when_balance_is_enough(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config(spread_count=3, min_loan_size_usd=150))
        assert len(strategy.build_offer_plan(450.0, 0.0002)) == 3

    def test_steps_down_when_balance_is_short(self, strategy_config):
        """449 元拆 3 筆會讓每筆低於 150，必須降到 2 筆。"""
        strategy = FrrPlusStrategy(strategy_config(spread_count=3, min_loan_size_usd=150))
        assert len(strategy.build_offer_plan(449.0, 0.0002)) == 2

    def test_steps_down_to_single_offer(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config(spread_count=3, min_loan_size_usd=150))
        assert len(strategy.build_offer_plan(299.0, 0.0002)) == 1

    def test_every_offer_meets_min_loan_size(self, strategy_config):
        """降階的目的就是這條：任何情況下每筆都不得低於最小單量。"""
        strategy = FrrPlusStrategy(strategy_config(spread_count=4, min_loan_size_usd=150))
        for balance in (150.0, 200.0, 301.0, 455.0, 620.0, 1000.0):
            plans = strategy.build_offer_plan(balance, 0.0002)
            assert all(plan.amount >= 150.0 for plan in plans), f"餘額 {balance} 出現低於最小單量的掛單"


class TestAmountSplit:
    """金額拆分：均分、餘數併入第一筆、加總不得超過可用餘額。"""

    def test_split_is_even_with_remainder_on_first(self, strategy_config):
        # 500 / 3 除不盡：166.66 × 3 = 499.98，餘 0.02 併進第一筆
        strategy = FrrPlusStrategy(strategy_config())
        amounts = [plan.amount for plan in strategy.build_offer_plan(500.0, 0.0002)]
        assert amounts == [166.68, 166.66, 166.66]

    def test_even_split_when_divisible(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config())
        amounts = [plan.amount for plan in strategy.build_offer_plan(600.0, 0.0002)]
        assert amounts == [200.0, 200.0, 200.0]

    def test_total_never_exceeds_balance(self, strategy_config):
        """加總超過可用餘額會被交易所直接拒單，這是最不能破的一條。

        2026-08-15 修正：這條原本只餵「漂亮的」餘額（小數點後至多兩位），
        而那種輸入**在數學上不可能違反這個性質**——floor 與 round 的結果一致。
        真實的 Bitfinex 餘額有 8 位小數，首次實單就因此被拒單。
        **斷言一直是對的，是輸入挑得太乾淨。**
        """
        strategy = FrrPlusStrategy(strategy_config())
        balances = (
            150.0, 344.12, 500.0, 777.77, 1000.01, 12345.67,      # 原本的「漂亮」值
            160.00861413,       # 首次實單的真實餘額
            344.30861413, 461.23456789, 150.005, 999.999, 150.00999999,
        )
        for balance in balances:
            plans = strategy.build_offer_plan(balance, 0.0002)
            total = round(sum(plan.amount for plan in plans), 2)
            assert total <= balance, f"餘額 {balance} 拆出的總額 {total} 超出可用餘額"

    def test_regression_first_live_offer_was_rejected(self, strategy_config):
        """2026-08-15 首次實單的迴歸測試。

        餘額 160.00861413，程式卻掛出 160.01，Bitfinex 以
        `Invalid offer: not enough USD balance available in deposit wallet`
        拒絕整筆。根因是餘數用 `round()` 把 0.0086 進位成 0.01，
        抵銷掉前一行刻意做的 floor。
        """
        strategy = FrrPlusStrategy(strategy_config(min_required_usd=150, min_loan_size_usd=150))
        plans = strategy.build_offer_plan(160.00861413, 0.00032288767123287674)
        assert len(plans) == 1
        assert plans[0].amount == 160.00
        assert plans[0].amount <= 160.00861413

    def test_amounts_are_rounded_to_cents(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config())
        for plan in strategy.build_offer_plan(777.77, 0.0002):
            assert plan.amount == round(plan.amount, 2)

    def test_remainder_goes_to_the_cheapest_offer(self, strategy_config):
        """餘數併進利率最低的第一筆——那筆最容易成交，資金閒置的機會最小。"""
        strategy = FrrPlusStrategy(strategy_config())
        plans = strategy.build_offer_plan(500.0, 0.0002)
        assert plans[0].amount > plans[1].amount
        assert plans[0].rate < plans[1].rate


class TestDuration:
    """天期判斷：每一筆各自依自己的利率決定，不是整組共用。"""

    def test_low_rate_uses_short_duration(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config(spread_count=1, long_duration_threshold=0.00082))
        assert strategy.build_offer_plan(200.0, 0.0002)[0].duration == 2

    def test_rate_at_threshold_uses_long_duration(self, strategy_config):
        # 邊界值：判斷式是 `>=`，剛好等於閾值要走長天期
        strategy = FrrPlusStrategy(
            strategy_config(spread_count=1, premium_rate=0.0, long_duration_threshold=0.00082)
        )
        assert strategy.build_offer_plan(200.0, 0.00082)[0].duration == 30

    def test_each_offer_decides_its_own_duration(self, strategy_config):
        """同一組掛單裡，低階維持短天期、高階鎖長天期。"""
        strategy = FrrPlusStrategy(strategy_config(long_duration_threshold=0.0005))
        plans = strategy.build_offer_plan(600.0, 0.0002)
        # 利率 0.0004 / 0.00046 / 0.000529，只有最後一筆越過 0.0005
        assert [plan.duration for plan in plans] == [2, 2, 30]


class TestLendLimit:
    """maxtolend / maxpercenttolend 風控上限（單輪量控版）。"""

    def test_no_limit_by_default(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config())
        total = sum(plan.amount for plan in strategy.build_offer_plan(1000.0, 0.0002))
        assert total == pytest.approx(1000.0)

    def test_absolute_limit_caps_total(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config(max_to_lend_usd=300))
        total = sum(plan.amount for plan in strategy.build_offer_plan(1000.0, 0.0002))
        assert total == pytest.approx(300.0)

    def test_percent_limit_caps_total(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config(max_percent_to_lend=20))
        total = sum(plan.amount for plan in strategy.build_offer_plan(1000.0, 0.0002))
        assert total == pytest.approx(200.0)

    def test_both_limits_take_the_smaller(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config(max_to_lend_usd=300, max_percent_to_lend=20))
        total = sum(plan.amount for plan in strategy.build_offer_plan(1000.0, 0.0002))
        assert total == pytest.approx(200.0)

    def test_limit_never_exceeds_actual_balance(self, strategy_config):
        """上限設得比餘額高時，仍以實際餘額為準。"""
        strategy = FrrPlusStrategy(strategy_config(max_to_lend_usd=99999))
        total = sum(plan.amount for plan in strategy.build_offer_plan(500.0, 0.0002))
        assert total == pytest.approx(500.0)

    def test_limit_below_min_loan_size_blocks_lending(self, strategy_config):
        """上限縮到連一筆最小單量都不夠，就整輪不掛。"""
        strategy = FrrPlusStrategy(strategy_config(max_to_lend_usd=100, min_loan_size_usd=150))
        assert strategy.build_offer_plan(1000.0, 0.0002) == []

    def test_limit_reduces_offer_count(self, strategy_config):
        """上限縮量後，筆數也要跟著降階。"""
        strategy = FrrPlusStrategy(
            strategy_config(max_to_lend_usd=300, min_loan_size_usd=150, spread_count=3)
        )
        assert len(strategy.build_offer_plan(1000.0, 0.0002)) == 2


class TestOfferPlanShape:
    """回傳結構本身：主迴圈與資料層都直接吃這些欄位。"""

    def test_returns_offer_plan_objects_with_usd(self, strategy_config):
        strategy = FrrPlusStrategy(strategy_config())
        for plan in strategy.build_offer_plan(600.0, 0.0002):
            assert isinstance(plan, OfferPlan)
            assert plan.currency == "USD"
            assert plan.amount > 0
            assert plan.rate > 0
            assert plan.duration > 0

    def test_defaults_apply_when_strategy_section_missing(self):
        """設定檔沒有 strategy 區段時要能用內建預設值跑起來，而不是炸掉。"""
        strategy = FrrPlusStrategy({})
        assert strategy.min_required_usd == 150
        assert strategy.spread_count == 3
        assert strategy.build_offer_plan(600.0, 0.0002)
