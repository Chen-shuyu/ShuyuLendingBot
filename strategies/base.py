# -*- coding: utf-8 -*-
"""策略層的抽象基底與共用資料結構。

策略層刻意保持「純函式」性質：輸入餘額與市場利率，輸出掛單計畫，
不碰網路、不碰資料庫、不看時間。所有需要副作用的事都由
`core/bot_engine.py` 負責，策略因此可以完全離線測試。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class OfferPlan:
    """一筆掛單計畫：策略層與迴圈層之間的契約。

    這是計畫值，不是成交值——落帳時要以交易所實際回報的金額與利率為準
    （部分成交時兩者會不同，見 `db/repository.py`）。
    """

    currency: str
    amount: float
    rate: float
    duration: int


class Strategy(ABC):
    """放貸策略介面。"""

    @abstractmethod
    def build_offer_plan(self, balance_usd: float, frr: float) -> List[OfferPlan]:
        """依目前可用餘額與 FRR 產生掛單計畫。

        回傳空清單代表「本輪不掛單」（例如餘額低於門檻），迴圈層會據此
        略過本輪而不視為失敗。
        """
