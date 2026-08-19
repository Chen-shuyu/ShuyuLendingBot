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

## 2026-08-19：等待估計換成「從進場時刻起算」（D038）

上面那段「逐根走訪」的算法**沒有做到它自己宣稱的事**。它逐根走訪算出每一段
命中間隔，最後卻用 `fmean()` 取平均——而「六小時空手接著連中三次」的間隔是
`[6, 0, 0]`、平均 2，「平均兩小時一次」的間隔是 `[2, 2, 2]`、平均也是 2。
**取平均這一步把它剛剛保留下來的陣發性又抹掉了。**

正確的問題不是「命中間隔平均多長」，而是**「我在一個任意時刻掛單，要等多久」**。
兩者在班次不規律時會差很多，因為隨機進場比較容易落進長的那一段空檔
（統計上的等候悖論）。實測同一份 168 小時 K 線：

| 掛單價 | 舊算法（間隔平均） | 新算法（進場等待） | 舊算實質年化 | 真實實質年化 |
|---|---|---|---|---|
| 9.12% | 1.6h | 4.3h | 8.82% | 8.37% |
| 9.78% | 2.3h | 6.0h | 9.34% | 8.70% |
| 9.96% | 3.2h | **10.8h** | 9.35% | **8.14%** |

**低估 3~4 倍，而且越往高價低估越嚴重。** 2026-08-19 的實跑是第一個負向樣本：
05:03 掛 9.78%（當輪估「平均等待 2.6h」），18 小時後仍未成交。

這是**修正一個說謊的函式**，不是選擇新策略——與 D037 認定 `_queue_ahead()`
越界時謊報「就是這麼多」屬於同一類（D026 靜默失效的第五次現身）。

## 為什麼估計仍然偏樂觀，以及為什麼可以接受

判定「high ≥ r 就會成交」假設我們那張單當時正躺在簿子上。實際上機器人每輪會
重新評估，取消重掛的空窗期就接不到掃單。D034 已經把「往下調價的重掛」擋掉了，
單子因此傾向留在場上，但空窗仍然存在。

**右設限是第二個樂觀來源**：窗尾那些「等到資料結束還沒等到」的起點，真實等待
只會比記下來的更長，這裡以「等到窗尾」計入（見 `estimate_wait()`）。所以輸出的
等待是**下界**，`censored_ratio` 就是在講這個下界有多不可信。

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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from strategies.base import OfferPlan
from strategies.orderbook_depth import OrderBookDepthStrategy


