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
from utils.exceptions import FatalError, RetryableError, SkipCycleError

try:
    import ccxt
except ModuleNotFoundError:  # pragma: no cover - environment fallback
    ccxt = None


def _is_insufficient_balance(message: str) -> bool:
    """從錯誤訊息判斷這是不是「餘額不足」，而不是真正的認證問題（TASKS.md B5）。

    ccxt 把 Bitfinex 的
    `Invalid offer: not enough USD balance available in deposit wallet`
    歸類成 `AuthenticationError`（D025 首次實單就是這樣被記成「認證失敗」的）。
    **例外的型別在這裡不可信，只有訊息內容可信**，所以分類要看訊息。

    只認 `not enough` 與 `insufficient` 兩個字樣，**刻意不單獨認 `balance`**：
    「查餘額失敗」之類的訊息也含這個字，而把真正的認證問題誤判成「本輪略過」
    會讓機器人拿無效金鑰空轉一整天——**這個方向的誤判比反過來貴得多**。
    """
    lowered = (message or "").lower()
    return "not enough" in lowered or "insufficient" in lowered


def _optional_millis(value) -> Optional[int]:
    """把 Bitfinex 回傳的毫秒時間戳轉成整數，轉不動就回 `None`。

    Bitfinex 的 funding 端點把時間戳當字串回傳（`'1787087004000'`），
    而且偶爾會是 `None`。這裡吞掉轉換錯誤而不是拋例外：時間戳是輔助資訊，
    值不出來就讓上層看到 `None` 並自己說「不知道」——**比讓一輪巡檢失敗好，
    也比默默填一個 0 好**（填 0 會變成「1970 年掛的單」，然後閒置時間爆表）。
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
        （見 DECISIONS.md D030）。

        **250 檔蓋不住整個供給側**（2026-08-20 修正，TASKS.md B9）。這裡原本寫
        「250 檔對應約 500 萬 USD，足以蓋過整個供給側」，實測不成立：
        2026-08-19 當下 250 檔的供給側總額只有 1,306,715 USD、可見最高只到年化 9.04%，
        而我們掛的是 9.78%——**價位在簿子之外**。

        所以呼叫端拿到的是「利率由低往高的前 250 檔」，可見範圍內完整、之上一無所知。
        `OrderBookDepthStrategy.describe_queue()` 的 `truncated` 就是在講這件事；
        這個誤解正是 A2／A3 兩個 bug 的共同根因。

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

    # 純讀取且冪等，可安全重試。
    @with_retry()
    def get_recent_trades(self, currency: str, limit: int = 10_000) -> List[Dict[str, Any]]:
        """取得放貸市場的近期成交紀錄（公開端點，不需簽章）。

        **為什麼定價非要有這一份資料**：訂單簿只講「有人願意用什麼價錢把錢借出去」，
        它講不出「借款人實際付了多少」。兩者可以差非常多——2026-08-16 夜間的實例是
        簿子最底端出現一道 **182 萬 USD 掛在 0.00015**，而同一小時的實際成交中位數
        是 0.00029（年化 10.6%）。只看簿子的策略會一路跟著那道牆把自己的報價砍半，
        而那道牆代表的只是某一個人願意賤賣，不是市場的價格（見 DECISIONS.md D033）。

        回傳依時間**升冪**排序，每筆含 `mts`（毫秒）／`amount`（一律取正）／
        `rate`／`period`。方向不分：借款人付的價錢就是成交價，兩邊看到的是同一個數字。
        """
        exchange = self._public_exchange()
        symbol = f"f{currency}"
        try:
            # /v2/trades/{symbol}/hist
            rows = exchange.public_get_trades_symbol_hist({"symbol": symbol, "limit": limit})
        except (ccxt.RateLimitExceeded, ccxt.NetworkError) as exc:
            raise RetryableError(f"查詢 {symbol} 近期成交逾時或超過速率限制：{exc}") from exc
        except ccxt.ExchangeError as exc:
            raise RetryableError(f"查詢 {symbol} 近期成交時交易所回傳錯誤：{exc}") from exc

        trades: List[Dict[str, Any]] = []
        try:
            for row in rows:
                # [0]=ID, [1]=MTS, [2]=AMOUNT, [3]=RATE, [4]=PERIOD；**五欄全是字串**
                # ——2026-08-29 實打確認（B6）。在那之前這裡寫的是「可能是字串」，
                # 而那個「可能」是從掛單簿推的，沒有查證過。所以一律自己轉型（D027）。
                rate = float(row[3])
                if rate <= 0:
                    continue
                trades.append(
                    {
                        "mts": int(row[1]),
                        # 正負號在成交紀錄裡表示的是吃單方向，對「成交價是多少」沒有影響。
                        "amount": abs(float(row[2])),
                        "rate": rate,
                        "period": int(row[4]),
                    }
                )
        except (IndexError, ValueError, TypeError) as exc:
            raise RetryableError(f"無法解析 {symbol} 近期成交回應：{exc}") from exc

        trades.sort(key=lambda trade: trade["mts"])
        return trades

    # 純讀取且冪等，可安全重試。
    @with_retry()
    def get_rate_candles(
        self, currency: str, period: int = 2, timeframe: str = "1h", limit: int = 5_000
    ) -> List[Dict[str, Any]]:
        """取得放貸利率 K 線（公開端點，不需簽章），依時間升冪排序。

        **這份資料回答的問題是「掛在某個利率，多久會遇到一次掃到那裡的需求」**，
        而那正是排隊位置模型答不出來、也答錯了的問題（見 DECISIONS.md D035）。

        每根 K 的 `high` 是那段時間內成交過的最高利率。這個市場的成交是**陣發掃單**
        ——需求來的時候一口氣掃到 9~10%，沒來的時候簿子前端也不動。所以
        「某根 K 的 `high` ≥ 我們的掛單利率」就等於「那段時間我們會被掃到」。

        端點是 `/v2/candles/trade:{timeframe}:f{ccy}:p{period}/hist`。
        **`p{period}` 這一段不能省**：不指定天期會把所有天期混在一起，
        而 2 天期佔了 86% 的供給、價格結構與長天期不同（見 D030 的天期分析）。
        """
        exchange = self._public_exchange()
        symbol = f"f{currency}"
        try:
            rows = exchange.public_get_candles_trade_timeframe_symbol_period_section(
                {
                    "timeframe": timeframe,
                    "symbol": symbol,
                    "period": f"p{int(period)}",
                    "section": "hist",
                    "limit": limit,
                    "sort": -1,
                }
            )
        except (ccxt.RateLimitExceeded, ccxt.NetworkError) as exc:
            raise RetryableError(f"查詢 {symbol} 利率 K 線逾時或超過速率限制：{exc}") from exc
        except ccxt.ExchangeError as exc:
            raise RetryableError(f"查詢 {symbol} 利率 K 線時交易所回傳錯誤：{exc}") from exc

        candles: List[Dict[str, Any]] = []
        try:
            for row in rows:
                # [0]=MTS, [1]=OPEN, [2]=CLOSE, [3]=HIGH, [4]=LOW, [5]=VOLUME；
                # **欄位可能是字串**（掛單簿與成交紀錄實測都是），一律自己轉型（D027）。
                high = float(row[3])
                if high <= 0:
                    continue
                candles.append(
                    {
                        "mts": int(row[0]),
                        "open": float(row[1]),
                        "close": float(row[2]),
                        "high": high,
                        "low": float(row[4]),
                        "volume": abs(float(row[5])),
                    }
                )
        except (IndexError, ValueError, TypeError) as exc:
            raise RetryableError(f"無法解析 {symbol} 利率 K 線回應：{exc}") from exc

        candles.sort(key=lambda candle: candle["mts"])
        return candles

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
        0=ID, 1=SYMBOL, **2=MTS_CREATE**, 3=MTS_UPDATE, 4=AMOUNT(剩餘),
        5=AMOUNT_ORIG, 10=STATUS, 14=RATE, 15=PERIOD。

        **`created_at_ms` 於 2026-08-19 補上並實打驗證**（D038）：那天場上唯一一張單
        回傳 `'1787087004000'`，換算 `2026-08-19 05:03:24 +0800`，與掛單當輪的日誌
        完全一致；同一次回應的 MTS_UPDATE 是同一個值，等於證明那張單 18 小時
        沒被動過。**這個欄位是閒置時間量測的基準**——用交易所的時間而不是自己記，
        重啟、重新部署都不會把它弄丟。

        欄位名帶 `_ms` 後綴是刻意的：`loan_offers.created_at` 是 ISO 字串，
        這裡是毫秒整數，兩個都叫 `created_at` 遲早有人拿去相減。
        """
        parsed: List[Dict[str, Any]] = []
        for offer in offers:
            parsed.append(
                {
                    # **id 一定要轉成整數**：取消端點只收整數，收到字串會回 `id: invalid`
                    # （2026-08-15 實單踩過，見 DECISIONS.md D026）。
                    "id": int(offer[0]),
                    "symbol": offer[1],
                    # 取不到就是 None：閒置時間是輔助資訊，為了它讓一輪巡檢失敗
                    # 並不划算（與 `_parse_positions` 對 opened_at 的處置一致）。
                    "created_at_ms": _optional_millis(offer[2] if len(offer) > 2 else None),
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

        **credits 已於 2026-08-29 用真實回應核對過**（B6，抄在
        `tests/unit/test_bitfinex_client.py` 的 `REAL_FUNDING_CREDIT`）：22 欄、
        數值全是字串，`[5]/[11]/[12]/[13]` 四格與官方文件一致，整列走完
        `_parse_positions()` 之後與 DB 裡那筆部位逐欄相同。

        ⚠ **loans 仍未核對**：它要「已被借走但還沒用掉」的時刻，實打當下錢已經
        被借走，端點回空陣列。所以解析維持防禦式：長度不足就跳過該筆並把原始內容
        寫進日誌，讓第一筆真實回應自己把結構告訴我們（D027 的做法）。
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

    def get_funding_ledger(
        self,
        currency: str,
        limit: int = 500,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """查帳本（`/v2/auth/r/ledgers/{ccy}/hist`），P2-2 的資料源。

        **這是這個專案唯一一個「交易所自己說的錢」**。其他所有績效數字都是推論：
        成交時間靠利率＋時間配對推出來、還款時間靠巡檢偵測、實得年化是兩者相乘。
        **帳本是那條推論鏈唯一的錨。**

        **2026-08-30 對正式帳號唯讀實打過**，真實回應抄在
        `tests/unit/test_bitfinex_client.py` 的 `REAL_LEDGER_ROWS`。三件事與
        官方文件不同或值得記下來（B6 預測過「ledger 是下一個重災區」，中了）：

        1. **`[2]` 不是 placeholder，是錢包名稱**（實測 `'funding'`／`'exchange'`）。
           官方文件把 `[2]`、`[4]`、`[7]` 都標成 placeholder，而 `[4]`／`[7]`
           確實是 `None`。**照文件寫會丟掉唯一能分辨錢包的欄位。**
        2. **數值全是字串**（`'0.04203999'`）——與 `funding_credits` 同一族（D027）。
        3. 🔴 **帳本裡混著別的東西**：27 列裡有 6 列錢包轉帳、1 列幣別兌換。
           **而且同一筆轉帳會出現兩列、正負相反、掛在不同錢包上**
           ——所以「把金額加總」與「只取正數」**兩種做法都會算錯**。
           分類一定要看 `description` ＋ `wallet`，見 `core/earnings.py`。
        """
        if self.dry_run:
            return []
        if self.exchange is None:
            raise FatalError("交易所客戶端尚未初始化，無法查詢帳本。")

        params: Dict[str, Any] = {"currency": currency, "limit": int(limit)}
        if start_ms is not None:
            params["start"] = int(start_ms)
        if end_ms is not None:
            params["end"] = int(end_ms)

        try:
            rows = self.exchange.private_post_auth_r_ledgers_currency_hist(params)
        except (ccxt.RateLimitExceeded, ccxt.NetworkError) as exc:
            raise RetryableError(f"查詢帳本逾時或超過速率限制：{exc}") from exc
        except ccxt.AuthenticationError as exc:
            raise FatalError(f"查詢帳本認證失敗：{exc}") from exc
        except ccxt.ExchangeError as exc:
            raise FatalError(f"查詢帳本時交易所回傳錯誤：{exc}") from exc

        return self._parse_ledger(rows)

    def _parse_ledger(self, rows) -> List[Dict[str, Any]]:
        """解析帳本列。**欄位對照見 `get_funding_ledger()` 的說明。**

        解析不了的一列不讓整批失敗，但**一定要留下原始內容**——否則就是
        「成交了卻沒人知道」的翻版，只是換個地方發生（D026）。
        """
        parsed: List[Dict[str, Any]] = []
        for row in rows:
            try:
                if len(row) <= 8:
                    raise IndexError(f"欄位數只有 {len(row)}，少於預期的 9")
                parsed.append(
                    {
                        "id": str(row[0]),
                        "currency": row[1],
                        # `[2]` 官方文件標成 placeholder，實測是錢包名稱。
                        "wallet": row[2],
                        "mts": int(row[3]) if row[3] is not None else None,
                        "amount": float(row[5]),
                        "balance": float(row[6]) if row[6] is not None else None,
                        "description": row[8] or "",
                    }
                )
            except (IndexError, ValueError, TypeError) as exc:
                self.logger.error(f"無法解析帳本列：{exc}；原始回應：{row!r}")
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
        except (ccxt.AuthenticationError, ccxt.ExchangeError) as exc:
            # 這兩種一起接：餘額不足這件事 ccxt 是丟 `AuthenticationError` 出來的
            # （D025），而它下次改版丟哪一種沒有人保證。**分類看訊息，不看型別。**
            if _is_insufficient_balance(str(exc)):
                self.logger.warning(f"建立放貸掛單失敗：融資錢包餘額不足（{exc}）")
                raise SkipCycleError(f"融資錢包餘額不足，本輪不掛單：{exc}") from exc
            if isinstance(exc, ccxt.AuthenticationError):
                self.logger.error(f"建立放貸掛單認證失敗：{exc}")
            else:
                self.logger.error(f"建立放貸掛單時交易所回傳錯誤：{exc}")
            raise FatalError(str(exc)) from exc

        # 回應為通知信封：[4]=FUNDING_OFFER_ARRAY，[6]=STATUS，[7]=TEXT
        # https://docs.bitfinex.com/reference/rest-auth-submit-funding-offer
        status = response[6] if len(response) > 6 else None
        if status != "SUCCESS":
            text = response[7] if len(response) > 7 else status
            # 拒單的理由也可能是餘額不足，而它是走信封回來、不是拋例外
            # ——兩條路都要問同一個問題，否則哪天回應形式一改就漏掉一半。
            if _is_insufficient_balance(str(text)):
                self.logger.warning(f"建立放貸掛單被拒：融資錢包餘額不足（{text}）")
                raise SkipCycleError(f"融資錢包餘額不足，本輪不掛單：{text}")
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
