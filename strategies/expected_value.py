# -*- coding: utf-8 -*-
"""期望值策略：不問「排第幾位」，問「掛在這個價位，單位時間賺多少」。

## 為什麼要換掉排隊位置（D035）

`OrderBookDepthStrategy` 的模型是「排在前面的錢越少，成交越快」，前提是需求會
**穩定地**從簿子前端一路吃過來。2026-08-17 的實測否定了這個前提：

- 最近 30 天，**90.0% 的小時曾觸及年化 8% 以上**，但只有 44.7% 的小時「收在」8% 以上
- 單根 1 小時 K 的振幅動輒 5 個百分點（08-17 20:00 那根：開 7.26%、收 5.47%、
  **高 9.78%**、低 4.92%）

也就是說，這個市場的成交是**陣發掃單**——需求來的時候一口氣掃到 9~10%，
沒來的時候簿子前端也不動。在這種結構下：

> **站在隊伍最前面，不會讓你更快成交，只會保證你用最低價成交。**

而簿子底端長期被大額低價單佔住（D033 那道牆一天之內從 182 萬長到 445 萬），
排隊條件「前方不超過 100 萬」在牆以上無解，於是報價被**強制**押到牆價上。
2026-08-16 那兩筆成交正是同一件事的兩面：19:31 以年化 9.12% 成交（該小時最高
11.68%）、21:31 以 5.47% 成交（**該小時最高 11.77%**）。

## 這個策略在做什麼

沿用 D034 已經驗證過的那條算式——**單位時間報酬**：

    實質年化 = 掛單利率 × 借出期間 ÷ (等待時間 + 借出期間)

差別在 D034 只拿它比較「重掛划不划得來」兩條路，這裡拿它**掃過所有候選價位**，
挑實質年化最高的那一個。等待時間不再是人手填進設定檔的常數（D032 要求的正是
這件事），而是每輪從 K 線重新估：

    掛在利率 r 的等待時間 ≈ 逐根掃過歷史 K，平均要等幾根才遇到 high ≥ r

`high` 就是「那一小時需求掃到多高」，所以「high ≥ r」等於「那一小時我們會被掃到」。
這個估計法**天生處理了陣發性**：用逐根走訪算連續落空的長度，而不是拿命中率取倒數
——後者會把「平均 3 小時一次」和「六小時空手、接著連中三次」算成同一件事。

## 為什麼估計會偏樂觀，以及為什麼可以接受

判定「high ≥ r 就會成交」假設我們那張單當時正躺在簿子上。實際上機器人每輪會
重新評估，取消重掛的空窗期就接不到掃單。D034 已經把「往下調價的重掛」擋掉了，
單子因此傾向留在場上，但空窗仍然存在。

偏樂觀的方向是**高估成交速度**，也就是傾向掛得比最佳解略高一點、等久一點。
在這個市場結構下那一側比較安全：實質年化曲線在 9%~10.5% 之間非常平
（8.76% ~ 9.61%），而往下掉到 5.47% 是斷崖。

## 保留的兩道防線

`minimum_rate`（年化 8%）與 `market_floor_pct` 都**原封不動**沿用。
期望值算出來的價位通常遠高於兩者，所以它們平常不會生效——但它們擋的是
「資料異常導致期望值算出一個荒謬的低價」，那正是不該省的保險。

**特別註記**：一度打算調低 `minimum_rate`，因為當下 30 分鐘內「年化 8% 以上成交
佔 0.0%」。那個判斷用一個時間切片代表市場，與 D030 記過的爆發桶陷阱是同一類錯誤，
查完 K 線就推翻了（D035）。年化 8% 的平均等待只有 0.6 小時，保留成本接近零。
"""

import statistics
from typing import Any, Dict, List, Optional, Tuple

from strategies.base import OfferPlan
from strategies.orderbook_depth import OrderBookDepthStrategy


