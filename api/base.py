# -*- coding: utf-8 -*-
"""交易所適配層的抽象介面。

核心迴圈（`core/bot_engine.py`）只透過這個介面跟交易所打交道，換交易所時
只要再實作一份，迴圈與策略層都不必動。

介面的重點其實不在方法簽章，而在**例外契約**：實作必須把底層套件的例外
（ccxt 的 `NetworkError`、`AuthenticationError`…）轉換成專案自己的
`RetryableError` / `FatalError` 再往外拋，因為主迴圈是靠這個分類決定
「下一輪重試」還是「直接停止」的。讓 ccxt 的例外漏到迴圈層，會被最外層的
`except Exception` 當成未預期例外，離開碼與重啟決策就全錯了。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ExchangeClient(ABC):
    """放貸機器人需要的交易所能力。"""

    @abstractmethod
    def test_connection(self) -> bool:
        """啟動檢查：連線與金鑰是否可用。失敗回傳 False，不拋例外。"""

    @abstractmethod
    def get_available_balance(self, currency: str) -> float:
        """取得 funding 錢包（放貸專用）的可用餘額。"""

    @abstractmethod
    def get_frr(self, currency: str) -> float:
        """取得放貸市場的 FRR（Flash Return Rate，日利率）。"""

    @abstractmethod
    def get_funding_book(self, currency: str) -> List[Dict[str, Any]]:
        """取得放貸市場的**供給側**掛單簿，由低利率往高排序。

        每一檔是 `{"rate": float, "period": int, "amount": float}`，金額一律為正數
        （借款需求側在來源資料裡是負的，實作要負責濾掉）。回傳空清單代表
        「這次拿不到市場深度」，策略層據此決定跳過本輪，而不是拿舊資料硬掛。

        用 dict 而不是共用的 dataclass，是為了不讓策略層與交易所層互相 import
        ——兩邊各自只依賴這份欄位約定（與 `cancel_active_offers()` 的慣例一致）。
        """

    @abstractmethod
    def get_recent_trades(self, currency: str, limit: int = 10_000) -> List[Dict[str, Any]]:
        """取得放貸市場的近期成交紀錄，依時間**升冪**排序。

        每一筆是 `{"mts": int, "amount": float, "rate": float, "period": int}`，
        `amount` 一律為正（來源資料的正負號表示吃單方向，與成交價無關）。

        掛單簿講的是「有人開價多少」，這一份講的是「借款人實際付了多少」——
        兩者可以差一倍以上，而只有後者能證明某個價位真的賣得掉（見 D033）。
        """

    @abstractmethod
    def get_active_offers(self, currency: Optional[str] = None) -> List[Dict[str, Any]]:
        """查詢場上尚未成交的放貸掛單，**不做任何取消動作**。

        與 `cancel_active_offers()` 查的是同一份資料，但職責分開：主迴圈要先看過
        場上現況才能決定「這一輪到底該不該重掛」。合在一起的話，光是想知道
        「現在掛的是什麼」就得先把單子取消掉，而取消本身就是我們要避免的動作。
        """

    @abstractmethod
    def get_active_positions(self, currency: str) -> List[Dict[str, Any]]:
        """查詢**已經借出去**的部位（成交後的資金），供成交偵測與總曝險計算使用。

        Bitfinex 把它拆成兩個端點：credits（借款人已用於持倉）與 loans（借出但尚未
        被使用）。對放貸方而言兩者都是「錢已經出去、正在生息」，所以這裡合併回傳，
        每一筆是 `{"id": str, "amount": float, "rate": float, "period": int,
        "opened_at": int|None, "kind": "credit"|"loan"}`。
        """

    @abstractmethod
    def cancel_active_offers(self, currency: Optional[str] = None) -> List[Dict[str, Any]]:
        """取消尚未成交的放貸掛單，回傳被取消的掛單資訊清單。"""

    @abstractmethod
    def create_loan_offer(self, currency: str, amount: float, rate: float, duration: int) -> Dict[str, Any]:
        """建立一筆放貸掛單，回傳交易所回報的成交條件。

        **不是冪等操作**：實作不得自行重試（見 DECISIONS.md D013）。
        """
