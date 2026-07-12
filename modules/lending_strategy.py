# -*- coding: utf-8 -*-
"""放貸策略邏輯。

這個模組負責將市場資訊與餘額轉換為一組掛單計畫，
目前先實作簡單的門檻判斷與拆單邏輯，後續可再擴充為更複雜的策略。
"""

from dataclasses import dataclass
from typing import List


@dataclass
class OfferPlan:
    currency: str
    amount: float
    rate: float
    duration: int


class LendingStrategy:
    """依照 PRD 初版策略，產生掛單計畫。"""

    def __init__(self, config):
        strategy_config = config.get("strategy", {})
        self.min_required_usd = strategy_config.get("min_required_usd", 150)
        self.split_threshold_usd = strategy_config.get("split_threshold_usd", 300)
        self.short_duration = strategy_config.get("short_duration", 2)
        self.long_duration = strategy_config.get("long_duration", 30)
        self.premium_rate = strategy_config.get("premium_rate", 0.0002)
        self.minimum_rate = strategy_config.get("minimum_rate", 0.0001)
        self.long_duration_threshold = strategy_config.get("long_duration_threshold", 0.00082)

    def build_offer_plan(self, balance_usd: float, frr: float) -> List[OfferPlan]:
        """依據目前餘額與 FRR，產生一組掛單方案。"""
        if balance_usd < self.min_required_usd:
            return []

        target_rate = max(frr + self.premium_rate, self.minimum_rate)
        duration = self.short_duration
        if target_rate >= self.long_duration_threshold:
            duration = self.long_duration

        if balance_usd >= self.split_threshold_usd:
            amount = round(balance_usd / 2, 2)
            return [
                OfferPlan(currency="USD", amount=amount, rate=target_rate, duration=duration),
                OfferPlan(currency="USD", amount=amount, rate=target_rate, duration=duration),
            ]

        return [OfferPlan(currency="USD", amount=round(balance_usd, 2), rate=target_rate, duration=duration)]
