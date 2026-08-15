# -*- coding: utf-8 -*-
"""與 Bitfinex 交易所互動的封裝模組（`api/base.py` 介面的 Bitfinex 實作）。

這個版本先提供最小可用的功能，包含初始化連線、檢查權限、
讀取餘額、讀取 FRR，以及建立放貸掛單。後續會再擴充成更完整的流程。

Bitfinex funding 相關操作一律走 ccxt 的 raw/implicit API，統一方法在 ccxt 的
bitfinex 實作裡從未存在過（見 DECISIONS.md D010）。
"""

from typing import Any, Dict, List, Optional

from api.base import ExchangeClient
from api.rate_limiter import RetrySettings, with_retry
from utils.exceptions import FatalError, RetryableError

try:
    import ccxt
except ModuleNotFoundError:  # pragma: no cover - environment fallback
    ccxt = None


class BitfinexClient(ExchangeClient):
    """最小可用的交易所封裝，供第一版流程使用。"""

    def __init__(self, config, logger, dry_run: bool = False):
        """初始化交易所客戶端。"""
        self.config = config.get("bitfinex", {})
        self.logger = logger
        self.dry_run = dry_run
        self.exchange = None
        # 供 @with_retry 讀取；必須用完整 config，因為 retry 區段不在 bitfinex 底下
        self.retry_settings = RetrySettings.from_config(config)

        if not self.dry_run:
            api_key = self.config.get("api_key")
            api_secret = self.config.get("api_secret")
            if api_key and api_secret:
                try:
                    if ccxt is None:
                        raise RuntimeError("ccxt 尚未安裝，請先完成套件安裝。")

                    # 注意：新版 ccxt（4.x）已將 V1/V2 合併為單一 `bitfinex`，
                    # 不再有獨立的 `bitfinex2`，這裡底層走的就是 V2 API。
                    self.exchange = ccxt.bitfinex(
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
            # 明確指定 type='funding'，與 get_available_balance() 查的是同一個錢包，
            # 語意一致，也能在啟動階段順便驗證 funding 錢包權限是否正常開通。
            self.exchange.fetch_balance({"type": "funding"})
            self.logger.info("已成功連線至 Bitfinex。")
            return True
        except Exception as exc:
            self.logger.error(f"連線失敗：{exc}")
            return False

    @with_retry()
    def get_available_balance(self, currency: str) -> float:
        """取得指定貨幣在 funding 錢包（放貸專用）的可用餘額。"""
        if self.dry_run:
            return float(self.config.get("dry_run_balance_usd", 344.12))

        if self.exchange is None:
            raise FatalError("交易所客戶端尚未初始化，無法查詢餘額。")

        try:
            # 必須明確指定 type='funding'，否則 ccxt 預設查的是 exchange（交易）錢包，
            # 不是放貸用的 funding 錢包。
            balance = self.exchange.fetch_balance({"type": "funding"})
        except (ccxt.RateLimitExceeded, ccxt.NetworkError) as exc:
            raise RetryableError(f"查詢 {currency} 餘額逾時或超過速率限制：{exc}") from exc
        except ccxt.AuthenticationError as exc:
            raise FatalError(f"查詢 {currency} 餘額認證失敗：{exc}") from exc
        except ccxt.ExchangeError as exc:
            raise FatalError(f"查詢 {currency} 餘額時交易所回傳錯誤：{exc}") from exc

        account = balance.get(currency, {})
        return float(account.get("free", 0.0) or 0.0)

    @with_retry()
    def get_frr(self, currency: str) -> float:
        """取得指定貨幣的 FRR（Flash Return Rate，放貸市場日利率）。"""
        if self.dry_run:
            return float(self.config.get("dry_run_frr", 0.0002))

        if self.exchange is None:
            raise FatalError("交易所客戶端尚未初始化，無法查詢 FRR。")

        try:
            # 直接呼叫 Bitfinex V2 公開端點 GET /v2/ticker/f{CCY}，
            # 回傳陣列 index 0 才是真正的放貸 FRR；先前誤用
            # fetch_funding_rate 讀到的是永續合約資金費率，數據錯誤。
            ticker = self.exchange.public_get_ticker_symbol({"symbol": f"f{currency}"})
            return float(ticker[0])
        except (ccxt.RateLimitExceeded, ccxt.NetworkError) as exc:
            raise RetryableError(f"查詢 {currency} FRR 逾時或超過速率限制：{exc}") from exc
        except ccxt.AuthenticationError as exc:
            raise FatalError(f"查詢 {currency} FRR 認證失敗：{exc}") from exc
        except ccxt.ExchangeError as exc:
            raise FatalError(f"查詢 {currency} FRR 時交易所回傳錯誤：{exc}") from exc
        except (IndexError, ValueError, TypeError) as exc:
            raise RetryableError(f"無法解析 {currency} 的 FRR 回應：{exc}") from exc

    # 取消是冪等操作（重試時會重新查詢，已取消的單不會再出現在清單裡），可安全重試。
    # 唯一的邊界情況：某筆取消其實已在交易所生效、只是回應逾時，重試後該筆不會被算進
    # 回傳清單，主迴圈因此可能略過「等待餘額釋放」而讀到偏舊的餘額——結果只是本輪少掛
    # 一點，不會超額掛出，且下一輪即自行修正。
    @with_retry()
    def cancel_active_offers(self, currency: Optional[str] = None) -> List[Dict[str, Any]]:
        """取消目前尚未成交的放貸掛單（active funding offers），不影響已成交的 active loan。"""
        if self.dry_run:
            self.logger.info("目前為 dry-run 模式，未實際取消任何掛單。")
            return []

        if self.exchange is None:
            raise FatalError("交易所客戶端尚未初始化，無法取消掛單。")

        symbol = f"f{currency}" if currency else "fUSD"
        try:
            # 目前釘選的 ccxt 版本（合併版 bitfinex）沒有提供統一的
            # fetch_funding_offers / cancel_funding_offer，只能直接呼叫
            # Bitfinex V2 底層 implicit API（與 get_frr() 呼叫 public_get_ticker_symbol
            # 是同一種做法）。
            offers = self.exchange.private_post_auth_r_funding_offers_symbol({"symbol": symbol})
        except (ccxt.RateLimitExceeded, ccxt.NetworkError) as exc:
            raise RetryableError(f"查詢未成交放貸掛單逾時或超過速率限制：{exc}") from exc
        except ccxt.AuthenticationError as exc:
            raise FatalError(f"查詢未成交放貸掛單認證失敗：{exc}") from exc
        except ccxt.ExchangeError as exc:
            raise FatalError(f"查詢未成交放貸掛單時交易所回傳錯誤：{exc}") from exc

        cancelled: List[Dict[str, Any]] = []
        for offer in offers:
            # Bitfinex V2 funding offer 陣列欄位：0=ID, 1=SYMBOL, 4=AMOUNT, 14=RATE, 15=PERIOD
            # https://docs.bitfinex.com/reference/rest-auth-funding-offers
            offer_id = offer[0]
            offer_info = {
                "id": offer_id,
                "symbol": offer[1],
                "amount": float(offer[4]),
                "rate": float(offer[14]),
                "period": int(offer[15]),
            }
            try:
                self.exchange.private_post_auth_w_funding_offer_cancel({"id": offer_id})
            except (ccxt.RateLimitExceeded, ccxt.NetworkError) as exc:
                raise RetryableError(f"取消掛單 {offer_id} 逾時或超過速率限制：{exc}") from exc
            except ccxt.ExchangeError as exc:
                self.logger.error(f"取消掛單 {offer_id} 失敗：{exc}")
                continue
            cancelled.append(offer_info)

        self.logger.info(f"已取消 {len(cancelled)} 筆未成交放貸掛單。")
        return cancelled

    # 這裡刻意「不」套用 @with_retry：掛單不是冪等操作。若請求其實已送達 Bitfinex、
    # 只是回應逾時，重試就會重複掛單，實盤下是真的多借出去。失敗時直接把
    # RetryableError 交給主迴圈，下一輪的「全取消重掛」會自然補回這筆額度。
    # 見 DECISIONS.md D013。
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
            raise FatalError("交易所客戶端尚未初始化，無法建立掛單。")

        symbol = f"f{currency}"
        try:
            # create_funding_offer / createFundingOffer 這兩個統一方法在 ccxt 對
            # bitfinex 的實作裡從未存在過（見 .project-docs/CCXT_BITFINEX_API_INVESTIGATION.md、
            # DECISIONS.md D010），改直接呼叫官方 REST 端點對應的 raw API；
            # type 固定用 LIMIT（固定利率掛單），對應策略層算好的絕對利率數值。
            response = self.exchange.private_post_auth_w_funding_offer_submit(
                {
                    "type": "LIMIT",
                    "symbol": symbol,
                    "amount": str(amount),
                    "rate": str(rate),
                    "period": int(duration),
                }
            )
        except (ccxt.RateLimitExceeded, ccxt.NetworkError) as exc:
            self.logger.warning(f"建立放貸掛單逾時或超過速率限制：{exc}")
            raise RetryableError(str(exc)) from exc
        except ccxt.AuthenticationError as exc:
            self.logger.error(f"建立放貸掛單認證失敗：{exc}")
            raise FatalError(str(exc)) from exc
        except ccxt.ExchangeError as exc:
            self.logger.error(f"建立放貸掛單時交易所回傳錯誤：{exc}")
            raise FatalError(str(exc)) from exc

        # 回應為通知信封：[4]=FUNDING_OFFER_ARRAY，[6]=STATUS，[7]=TEXT
        # https://docs.bitfinex.com/reference/rest-auth-submit-funding-offer
        status = response[6] if len(response) > 6 else None
        if status != "SUCCESS":
            text = response[7] if len(response) > 7 else status
            raise FatalError(f"建立放貸掛單失敗：{text}")

        offer = response[4]
        return {
            "status": "submitted",
            "id": offer[0],
            "symbol": offer[1],
            "amount": float(offer[4]),
            "rate": float(offer[14]),
            "period": int(offer[15]),
        }
