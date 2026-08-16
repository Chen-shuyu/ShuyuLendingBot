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

    def _public_exchange(self):
        """回傳可用於**公開端點**的 ccxt 實例。

        行情是公開資料，不需要簽章、也沒有下單風險，所以 dry-run 或沒設定金鑰時
        照樣建得起來——這讓 dry-run 能用真實的市場深度驗證定價，而不是拿假資料
        空跑。餘額與掛單那些私有端點仍然受 `self.exchange is None` 擋著，
        dry-run 不會因為這個實例而動到真錢。
        """
        if self.exchange is not None:
            return self.exchange
        if getattr(self, "_public_client", None) is None:
            if ccxt is None:
                raise FatalError("ccxt 尚未安裝，無法查詢市場行情。")
            self._public_client = ccxt.bitfinex({"enableRateLimit": True, "timeout": 10000})
        return self._public_client

    # 純讀取且冪等，可安全重試。
    @with_retry()
    def get_funding_book(self, currency: str) -> List[Dict[str, Any]]:
        """取得放貸市場供給側掛單簿（由低利率往高排序）。

        **為什麼要抓 250 檔**：`len` 預設只給 25 檔，那只涵蓋簿子最前面約 3 萬 USD，
        算不出「我們排在多少錢後面」——而排隊位置正是這個策略唯一在意的東西
        （見 DECISIONS.md D030）。250 檔對應約 500 萬 USD，足以蓋過整個供給側。

        回傳的 `amount` 一律為正。Bitfinex 用正負號區分方向：**負數是借款需求側**，
        對放貸方來說那是買家不是競爭者，混進來會把排隊金額算大好幾倍。
        """
        exchange = self._public_exchange()
        symbol = f"f{currency}"
        try:
            # /v2/book/{symbol}/{precision}。P0 是精度最高的聚合層級。
            rows = exchange.public_get_book_symbol_precision(
                {"symbol": symbol, "precision": "P0", "len": 250}
            )
        except (ccxt.RateLimitExceeded, ccxt.NetworkError) as exc:
            raise RetryableError(f"查詢 {symbol} 掛單簿逾時或超過速率限制：{exc}") from exc
        except ccxt.ExchangeError as exc:
            raise RetryableError(f"查詢 {symbol} 掛單簿時交易所回傳錯誤：{exc}") from exc

        levels: List[Dict[str, Any]] = []
        try:
            for row in rows:
                # [0]=RATE, [1]=PERIOD, [2]=COUNT, [3]=AMOUNT；**每個欄位都是字串**
                # （實測 `'0.0002808219178082192'`），所以一律自己轉型（D027）。
                amount = float(row[3])
                if amount <= 0:
                    continue
                levels.append(
                    {"rate": float(row[0]), "period": int(row[1]), "amount": amount}
                )
        except (IndexError, ValueError, TypeError) as exc:
            raise RetryableError(f"無法解析 {symbol} 掛單簿回應：{exc}") from exc

        levels.sort(key=lambda level: level["rate"])
        return levels

    @with_retry()
    def get_active_offers(self, currency: Optional[str] = None) -> List[Dict[str, Any]]:
        """查詢場上未成交的放貸掛單（唯讀，不取消任何東西）。"""
        if self.dry_run:
            return []

        if self.exchange is None:
            raise FatalError("交易所客戶端尚未初始化，無法查詢掛單。")

        symbol = f"f{currency}" if currency else "fUSD"
        return self._parse_offers(self._fetch_raw_offers(symbol))

    def _fetch_raw_offers(self, symbol: str):
        """打 funding offers 端點並統一例外分類（查詢與取消兩條路徑共用）。"""
        try:
            offers = self.exchange.private_post_auth_r_funding_offers_symbol({"symbol": symbol})
        except (ccxt.RateLimitExceeded, ccxt.NetworkError) as exc:
            raise RetryableError(f"查詢未成交放貸掛單逾時或超過速率限制：{exc}") from exc
        except ccxt.AuthenticationError as exc:
            raise FatalError(f"查詢未成交放貸掛單認證失敗：{exc}") from exc
        except ccxt.ExchangeError as exc:
            raise FatalError(f"查詢未成交放貸掛單時交易所回傳錯誤：{exc}") from exc
        return offers

    @staticmethod
    def _parse_offers(offers) -> List[Dict[str, Any]]:
        """把 funding offer 陣列轉成統一的 dict。

        欄位索引以 2026-08-16 對正式帳號實打的回應核對過（21 欄，全部是字串）：
        0=ID, 1=SYMBOL, 4=AMOUNT(剩餘), 5=AMOUNT_ORIG, 10=STATUS, 14=RATE, 15=PERIOD。
        """
        parsed: List[Dict[str, Any]] = []
        for offer in offers:
            parsed.append(
                {
                    # **id 一定要轉成整數**：取消端點只收整數，收到字串會回 `id: invalid`
                    # （2026-08-15 實單踩過，見 DECISIONS.md D026）。
                    "id": int(offer[0]),
                    "symbol": offer[1],
                    "amount": float(offer[4]),
                    "rate": float(offer[14]),
                    "period": int(offer[15]),
                }
            )
        return parsed

    @with_retry()
    def get_active_positions(self, currency: str) -> List[Dict[str, Any]]:
        """查詢已經借出去的部位（credits ＋ loans 合併）。

        **為什麼要查兩個端點**：Bitfinex 把已成交的放貸拆成 credits（借款人已拿去
        用在持倉上）與 loans（已被借走但還沒用掉）。對放貸方來說兩者都是
        「錢已經出去、正在生息」，只查其中一個會漏掉另一半。

        **欄位索引取自官方文件，尚未經真實回應核對**——本專案至今一筆都沒成交過，
        探測時兩個端點都是空清單。所以解析刻意寫成防禦式：長度不足就跳過該筆並把
        原始內容寫進日誌，讓第一筆真實成交自己把結構告訴我們（D027 的做法）。
        拿到真實回應後要回來把這段註解改成「已核對」。
        """
        if self.dry_run:
            return []

        if self.exchange is None:
            raise FatalError("交易所客戶端尚未初始化，無法查詢已借出部位。")

        symbol = f"f{currency}"
        positions: List[Dict[str, Any]] = []
        for kind, method in (
            ("credit", "private_post_auth_r_funding_credits_symbol"),
            ("loan", "private_post_auth_r_funding_loans_symbol"),
        ):
            try:
                rows = getattr(self.exchange, method)({"symbol": symbol})
            except (ccxt.RateLimitExceeded, ccxt.NetworkError) as exc:
                raise RetryableError(f"查詢已借出部位（{kind}）逾時或超過速率限制：{exc}") from exc
            except ccxt.AuthenticationError as exc:
                raise FatalError(f"查詢已借出部位（{kind}）認證失敗：{exc}") from exc
            except ccxt.ExchangeError as exc:
                raise FatalError(f"查詢已借出部位（{kind}）時交易所回傳錯誤：{exc}") from exc

            positions.extend(self._parse_positions(rows, kind))
        return positions

    def _parse_positions(self, rows, kind: str) -> List[Dict[str, Any]]:
        """解析 funding credits／loans 陣列。

        欄位（官方文件）：0=ID, 1=SYMBOL, 5=AMOUNT, 7=STATUS, 11=RATE, 12=PERIOD,
        13=MTS_OPENING。credits 比 loans 多一個 21=POSITION_PAIR，前 14 欄一致，
        所以兩者共用這支解析。
        """
        parsed: List[Dict[str, Any]] = []
        for row in rows:
            try:
                if len(row) <= 13:
                    raise IndexError(f"欄位數只有 {len(row)}，少於預期的 14")
                parsed.append(
                    {
                        "id": str(row[0]),
                        "symbol": row[1],
                        "amount": abs(float(row[5])),
                        "rate": float(row[11]),
                        "period": int(row[12]),
                        "opened_at": int(row[13]) if row[13] is not None else None,
                        "kind": kind,
                    }
                )
            except (IndexError, ValueError, TypeError) as exc:
                # 不讓一筆解析不了的資料害整輪失敗——但一定要留下原始內容，
                # 否則就是「成交了卻沒人知道」的翻版，只是換個地方發生。
                self.logger.error(
                    f"無法解析已借出部位（{kind}）：{exc}；原始回應：{row!r}"
                )
        return parsed

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
        # 目前釘選的 ccxt 版本（合併版 bitfinex）沒有提供統一的
        # fetch_funding_offers / cancel_funding_offer，只能直接呼叫
        # Bitfinex V2 底層 implicit API（與 get_frr() 呼叫 public_get_ticker_symbol
        # 是同一種做法）。查詢與解析和 `get_active_offers()` 共用同一份實作——
        # 欄位索引只寫在一個地方，才不會有一邊改了另一邊沒改。
        offers = self._parse_offers(self._fetch_raw_offers(symbol))

        cancelled: List[Dict[str, Any]] = []
        for offer_info in offers:
            offer_id = offer_info["id"]
            try:
                self.exchange.private_post_auth_w_funding_offer_cancel({"id": offer_id})
            except (ccxt.RateLimitExceeded, ccxt.NetworkError) as exc:
                raise RetryableError(f"取消掛單 {offer_id} 逾時或超過速率限制：{exc}") from exc
            except ccxt.ExchangeError as exc:
                self.logger.error(f"取消掛單 {offer_id} 失敗：{exc}")
                continue
            cancelled.append(offer_info)

        # 查到掛單卻一筆都取消不掉 = 「每輪全取消重掛」整個策略失效，必須讓它變成
        # 看得見的失敗。原本這裡只記 ERROR 就往下走，於是本輪仍算成功：
        # 連續失敗計數不動、不會告警、心跳照常、健康檢查照樣綠燈——
        # **機器人看起來一切正常，實際上已經停止更新掛單利率**（2026-08-15 實單踩到，
        # 連續兩輪沒有人發現，見 DECISIONS.md D026）。
        # 用 RetryableError 而不是 FatalError：多半是暫時性的，下一輪重試合理，
        # 連續達門檻時 FailureTracker 會送出告警。
        if offers and not cancelled:
            raise RetryableError(
                f"查到 {len(offers)} 筆未成交掛單，但一筆都取消不掉，本輪不掛新單"
            )

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
