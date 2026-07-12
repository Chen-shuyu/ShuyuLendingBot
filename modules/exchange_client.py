# -*- coding: utf-8 -*-
"""與 Bitfinex 交易所互動的封裝模組。

這個版本先提供最小可用的功能，包含初始化連線、檢查權限、
讀取餘額、讀取 FRR，以及建立放貸掛單。後續會再擴充成更完整的流程。
"""

from typing import Any, Dict, List, Optional

try:
    import ccxt
except ModuleNotFoundError:  # pragma: no cover - environment fallback
    ccxt = None


class BitfinexClient:
    """最小可用的交易所封裝，供第一版流程使用。"""

    def __init__(self, config, logger, dry_run: bool = False):
        """初始化交易所客戶端。"""
        self.config = config.get("bitfinex", {})
        self.logger = logger
        self.dry_run = dry_run
        self.exchange = None

        if not self.dry_run:
            api_key = self.config.get("api_key")
            api_secret = self.config.get("api_secret")
            if api_key and api_secret:
                try:
                    if ccxt is None:
                        raise RuntimeError("ccxt 尚未安裝，請先完成套件安裝。")

                    self.exchange = ccxt.bitfinex2(
                        {
                            "apiKey": api_key,
                            "secret": api_secret,
                            "enableRateLimit": True,
                            "timeout": 10000,
                        }
                    )
                except Exception as exc:
                    self.logger.warning(f"交易所初始化失敗：{exc}")

    def test_connection(self) -> bool:
        """檢查交易所連線是否可用。"""
        if self.dry_run:
            self.logger.info("目前為 dry-run 模式，略過實際交易所連線檢查。")
            return True

        if self.exchange is None:
            self.logger.error("交易所客戶端尚未初始化，請確認 API 金鑰與設定。")
            return False

        try:
            self.exchange.fetch_balance()
            self.logger.info("已成功連線至 Bitfinex。")
            return True
        except Exception as exc:
            self.logger.error(f"連線失敗：{exc}")
            return False

    def get_available_balance(self, currency: str) -> float:
        """取得指定貨幣的可用餘額。"""
        if self.dry_run:
            return float(self.config.get("dry_run_balance_usd", 344.12))

        if self.exchange is None:
            raise RuntimeError("交易所客戶端尚未初始化，無法查詢餘額。")

        balance = self.exchange.fetch_balance()
        funding_wallet = balance.get("info", {}).get("funding", [])
        for entry in funding_wallet:
            if entry.get("currency") == currency:
                return float(entry.get("amount", 0.0))
        return 0.0

    def get_frr(self, currency: str) -> float:
        """取得指定貨幣的 FRR。"""
        if self.dry_run:
            return float(self.config.get("dry_run_frr", 0.0002))

        if self.exchange is None:
            raise RuntimeError("交易所客戶端尚未初始化，無法查詢 FRR。")

        try:
            if hasattr(self.exchange, "fetch_funding_rate"):
                rate = self.exchange.fetch_funding_rate(currency)
                return float(rate.get("rate", 0.0))
            return 0.0
        except Exception as exc:
            self.logger.warning(f"無法取得 {currency} 的 FRR：{exc}")
            return 0.0

    def cancel_active_offers(self, currency: Optional[str] = None) -> List[Dict[str, Any]]:
        """取消目前的掛單。"""
        if self.dry_run:
            self.logger.info("目前為 dry-run 模式，未實際取消任何掛單。")
            return []

        if self.exchange is None:
            raise RuntimeError("交易所客戶端尚未初始化，無法取消掛單。")

        try:
            if hasattr(self.exchange, "fetch_open_orders"):
                return self.exchange.fetch_open_orders(currency)
            return []
        except Exception as exc:
            self.logger.error(f"取消掛單失敗：{exc}")
            return []

    def create_loan_offer(self, currency: str, amount: float, rate: float, duration: int) -> Dict[str, Any]:
        """建立放貸掛單。"""
        if self.dry_run:
            return {
                "status": "dry_run",
                "currency": currency,
                "amount": amount,
                "rate": rate,
                "duration": duration,
            }

        if self.exchange is None:
            raise RuntimeError("交易所客戶端尚未初始化，無法建立掛單。")

        try:
            if hasattr(self.exchange, "create_funding_offer"):
                return self.exchange.create_funding_offer(currency, amount, rate, duration)
            if hasattr(self.exchange, "createFundingOffer"):
                return self.exchange.createFundingOffer(symbol=currency, amount=amount, rate=rate, period=duration)
            raise NotImplementedError("目前的 ccxt 版本沒有提供此交易所所需的 funding-offer 方法。")
        except Exception as exc:
            self.logger.error(f"建立放貸掛單失敗：{exc}")
            raise
