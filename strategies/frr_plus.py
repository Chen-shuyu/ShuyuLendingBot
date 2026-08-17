# -*- coding: utf-8 -*-
"""FRR+ 放貸策略。

這個模組負責將市場資訊與餘額轉換為一組掛單計畫：先套用 maxtolend 風控上限縮減
可放貸金額，再依 spread 設定把金額拆成多筆、利率逐階遞增的掛單，最後對每一筆
單獨判斷天期（高利率鎖長天期、低利率保持靈活）。
"""

from decimal import Decimal
from typing import List

from strategies.base import OfferPlan, Strategy


class FrrPlusStrategy(Strategy):
    """FRR+ 策略：動態利率底線 + spread 階梯拆單 + xDays 動態天期 + maxtolend 風控。"""

    def __init__(self, config):
        strategy_config = config.get("strategy", {})
        self.min_required_usd = float(strategy_config.get("min_required_usd", 150))
        self.min_loan_size_usd = float(strategy_config.get("min_loan_size_usd", 150))
        self.short_duration = int(strategy_config.get("short_duration", 2))
        self.long_duration = int(strategy_config.get("long_duration", 30))
        self.premium_rate = float(strategy_config.get("premium_rate", 0.0002))
        self.minimum_rate = float(strategy_config.get("minimum_rate", 0.0001))
        self.long_duration_threshold = float(strategy_config.get("long_duration_threshold", 0.00082))
        self.spread_count = int(strategy_config.get("spread_count", 3))
        self.spread_step_pct = float(strategy_config.get("spread_step_pct", 0.15))
        self.max_to_lend_usd = float(strategy_config.get("max_to_lend_usd", 0))
        self.max_percent_to_lend = float(strategy_config.get("max_percent_to_lend", 0))

    def build_offer_plan(
        self, balance_usd: float, frr: float, book=None, trades=None, candles=None
    ) -> List[OfferPlan]:
        """依據目前餘額與 FRR，產生一組掛單方案。

        `book`、`trades` 與 `candles` 一律忽略：這個策略的定價基準是 FRR，
        不看市場深度、實際成交或 K 線（`requires_book` / `requires_trades` /
        `requires_candles` 都維持 False，迴圈層根本不會去抓）。
        """
        self.last_skip_reason = None

        if balance_usd < self.min_required_usd:
            return self._skip(
                f"可用餘額 {balance_usd:.2f} USD 低於下限 {self.min_required_usd:.2f} USD"
            )

        lendable_usd = self._apply_lend_limit(balance_usd)
        if lendable_usd < self.min_loan_size_usd:
            return self._skip(
                f"風控上限套用後只剩 {lendable_usd:.2f} USD，"
                f"低於單筆最小量 {self.min_loan_size_usd:.2f} USD"
            )

        base_rate = max(frr + self.premium_rate, self.minimum_rate)
        count = self._resolve_spread_count(lendable_usd)
        amounts = self._split_amount(lendable_usd, count)

        plans: List[OfferPlan] = []
        for index, amount in enumerate(amounts):
            rate = round(base_rate * (1 + self.spread_step_pct) ** index, 6)
            plans.append(
                OfferPlan(
                    currency="USD",
                    amount=amount,
                    rate=rate,
                    duration=self._resolve_duration(rate),
                )
            )
        return plans

    def _apply_lend_limit(self, balance_usd: float) -> float:
        """套用 maxtolend / maxpercenttolend 上限，回傳本輪實際可掛出的總金額。"""
        limits = []
        if self.max_to_lend_usd > 0:
            limits.append(self.max_to_lend_usd)
        if self.max_percent_to_lend > 0:
            limits.append(balance_usd * self.max_percent_to_lend / 100)
        if not limits:
            return balance_usd
        return min(balance_usd, min(limits))

    def _resolve_spread_count(self, lendable_usd: float) -> int:
        """決定實際能拆成幾筆：金額不足時逐階降回，確保每筆都達到交易所最小單量。"""
        count = self.spread_count
        while count > 1 and lendable_usd < count * self.min_loan_size_usd:
            count -= 1
        return count

    def _split_amount(self, lendable_usd: float, count: int) -> List[float]:
        """把總金額均分成 count 筆；除不盡的餘數併入利率最低、最容易成交的第一筆。

        **全程向下取到分位**：各筆加總必須 `<=` 可用餘額，多一分錢，交易所就會以
        `Invalid offer: not enough USD balance available in deposit wallet`
        拒絕**整筆**掛單。這在 dry-run 下永遠看不出來——沒有人驗證金額。
        """
        # 全程以「整數分」計算，理由有兩個：
        # 1. 截斷成分位就保證加總 <= 餘額。原本的寫法先 floor 每筆、再用 `round()`
        #    處理餘數，等於把 floor 抵銷掉——0.0086 被進位成 0.01，總額就超出了。
        #    2026-08-15 首次實單即因此被拒：餘額 160.00861413，卻掛出 160.01。
        # 2. 純浮點運算會少掉一分錢：`500.0 - 166.66 * 3` 實際算出的是
        #    0.019999999999953，向下取分位就變成 0.01。`Decimal(str(x))` 沒有這個問題。
        total_cents = int(Decimal(str(lendable_usd)) * 100)  # int() 截斷 = 向下取分位
        per_cents, remainder_cents = divmod(total_cents, count)
        amounts = [per_cents / 100] * count
        if remainder_cents:
            amounts[0] = (per_cents + remainder_cents) / 100
        return amounts

    def _resolve_duration(self, rate: float) -> int:
        """利率突破暴利閾值就鎖長天期，否則維持短天期保有資金靈活性。"""
        if rate >= self.long_duration_threshold:
            return self.long_duration
        return self.short_duration