@dataclass(frozen=True)
class WaitEstimate:
    """掛在某個利率時的等待時間分佈（從任意時刻進場起算）。

    **為什麼不只回傳一個平均值**：這個市場的等待是重尾的——平均會被少數極長的
    乾旱期拉高，中位數才是「多數時候的體感」，而 `p75` 講的是壞情況。三個數字
    並列，人才看得出「平均 6 小時」背後是不是藏著「四分之一的機率超過 12 小時」。

    期望值計算本身用 `mean_hours`（期望值就該用期望值），其餘兩個是給日誌與
    事後校準看的。
    """

    rate: float
    mean_hours: float
    median_hours: float
    p75_hours: float
    hits: int
    censored: int
    samples: int

    @property
    def censored_ratio(self) -> float:
        """有多少比例的起點「等到資料結束還沒等到」。

        這個比例越高，`mean_hours` 這個下界就越不可信——**它是誠實度的刻度，
        不是可以忽略的統計細節**。
        """
        return self.censored / self.samples if self.samples else 0.0


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
    # 小工具
    # ------------------------------------------------------------------

    @staticmethod
    def _annual(daily_rate: float) -> float:
        """日利率換算成年化百分比。日誌與說明一律用年化，因為人只看得懂那個。"""
        return daily_rate * 365 * 100

    def describe_decision(self) -> Optional[str]:
        """把最近一次定價決策濃縮成一行，供迴圈層寫日誌（策略層不碰 IO）。

        **這個方法存在的理由就是 D033 的教訓**：那次用半價把 344 USD 借出去，
        事後翻日誌只有「掛出 344.30 USD，利率 0.000150」——**沒有任何一個數字
        能讓人看出那是半價**。定價基準換成期望值之後，同樣的處境原封不動重現：
        日誌看得到最後的價格，看不到它是怎麼被選出來的。

        回傳 `None` 代表這一輪沒有評估過任何候選價位（例如餘額不足就先出局了）。
        """
        if not self.last_evaluation:
            return None

        chosen = max(self.last_evaluation, key=lambda item: item["effective"])
        # 拿「最快成交的那個候選」當對照組：它就是舊策略會選的那一類價位，
        # 兩者並列才看得出這一輪的取捨到底換到了什麼。
        fastest = min(self.last_evaluation, key=lambda item: item["wait_hours"])
        # **中位數與 p75 一定要跟平均並列**（D038）：等待是重尾的，只印平均會讓
        # 「平均 6 小時」看起來像「大概 6 小時會成交」，而實際上可能是
        # 「一半機率 3.5 小時內、四分之一機率超過 12 小時」。2026-08-19 掛了 18 小時
        # 沒成交，就是落在那條尾巴裡——當輪日誌卻只寫了一句「平均等待 2.6h」。
        censored_note = ""
        if chosen["censored_ratio"] > 0:
            censored_note = f"、{chosen['censored_ratio'] * 100:.0f}% 的起點在窗內沒等到「真實等待更長」"
        return (
            f"期望值定價：{len(self.last_evaluation)} 個候選價位，"
            f"選中年化 {self._annual(chosen['rate']):.2f}%"
            f"（進場等待 平均 {chosen['wait_hours']:.1f}h／中位數 {chosen['median_hours']:.1f}h／"
            f"四分之三在 {chosen['p75_hours']:.1f}h 內、窗內命中 {chosen['hits']} 次、"
            f"實質年化 {self._annual(chosen['effective']):.2f}%{censored_note}）；"
            f"對照最快成交的候選 年化 {self._annual(fastest['rate']):.2f}%"
            f"（平均等待 {fastest['wait_hours']:.1f}h、實質年化 "
            f"{self._annual(fastest['effective']):.2f}%）"
        )

    def chosen_forecast(self) -> Optional[Dict[str, Any]]:
        """最近一輪選中的那個價位當下的等待預估，供迴圈層落 DB（D038）。

        **這是唯一「不存下來就永遠消失」的那一半資料**：實際等了多久事後算得出來
        （掛單時間與成交時間都已經在 DB 裡），但「掛出去那一刻我們以為要等多久」
        只存在於這一輪的記憶體。少了它，事後就只能拿今天的模型解釋昨天的決定。

        回傳 `None` 代表這一輪沒有評估過任何候選價位。
        """
        if not self.last_evaluation:
            return None
        chosen = max(self.last_evaluation, key=lambda item: item["effective"])
        return {
            "rate": chosen["rate"],
            "mean_hours": chosen["wait_hours"],
            "median_hours": chosen["median_hours"],
            "p75_hours": chosen["p75_hours"],
            "hits": chosen["hits"],
            "censored_ratio": chosen["censored_ratio"],
            "window_hours": self.ev_window_hours,
        }

    # ------------------------------------------------------------------
    # 期望值計算
    # ------------------------------------------------------------------

    def estimate_wait(self, highs: List[float], rate: float) -> Optional[WaitEstimate]:
        """掛在 `rate`，從任意時刻進場要等多久才遇到一次掃到這裡的需求。

        回傳等待時間的分佈；命中次數不足 `ev_min_hits` 時回傳 `None`。

        **問的是「我現在進場要等多久」，不是「命中間隔平均多長」**（D038）。
        舊版逐根走訪算出間隔後取平均，而 `[6, 0, 0]` 與 `[2, 2, 2]` 的平均都是 2
        ——取平均那一步把剛保留下來的陣發性又抹掉了。改成從**每一個小時**出發各算
        一次等待，長空檔就會依它實際佔掉的時間長度加權，這才是掛單當下面對的分佈。

        **命中的那一根算等 0.5 根**：掃單發生在該根之內，平均落在中點。

        **右設限（等到窗尾還沒等到）以「等到窗尾」計入，不丟棄**：丟棄會把最長的
        那些等待整批刪掉，正是舊版低估的來源之一。這樣算出來的是**下界**，
        真實等待只會更長，所以一併回傳 `censored` 讓上層看得見這個下界有多虛。

        實作是 O(n)：先由後往前記下「每個位置之後的第一次命中在哪」，
        再讓每個起點 O(1) 查表。naive 的雙迴圈在 168 根 × 上百個候選價位下
        要跑上百萬次比較，而這是每輪巡檢都要做的事。
        """
        total = len(highs)
        if total == 0:
            return None

        next_hit: List[Optional[int]] = [None] * total
        upcoming: Optional[int] = None
        for index in range(total - 1, -1, -1):
            if highs[index] >= rate:
                upcoming = index
            next_hit[index] = upcoming

        hits = sum(1 for high in highs if high >= rate)
        if hits < self.ev_min_hits:
            return None

        waits: List[float] = []
        censored = 0
        for start in range(total):
            target = next_hit[start]
            if target is None:
                # 右設限：至少等到窗尾，實際更長。
                waits.append((total - start) * self.candle_hours)
                censored += 1
            else:
                waits.append((target - start + 0.5) * self.candle_hours)

        ordered = sorted(waits)
        return WaitEstimate(
            rate=rate,
            mean_hours=statistics.fmean(waits),
            median_hours=statistics.median(ordered),
            p75_hours=ordered[min(int(len(ordered) * 0.75), len(ordered) - 1)],
            hits=hits,
            censored=censored,
            samples=total,
        )

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
            estimate = self.estimate_wait(highs, rate)
            if estimate is None:
                continue
            # D034 的算式：單位時間報酬。等待期間的年化是 0%，所以利息要攤在
            # 「等待 ＋ 借出」的總時間上，而不是只攤在借出期間。
            effective = rate * hold_hours / (estimate.mean_hours + hold_hours)
            self.last_evaluation.append(
                {
                    "rate": rate,
                    "wait_hours": estimate.mean_hours,
                    "median_hours": estimate.median_hours,
                    "p75_hours": estimate.p75_hours,
                    "hits": estimate.hits,
                    "censored_ratio": estimate.censored_ratio,
                    "effective": effective,
                }
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
        self.last_skip_reason = None

        if balance_usd < self.min_required_usd:
            return self._skip(
                f"可用餘額 {balance_usd:.2f} USD 低於下限 {self.min_required_usd:.2f} USD"
            )

        lendable_usd = self._apply_lend_limit(balance_usd)
        if lendable_usd < self.min_loan_size_usd:
            return self._skip(
                f"風控上限套用後只剩 {lendable_usd:.2f} USD，"
                f"低於單筆最小量 {self.min_loan_size_usd:.2f} USD"
            )

        # 沒有 K 線就不掛。**刻意不退回排隊定價**：那正是 D035 認定選錯自變數的
        # 定價方式，拿它當備援等於「資料一缺就自動切換成一個已知會賣在底部的策略」，
        # 而且從日誌上看起來一切正常。同樣的理由 D030 已經對 FRR 講過一次。
        if not candles:
            return self._skip("拿不到利率 K 線，無法估算等待時間（刻意不退回排隊定價）")

        # 成交價下限仍然要有。K 線講的是「歷史上掃到多高」，
        # 成交紀錄講的是「借款人現在實際付多少」——後者才擋得住當下的異常（D033）。
        market_rate = self.market_rate(trades)
        if market_rate is None:
            return self._skip("近期成交樣本不足，算不出常態成交價，無法設定成交價下限")

        base_rate = self.choose_rate(candles)
        if base_rate is None:
            return self._skip(
                f"K 線只有 {len(candles)} 根，或窗內沒有任何候選價位的命中次數達到 "
                f"{self.ev_min_hits} 次，估不出可信的等待時間"
            )

        # 兩道防線沿用 D033，語意不變：下限只往上拉，不往下壓。
        floored_rate = self._quantize(max(base_rate, market_rate * self.market_floor_pct))
        if floored_rate < self.minimum_rate:
            # **這一句是這次改動最重要的一行。** 在它之前，這個出口跟「錢包沒錢」
            # 寫出來的日誌一模一樣，而兩者的處置完全相反：一個要等市場回來，
            # 一個要去檢查資金為什麼不見了。
            return self._skip(
                f"期望值算出年化 {self._annual(base_rate):.2f}%、"
                f"成交價下限拉到年化 {self._annual(floored_rate):.2f}%，"
                f"仍低於地板年化 {self._annual(self.minimum_rate):.2f}%，本輪不賣"
            )
        base_rate = floored_rate

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
