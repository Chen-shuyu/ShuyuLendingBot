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
    def cancel_active_offers(self, currency: Optional[str] = None) -> List[Dict[str, Any]]:
        """取消尚未成交的放貸掛單，回傳被取消的掛單資訊清單。"""

    @abstractmethod
    def create_loan_offer(self, currency: str, amount: float, rate: float, duration: int) -> Dict[str, Any]:
        """建立一筆放貸掛單，回傳交易所回報的成交條件。

        **不是冪等操作**：實作不得自行重試（見 DECISIONS.md D013）。
        """
