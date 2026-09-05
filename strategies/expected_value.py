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

        # **算式裡那個 `P`：我們假設「借出去之後會生息多久」。**
        #
        # 🔴 **這件事 2026-08-30 之前與 `offer_period` 是同一個值，而那是個錯誤的耦合**
        # （D056）。`offer_period` 有兩個完全不同的用途：
        #   1. **送給交易所的天期**——它是合約條款，而且交易所最短只接受 2 天；
        #   2. **算式裡的 `P`**——它該是「實際會生息多久」的估計。
        # 借款人可以隨時還款，所以 (1) 是**上限**、(2) 是**期望值**，兩者本來就不同。
        # 綁在一起的後果是「想修正假設就得改合約天期」，而那條路是走不通的
        # （整數、而且低於交易所下限）。
        #
        # 預設值刻意退回 `offer_period * 24`——**沒設這個鍵的人行為完全不變**。
        self.assumed_hold_hours = float(
            strategy_config.get("assumed_hold_hours", self.offer_period * 24.0)
        )

        # **高原容差**（D061）：實質年化落在最佳值的這個比例以內的候選，
        # 一律視為**同分**，然後在同分的那一群裡**取價格最高的那一個**。
        #
        # 🔴 **為什麼需要這個東西**：實質年化曲線在 8.3～9.0% 那一段是平的
        # （`P=12` 之下全部落在 7.50～7.69），而 2026-09-05 正式資料的前兩名是
        #
        #     8.7600%  實質 = 7.695058824   <== 選中
        #     8.9279%  實質 = 7.695017700
        #
        # **差 4×10⁻⁵ 個百分點，也就是第 6 位有效數字。**
        # 同一份資料裡 `W` 的估計誤差是 **4～9 倍**（12 個樣本）——
        # **拿一個誤差以「倍」計的量，去分辨第 6 位有效數字，是在對雜訊做決策。**
        #
        # 🔴 **而且原本的平手方向是錯的。** 候選是升冪掃描、比較是嚴格大於，
        # 於是平手時保留先到的那個 = **最便宜的那個**。那不是誰寫錯了，
        # 是「取最大值」的預設寫法**在高原上會有方向**，而沒有人挑過它的方向。
        #
        # **為什麼偏高**：高原內的目標函數差是雜訊，**但價差是真的**
        # ——8.93% 比 8.76% 多 1.9% 的利息，而它落在同一片高原上。
        #
        # **為什麼不是隨機挑**：隨機會讓每輪的候選變動變成重掛，而重掛有空窗成本
        # （D034）。取最高是**確定性的**，同一窗永遠給同一個答案。
        #
        # 🔴 **類別預設是 0，正式環境的 1.0 寫在 `config.yaml`。**
        # 慣例與 `assumed_hold_hours` 相同（**沒設這個鍵的人行為完全不變**），
        # 而這裡有一個額外的、更重要的理由：
        #
        # **回測的迴歸釘子釘的是「當時那個策略會選什麼」**（D049／D050／D054／D055
        # 共 17 條）。把類別預設改成非零，等於讓那 17 條同時換值——
        # 於是「D054 的結論還成不成立」與「新旋鈕好不好」變成同一個問題，
        # **而那正是 D036 記下的那個病**：一次改兩件事，之後分不出是誰造成的。
        #
        # 設成 0 就完全退回舊行為（嚴格取最大、平手偏便宜）。
        self.ev_plateau_tolerance_pct = float(
            strategy_config.get("ev_plateau_tolerance_pct", 0.0)
        )

        # **本輪** `choose_rate()` 的完整評估結果，供迴圈層寫日誌用。
        # **策略層仍然不碰 IO**：這裡只是把算過的東西留下來，不主動輸出。
        #
        # 「本輪」三個字是 D041 的重點：這個清單一旦跨輪留著，就會被下一輪
        # 當成自己的決策報出去。重置點在 `build_offer_plan()` 的開頭，
        # 與 `last_skip_reason` 並排——那裡才是「新的一輪開始了」。
        self.last_evaluation: List[Dict[str, float]] = []

        # **本輪**評估用的那個 K 線窗長什麼樣，供 M1-b 落 DB。
        # 少了它，事後看得到「選了哪個價位」卻答不出「當時的窗到哪一根 K 為止」
        # ——而 D3 問的正是「一根 K 滾出窗，價格目標就自己跳一階」。
        #
        # **它跟 `last_evaluation` 是同一種東西，所以必須在同一個地方重置**：
        # 每多一個「本輪的狀態」，就多一個會跨輪殘留的成員（D041 已經有兩個了）。
        # 重置點只有一個，就在 `build_offer_plan()` 的開頭。
        self.last_window: Dict[str, Any] = {}

        # **本輪**評估用的那一窗 `high`，供 `evaluate_rate()` 對任意利率重估（M1-c）。
        # 留下的是窗本身而不是評估結果：場上那張既有掛單的利率通常**不在**候選集裡
        # （它是更早某一輪選出來的，中間還經過成交價下限與 spread 的加工），
        # 所以要比較「保住它 vs 改掛」就得能對一個沒算過的利率重新評估。
        #
        # **第四個「本輪的狀態」，一樣只在同一處重置**（見上面那段的理由）。
        self.last_highs: List[float] = []

        # **本輪真的被選中的那一列**（不是實質年化最高的那一列）。
        #
        # 🔴 **這個成員存在的理由是一個真的發生過的缺陷。** D061 加上高原容差之後，
        # 選中的不再必然是 `max(effective)` 的那一個，而
        # `describe_decision()`／`chosen_forecast()`／`pricing_decision()`
        # **三處各自用 `max(...)` 重算了一次「誰被選中」**。於是機器人掛 8.9279%，
        # 而日誌、`offer_wait_forecasts`、`pricing_decisions` 三處**一致地**說 8.76%
        # ——三個都錯成同一個值，看起來完全正常。
        #
        # **修法不是把三處各改一次**（那正是這個 bug 的成因），
        # 是讓「誰被選中」**只有一個來源**：`choose_rate()` 寫，其他人讀。
        #
        # **第五個「本輪的狀態」，一樣只在同一處重置。**
        self.last_chosen: Optional[Dict[str, float]] = None


    # ------------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------------

    @staticmethod
    def _annual(daily_rate: float) -> float:
        """日利率換算成年化百分比。日誌與說明一律用年化，因為人只看得懂那個。"""
        return daily_rate * 365 * 100

    def describe_decision(self) -> Optional[str]:
        """把**本輪**的定價決策濃縮成一行，供迴圈層寫日誌（策略層不碰 IO）。

        **這個方法存在的理由就是 D033 的教訓**：那次用半價把 344 USD 借出去，
        事後翻日誌只有「掛出 344.30 USD，利率 0.000150」——**沒有任何一個數字
        能讓人看出那是半價**。定價基準換成期望值之後，同樣的處境原封不動重現：
        日誌看得到最後的價格，看不到它是怎麼被選出來的。

        回傳 `None` 代表這一輪沒有評估過任何候選價位（例如餘額不足就先出局了）。
        **這個契約一度是假的**：`last_evaluation` 只在 `choose_rate()` 內重置，
        而餘額守門檻在那之前就 return，於是資金一借出，這裡就把上一輪的決策
        當成本輪的報出去——2026-08-21 22:34 起連續 21 小時、87 輪以上，
        每一輪都印出位元組完全相同的一行，而鄰行寫著「可用餘額 0.01 USD
        低於下限 150.00 USD」。修正見 D041。
        """
        # 🔴 **守門條件是 `last_chosen`，不是 `last_evaluation`。**
        # 兩者不等價：評估過一輪但沒有選出價位（例如整組候選的實質年化都是 0）
        # 時，前者是空的、後者不是。**「評估過」不等於「選出來了」**，
        # 而報告端要講的是後者。
        if self.last_chosen is None:
            return None

        chosen = self.last_chosen
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

        回傳 `None` 代表這一輪沒有評估過任何候選價位。**與
        `describe_decision()` 共用同一個清單，所以也共用 D041 那個陳舊問題**
        ——落 DB 這條路今天沒被汙染純屬呼叫順序的巧合（只在掛單成功後才呼叫，
        而那條路必定剛評估過），不是設計上的保證。
        """
        # 守門條件是 `last_chosen`，理由同 `describe_decision()`。
        if self.last_chosen is None:
            return None
        chosen = self.last_chosen
        return {
            "rate": chosen["rate"],
            "mean_hours": chosen["wait_hours"],
            "median_hours": chosen["median_hours"],
            "p75_hours": chosen["p75_hours"],
            "hits": chosen["hits"],
            "censored_ratio": chosen["censored_ratio"],
            "window_hours": self.ev_window_hours,
        }

    def pricing_decision(self) -> Optional[Dict[str, Any]]:
        """把**本輪**的定價決策整理成可以落 DB 的一份資料（M1-b 決策落地）。

        **與 `describe_decision()` 是同一份 `last_evaluation` 的兩種輸出**，
        而這件事本身就是設計的一部分：迴圈層把兩者接在一起呼叫，於是
        **日誌那一行就是 DB 那一列的鄰行**。D041 當初把決策落地擋在 M1-b 之後，
        理由正是「日誌印錯還有鄰行可以拆穿，DB 裡多一列假資料沒有鄰行會反駁」
        ——同源同時機是把那個保護延續下來的方法，不是巧合。

        回傳 `None` 代表這一輪沒有評估過任何候選價位。

        **候選集只給價位與實質年化兩排**，其餘的等待分佈只有選中的那一個留下來
        （`chosen_*`）。理由與成本見 `db/models.py` 的表註解：
        110 個候選的完整評估是 17 KB，這兩排是 2.6 KB，而
        **`effective` 就是排序依據——留下它才答得出「為什麼是這個價位」**。
        """
        # 🔴 **守門條件是 `last_chosen`，不是 `last_evaluation`。**
        # 兩者不等價：評估過一輪但沒有選出價位（例如整組候選的實質年化都是 0）
        # 時，前者是空的、後者不是。**「評估過」不等於「選出來了」**，
        # 而報告端要講的是後者。
        if self.last_chosen is None:
            return None

        chosen = self.last_chosen
        fastest = min(self.last_evaluation, key=lambda item: item["wait_hours"])
        # 排序過才存：事後要比對兩輪的候選集差在哪一個價位，靠的是這個順序。
        # 不排序的話「111 → 110 少了誰」得先自己排一次，而那正是 D3 的問題。
        ordered = sorted(self.last_evaluation, key=lambda item: item["rate"])
        return {
            # 用類別名而不是設定檔的 `mode`：M2 要對上的是「當時跑的是哪一份程式碼」，
            # 而 `mode` 只是指向它的字串，改個別名就對不上了。
            "strategy": type(self).__name__,
            "chosen_rate": chosen["rate"],
            "chosen_effective": chosen["effective"],
            "chosen_mean_hours": chosen["wait_hours"],
            "chosen_median_hours": chosen["median_hours"],
            "chosen_p75_hours": chosen["p75_hours"],
            "chosen_hits": chosen["hits"],
            "chosen_censored_ratio": chosen["censored_ratio"],
            "fastest_rate": fastest["rate"],
            "fastest_mean_hours": fastest["wait_hours"],
            "fastest_effective": fastest["effective"],
            "candidate_count": len(self.last_evaluation),
            "candidate_rates": [item["rate"] for item in ordered],
            "candidate_effectives": [item["effective"] for item in ordered],
            "window_hours": self.ev_window_hours,
            # **這個 48 是已知錯的**（D040：實測完成率 43.6%）。存下來不是因為它對，
            # 而是因為 M2 回測工具要拿它當「當時假設了什麼」——換掉它之後，
            # 舊決策才有辦法跟新決策比較。存的是假設，不是事實。
            "hold_hours_assumed": self.assumed_hold_hours,
            "candle_count": self.last_window.get("candle_count"),
            "candle_latest_mts": self.last_window.get("candle_latest_mts"),
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
        self.last_window = {}
        self.last_highs = []
        self.last_chosen = None
        if len(candles) < self.ev_min_candles:
            return None

        window = candles[-self.ev_window_hours :]
        highs = [candle["high"] for candle in window]
        if len(highs) < self.ev_min_candles:
            return None

        # 窗的兩個座標：幾根、最新那根是哪一根。**`mts` 不轉時區也不轉格式**
        # ——它是對帳時唯一不會因為時區設定而跑掉的欄位（同 `market_candles`）。
        self.last_window = {
            "candle_count": len(window),
            "candle_latest_mts": window[-1].get("mts"),
        }
        # 留給 `evaluate_rate()`：M1-c 要拿**同一窗**去評估場上那張單的利率，
        # 兩邊用同一把尺算出來的實質年化才比得起來。
        self.last_highs = highs

        # 算式裡的 `P`。**2026-08-30 起它是獨立的設定，不再等於合約天期**（D056）。
        # 回測顯示假設值落在 8～20h 這片高原上時實得年化最高（D055）。
        # ⚠ **它有一部分是在補 `W` 的偏差**（D047 的乾旱回饋圈），
        # 不是純粹的「持有時間估計」；修了 `W` 之後這個值要重調。
        #
        # 🔴 **2026-09-05：這個 12 已經被實測否定，見 D060。** 實測（篩掉 D057
        # 的幽靈樣本後）平均 **22.60h**、中位數 **11.62h**；而 D056 上線後
        # **在選中的那個價位上，結清的 3 筆有 2 筆借滿 48h**。
        #
        # 🔴 **但正確的修法不是把 12 換成別的常數**（D062）：`P` 隨 `r` 遞減
        # （`rho` = −0.383），而這裡正在用 `P` 去挑 `r`——**用一個依賴 `r` 的量
        # 當常數去最佳化 `r`，目標函數在定義上就是自我矛盾的**。
        # 要換掉的是 `HoldModel`，不是這個數字。
        hold_hours = self.assumed_hold_hours

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

        chosen_rate = self._pick_from_plateau(self.last_evaluation)
        # **唯一的來源。** 三個報告端一律讀這裡，不再各自 `max(...)` 重算。
        self.last_chosen = next(
            (item for item in self.last_evaluation if item["rate"] == chosen_rate),
            None,
        )
        return chosen_rate

    def _pick_from_plateau(
        self, evaluation: List[Dict[str, float]]
    ) -> Optional[float]:
        """從評估結果裡挑一個價位：**同分的那一群裡取最高價**（D061）。

        「同分」的定義是 `effective >= 最佳值 × (1 - 容差)`。
        容差 0 時退回舊行為（嚴格取最大、平手偏便宜）——**而舊行為是可以被
        重現的**，這一點是刻意的：沒有辦法退回去的改動，沒有辦法被比較。

        ⚠ **最佳值必須是正的才切得出高原**：`effective` 恆非負，若最佳值是 0
        則「最佳值 × (1 - 容差)」也是 0，整個候選集都會被判定同分，
        然後挑出最貴的那一個——**在一份全是 0 的評估上挑最貴的，是最壞的猜**。
        """
        usable = [item for item in evaluation if item["effective"] > 0]
        if not usable:
            return None

        best_effective = max(item["effective"] for item in usable)
        if self.ev_plateau_tolerance_pct <= 0:
            # 舊行為：升冪掃描 ＋ 嚴格大於 = 平手取最便宜。
            # **這裡要明寫出來**，不能靠「剛好 max() 會這樣」——那正是
            # 這個缺陷當初的長相：方向是實作的副作用，不是誰選的。
            for item in usable:
                if item["effective"] == best_effective:
                    return item["rate"]
            return None

        floor = best_effective * (1.0 - self.ev_plateau_tolerance_pct / 100.0)
        plateau = [item for item in usable if item["effective"] >= floor]
        return max(item["rate"] for item in plateau)

    def evaluate_rate(self, rate: float) -> Optional[Dict[str, Any]]:
        """用**本輪那一窗**回答「掛在這個利率會是什麼結果」（M1-c，D046）。

        `choose_rate()` 的候選只取自窗內出現過的 `high`，所以**場上那張既有掛單
        的利率通常不在候選集裡**——它是更早某一輪選出來的，而且中間還經過成交價
        下限與 spread 的加工（見 `build_offer_plan()`）。要把「保住它」跟「改掛
        本輪候選」並排比較，就得能對一個沒算過的利率重新評估一次。

        **兩邊一定要走同一個函式。** 候選價位的 `effective` 出自這裡的算式，
        場上那張若改用排隊金額換算，比出來的差額有一半會是兩把尺的差
        ——`bot_engine._queue_ahead()` 的註解講的是同一件事。

        回傳的 dict 與 `last_evaluation` 每一項同形狀。**本輪沒評估過**
        （`choose_rate()` 沒跑到，或 K 線根本不夠）就回 `None`。

        **命中不足 `ev_min_hits` 時照樣回一列**，只是等待相關的欄位是 `None`、
        `hits` 填實際數字：「窗裡一次都沒掃到這麼高（`hits=0`）」與「掃到了但只有
        三次（`hits=3 < 5`）」在分析長尾時意義完全不同，而回 `None` 會把兩者
        壓成同一個空白。**08-19 那張掛了 34.2 小時沒成交的單，落下來就會長這樣**
        ——那正是最想留住的一列，不能因為算不出實質年化就不寫。

        ⚠ **回傳的等待不是「還要等多久」**：`estimate_wait()` 問的是「從任意時刻
        進場要等多久」，而場上那張已經等了一段時間了。拿無記憶分佈去估剩餘等待
        是高估（D045 已量出整體高估 3.9 倍），條件機率是 M2 的題目。

        **唯讀，不動任何 `last_*`。** 它跟 `describe_decision()`／
        `pricing_decision()`／`chosen_forecast()` 是同一族：對本輪評估殘留的投影，
        所以引擎只要傳一個利率進來，不必也不該讓策略看見場上那張單（D046）。
        """
        if not self.last_highs or rate <= 0:
            return None

        hits = sum(1 for high in self.last_highs if high >= rate)
        estimate = self.estimate_wait(self.last_highs, rate)
        if estimate is None:
            return {
                "rate": rate,
                "wait_hours": None,
                "median_hours": None,
                "p75_hours": None,
                "hits": hits,
                "censored_ratio": None,
                "effective": None,
            }

        # 與 `choose_rate()` 完全同一條算式（D034）。**這個 `hold_hours` 是已知
        # 錯的**（D040：實測完成率 51.8%），但兩邊都用它，所以比較仍然公平。
        hold_hours = self.assumed_hold_hours
        return {
            "rate": rate,
            "wait_hours": estimate.mean_hours,
            "median_hours": estimate.median_hours,
            "p75_hours": estimate.p75_hours,
            "hits": estimate.hits,
            "censored_ratio": estimate.censored_ratio,
            "effective": rate * hold_hours / (estimate.mean_hours + hold_hours),
        }

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
        # **這一行是 D041 的修正本體。** 底下有六個出口會在 `choose_rate()` 之前
        # 就 return，而評估結果原本只在 `choose_rate()` 內重置——走那六條路的輪次
        # 因此繼承了上一輪的評估，並被 `describe_decision()` 當成本輪的決策報出去。
        #
        # 重置點放在這裡而不是那六個出口各補一次，是因為「新的一輪開始了」只有
        # 一個位置，而在每個出口補一次的作法，正是這個 bug 當初的成因：
        # 漏掉任何一條就再犯一次，而且漏掉的那條不會有人發現。
        #
        # **新增「本輪的狀態」時，這裡是唯一要一起加的地方**——`last_window`
        # （M1-b）就是照這條規則放進來的第三個成員。
        self.last_evaluation = []
        self.last_window = {}
        self.last_highs = []
        self.last_chosen = None

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
