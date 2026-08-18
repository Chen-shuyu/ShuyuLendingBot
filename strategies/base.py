# -*- coding: utf-8 -*-
"""策略層的抽象基底與共用資料結構。

策略層刻意保持「純函式」性質：輸入餘額與市場利率，輸出掛單計畫，
不碰網路、不碰資料庫、不看時間。所有需要副作用的事都由
`core/bot_engine.py` 負責，策略因此可以完全離線測試。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


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

    # 這個策略需不需要市場深度（訂單簿）。迴圈層據此決定要不要多打一次公開端點：
    # 用不到卻照打，等於白白多一個會失敗的地方。
    requires_book = False

    # 這個策略需不需要近期成交紀錄。同上，用不到就不打。
    requires_trades = False

    # 這個策略需不需要利率 K 線。同上，用不到就不打。
    requires_candles = False

    # 最近一次回傳空計畫的原因（沒有就是 None）。迴圈層拿它寫日誌與落帳。
    #
    # **為什麼這是介面的一部分，而不是某個策略的私事**：`build_offer_plan()` 回傳
    # 空清單有很多種原因——沒錢、資料不足、價格太低——而迴圈層看到的都是同一個
    # `[]`。舊版因此寫死一句「可放貸金額不足」，在多數出口都是錯的；最糟的情況是
    # 帳上有 344 USD 卻寫「可放貸金額不足（目前 344.3 USD）」，自相矛盾又把人
    # 指向錯的方向（TASKS.md A1）。
    #
    # **策略層仍然不碰 IO**：這裡只是把已經知道的事實留下來，不主動輸出。
    last_skip_reason: Optional[str] = None

    def _skip(self, reason: str) -> List["OfferPlan"]:
        """本輪不掛單，並把原因留給迴圈層。"""
        self.last_skip_reason = reason
        return []

    @abstractmethod
    def build_offer_plan(
        self,
        balance_usd: float,
        frr: float,
        book: Optional[List[Dict[str, Any]]] = None,
        trades: Optional[List[Dict[str, Any]]] = None,
        candles: Optional[List[Dict[str, Any]]] = None,
    ) -> List[OfferPlan]:
        """依目前可用餘額與市場資訊產生掛單計畫。

        `book` 是供給側掛單簿（見 `api/base.py` 的 `get_funding_book()`），只有
        `requires_book = True` 的策略會拿到；`trades` 是近期成交紀錄
        （`get_recent_trades()`），只有 `requires_trades = True` 的策略會拿到；
        `candles` 是利率 K 線（`get_rate_candles()`），只有 `requires_candles = True`
        的策略會拿到。其餘策略可以忽略它們。

        **三份資料回答的是不同問題**：掛單簿講「別人開價多少、我排第幾位」，
        成交紀錄講「借款人現在實際付了多少」，K 線講「過去每段時間需求掃到多高」。
        只看第一份會被一筆低價大單牽著走（D033）；只看前兩份會把一個時間切片
        誤當成市場的常態，而這個市場在每小時之內的振幅動輒 5 個百分點（D035）。

        回傳空清單代表「本輪不掛單」（例如餘額低於門檻、或市場價格低於底線），
        迴圈層會據此略過本輪而不視為失敗。
        """