class ExpectedValueStrategy(OrderBookDepthStrategy):
    """以單位時間報酬期望值選擇掛單利率（見 DECISIONS.md D035）。

    刻意繼承 `OrderBookDepthStrategy`：金額拆分、風控上限、成交價下限、
    利率量化、排隊位置描述全部共用，**只有「怎麼決定 base_rate」這一步不同**。
    這樣兩個策略的差異就是一個可以單獨檢視的方法，不是兩份平行演化的程式碼。
    """

    requires_book = True
    requires_trades = True
    requires_candles = True

    def __init__(self, config):
        super().__init__(config)
        strategy_config = config.get("strategy", {})

        # 用最近幾小時的 K 線做校準。**這是這個策略唯一的「窗」旋鈕**，
        # 而且它與 `target_queue_usd` 有本質差別：後者是人手算出來的**答案**
        # （「排 100 萬」），這個只是**取樣範圍**，答案每輪重算。
        #
        # 預設 168（7 天）：短到能反映當前的市場狀態，長到有 168 個樣本。
        # 實測 7 天窗的最佳解是年化 9.75%（實質 9.23%），30 天窗是 10.50%
        # （實質 9.61%）——兩者方向一致，差別在 30 天窗涵蓋了利率較高的時期。
        self.ev_window_hours = int(strategy_config.get("ev_window_hours", 168))

        # 候選價位至少要在窗內命中這麼多次才採用。**防的是尾端**：
        # 窗內最高的那一兩根 K 永遠「命中 1 次」，不擋的話期望值會一路往上爬到
        # 一個只發生過一次的價位，然後掛在那裡等一個不會再來的掃單。
        self.ev_min_hits = int(strategy_config.get("ev_min_hits", 5))

        # 少於這麼多根 K 就當資料不足，本輪不掛（不退回排隊定價，理由見 `build_offer_plan`）。
        self.ev_min_candles = int(strategy_config.get("ev_min_candles", 48))

        # 每輪抓幾根 K。要蓋得住 `ev_window_hours` 並留餘裕（交易所偶爾會缺根）。
        self.candle_limit = int(strategy_config.get("candle_limit", 240))
        self.candle_timeframe = str(strategy_config.get("candle_timeframe", "1h"))

        # 這個時間框架的一根 K 等於幾小時。等待時間是以「根」數出來的，
        # 要換算成小時才能跟借出期間相加。
        self.candle_hours = float(strategy_config.get("candle_hours", 1.0))

        # 最近一次 `choose_rate()` 的完整評估結果，供迴圈層寫日誌用。
        # **策略層仍然不碰 IO**：這裡只是把算過的東西留下來，不主動輸出。
        self.last_evaluation: List[Dict[str, float]] = []

    # ------------------------------------------------------------------
    # 期望值計算
    # ------------------------------------------------------------------

    def estimate_wait_hours(self, highs: List[float], rate: float) -> Optional[Tuple[float, int]]:
        """掛在 `rate`，平均要等幾小時才遇到一次掃到這裡的需求。

        回傳 `(平均等待小時, 命中次數)`；命中次數不足時回傳 `None`。

        **逐根走訪，不用「命中率取倒數」**：後者假設命中是均勻分佈的，
        而這個市場的成交是陣發的。「六小時空手、接著連中三次」與
        「平均兩小時一次」在倒數法下完全一樣，實際的等待體驗差很多。

        命中的那一根算等 0.5 根：掃單發生在該根之內，平均落在中點。
        **尾端沒等到的那一段不計入**——它是右設限資料，當成「等了 N 根就成交」
        會系統性低估等待時間。
        """
        waits: List[float] = []
        misses = 0
        hits = 0
        for high in highs:
            if high >= rate:
                waits.append((misses + 0.5) * self.candle_hours)
                hits += 1
                misses = 0
            else:
                misses += 1

        if hits < self.ev_min_hits:
            return None
        return statistics.fmean(waits), hits

    def choose_rate(self, candles: List[Dict[str, Any]]) -> Optional[float]:
        """掃過所有候選價位，回傳實質年化最高的那一個。

        候選價位直接取自窗內出現過的 `high`：**沒有掃到過的價位不該成為候選**，
        這同時也是天然的上限——不必另外設一個「最高不准超過多少」的旋鈕。
        """
        self.last_evaluation = []
        if len(candles) < self.ev_min_candles:
            return None

        window = candles[-self.ev_window_hours :]
        highs = [candle["high"] for candle in window]
        if len(highs) < self.ev_min_candles:
            return None

        hold_hours = self.offer_period * 24.0
        best_rate: Optional[float] = None
        best_effective = 0.0

        for rate in sorted({self._quantize(high) for high in highs}):
            if rate <= 0:
                continue
            estimate = self.estimate_wait_hours(highs, rate)
            if estimate is None:
                continue
            wait_hours, hits = estimate
            # D034 的算式：單位時間報酬。等待期間的年化是 0%，所以利息要攤在
            # 「等待 ＋ 借出」的總時間上，而不是只攤在借出期間。
            effective = rate * hold_hours / (wait_hours + hold_hours)
            self.last_evaluation.append(
                {"rate": rate, "wait_hours": wait_hours, "hits": hits, "effective": effective}
            )
            if effective > best_effective:
                best_rate, best_effective = rate, effective

        return best_rate

    # ------------------------------------------------------------------
    # 掛單計畫
    # ------------------------------------------------------------------

    def build_offer_plan(
        self,
        balance_usd: float,
        frr: float,
        book: Optional[List[Dict[str, Any]]] = None,
        trades: Optional[List[Dict[str, Any]]] = None,
        candles: Optional[List[Dict[str, Any]]] = None,
    ) -> List[OfferPlan]:
        """依餘額與 K 線的期望值定價產生掛單計畫。`frr` 與 `book` 只作記錄用途。"""
        if balance_usd < self.min_required_usd:
            return []

        lendable_usd = self._apply_lend_limit(balance_usd)
        if lendable_usd < self.min_loan_size_usd:
            return []

        # 沒有 K 線就不掛。**刻意不退回排隊定價**：那正是 D035 認定選錯自變數的
        # 定價方式，拿它當備援等於「資料一缺就自動切換成一個已知會賣在底部的策略」，
        # 而且從日誌上看起來一切正常。同樣的理由 D030 已經對 FRR 講過一次。
        if not candles:
            return []

        # 成交價下限仍然要有。K 線講的是「歷史上掃到多高」，
        # 成交紀錄講的是「借款人現在實際付多少」——後者才擋得住當下的異常（D033）。
        market_rate = self.market_rate(trades)
        if market_rate is None:
            return []

        base_rate = self.choose_rate(candles)
        if base_rate is None:
            return []

        # 兩道防線沿用 D033，語意不變：下限只往上拉，不往下壓。
        base_rate = self._quantize(max(base_rate, market_rate * self.market_floor_pct))
        if base_rate < self.minimum_rate:
            return []

        count = self._resolve_spread_count(lendable_usd)
        amounts = self._split_amount(lendable_usd, count)

        plans: List[OfferPlan] = []
        for index, amount in enumerate(amounts):
            rate = self._quantize(base_rate * (1 + self.spread_step_pct) ** index)
            plans.append(
                OfferPlan(
                    currency="USD",
                    amount=amount,
                    rate=rate,
                    duration=self.offer_period,
                )
            )
        return plans
