# -*- coding: utf-8 -*-
"""訂單簿深度策略：以「排隊位置」定價，而不是以某個指標加減碼。

## 為什麼不再用 FRR

`FrrPlusStrategy` 的算式是 `FRR + premium`。2026-08-16 的實測證實這條路走不通：
FRR 是**落後的加權平均**，當日為 0.000322（年化 11.77%），而 fUSD 市場當天實際
成交的最高利率只有 0.000274（年化 10.00%）——**FRR 本身就已經高過市場天花板**，
所以 `FRR + 任何正數` 必然掛空，連 `premium_rate = 0` 都不會成交。掛了 78 輪、
12 小時，一筆都沒借出去。

用負的 premium 硬壓下來只是權宜：它綁在 FRR 上，FRR 一漂移掛單就跟著跑掉。

## 這個策略在做什麼

市場的成交價帶極窄（年化 8.7%～10.0%），**訂價權不在我們手上**——借款人不肯付
更高，掛 19% 不是比較貪心，是沒有買家。所以真正的問題不是「利率訂多高」，
而是**「在這條窄帶裡站第幾位」**。

訂單簿直接回答了這件事：想要多快成交，就看願意排在多少錢後面。演算法只有一句——
**在「排在我們前面的錢不超過 `target_queue_usd`」的前提下，挑利率最高的那一檔。**

`target_queue_usd` 是這個策略唯一需要調的旋鈕，語意是「我願意排在多少錢後面」。
它可以直接換算成等待時間：除以該天期每小時的成交金額即可。2026-08-16 的實測，
2 天期每小時流過約 415 萬 USD，所以 100 萬 ≈ 等 15 分鐘。

## 為什麼排隊位置比利率重要（這個資金規模下尤其如此）

以 344 USD 計算：空轉一天損失約 0.074 USD，而利率多爭取 1 個百分點一天只多賺
0.008 USD。**空轉一天，要靠「利率高 1 個百分點」跑 9 天才補得回來。**
所以寧可掛低一點立刻成交，絕不為了多半個百分點去多等——這條算式是整個策略的依據。

## `minimum_rate` 的語意在這裡是「不賣」，不是「拉高」

舊策略寫 `max(frr + premium, minimum_rate)`，意思是「算出來太低就拉到底線」——
問題是拉上去的價位可能整個超出簿子，結果是**掛一張永遠不會成交的單**，
帳面上看起來很體面，實際上等於沒放貸。

這裡改成：算出來的價位低於 `minimum_rate` 就**整輪不掛**。低於底線代表市場現在
不值得借，那就等下一輪——而不是掛一個假裝有在放貸的價格。

## 只看訂單簿會被一筆低價大單牽著走（D033）

2026-08-16 夜間實際發生：簿子最底端出現一道 **182 萬 USD 掛在 0.00015**
（年化 5.47%），而同一小時 2 天期的實際成交中位數是 0.00026（年化 9.5%）。
排隊規則是「排在我前面的錢不超過 `target_queue_usd`（100 萬）」，
有了這道牆之後**任何高於 0.00015 的價位前面都排著 182 萬**——條件在牆以上無解，
於是策略一路跟著牆把自己的報價砍到年化 5.47%，並且真的成交了。

根因不在排隊規則本身，而在**訂單簿只講「有人開價多少」，講不出「借款人實際付多少」**。
所以這裡多讀一份近期成交紀錄，算出常態成交價（同天期成交的金額加權中位數）當作
**下限**：排隊規則算出來的價位低於這個下限時，就把價位拉到下限。

這與上一節「不要用 `max(base, minimum_rate)` 把價格拉高」**不衝突**，
差別在下限是哪來的：`minimum_rate` 是寫死的常數，拉上去可能整個超出簿子；
而這裡的下限取自**實際成交**，某個價位有成交紀錄，就證明那個價位賣得掉。
"""

from decimal import ROUND_DOWN, Decimal
from typing import Any, Dict, List, Optional

from strategies.base import OfferPlan, Strategy


class OrderBookDepthStrategy(Strategy):
    """依訂單簿累積深度決定掛單利率（見 DECISIONS.md D030）。"""

    requires_book = True
    requires_trades = True

    def __init__(self, config):
        strategy_config = config.get("strategy", {})
        self.min_required_usd = float(strategy_config.get("min_required_usd", 150))
        self.min_loan_size_usd = float(strategy_config.get("min_loan_size_usd", 150))
        self.minimum_rate = float(strategy_config.get("minimum_rate", 0.0001))
        self.spread_count = int(strategy_config.get("spread_count", 1))
        self.spread_step_pct = float(strategy_config.get("spread_step_pct", 0.15))
        self.max_to_lend_usd = float(strategy_config.get("max_to_lend_usd", 0))
        self.max_percent_to_lend = float(strategy_config.get("max_percent_to_lend", 0))
        # 掛單天期。沿用 `short_duration` 當預設值，這樣只想換策略、不想動天期的人
        # 不必多設一個鍵。
        self.offer_period = int(
            strategy_config.get("offer_period", strategy_config.get("short_duration", 2))
        )
        self.target_queue_usd = float(strategy_config.get("target_queue_usd", 1_000_000))

        # 成交價下限相關（見 D033）。
        # `market_floor_pct` 是「常態成交價的幾成」，1.0 = 完全不肯低於常態價。
        # 調低 = 更容易成交但可能賤賣；調高 = 守住價格但市場真的走低時會掛空。
        self.market_floor_pct = float(strategy_config.get("market_floor_pct", 0.85))
        # 少於這麼多筆同天期成交就當樣本不足，本輪不掛（見 `market_rate()`）。
        self.min_trade_samples = int(strategy_config.get("min_trade_samples", 50))
        # 只採用最近這段時間的成交。市場冷清時一批成交可能橫跨大半天，
        # 那種舊資料拿來當「現在的價格」並不合適。
        self.trade_window_hours = float(strategy_config.get("trade_window_hours", 6))
        # 每輪要抓多少筆成交。**不能設太小**：實測 1000 筆在活躍時段只涵蓋 1.2 分鐘，
        # 樣本不足會讓策略整輪不掛；10000 是這支端點的上限，約可涵蓋 40 分鐘。
        self.trade_limit = int(strategy_config.get("trade_limit", 10_000))
        # 送出前把利率**無條件捨去**到幾位小數，見 `_quantize()`。
        self.rate_decimals = int(strategy_config.get("rate_decimals", 8))

    def build_offer_plan(
        self,
        balance_usd: float,
        frr: float,
        book: Optional[List[Dict[str, Any]]] = None,
        trades: Optional[List[Dict[str, Any]]] = None,
        candles: Optional[List[Dict[str, Any]]] = None,
    ) -> List[OfferPlan]:
        """依餘額、市場深度與近期成交產生掛單計畫。`frr` 只作記錄用途，不參與定價。"""
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

        # 沒有市場深度就不掛。**刻意不退回 FRR 那條路**：那正是已知會掛空的定價方式，
        # 拿它當備援等於「失敗時自動切換成一個確定無效的策略」，還會讓人以為有在放貸。
        if not book:
            return self._skip("拿不到市場深度（訂單簿），無法定價（刻意不退回 FRR）")

        # 沒有成交資料同樣不掛。代價是不對稱的：少掛一輪只損失幾毫（344 USD 空轉
        # 一整天也才 0.074 USD），而在看不見成交價的情況下掛錯價位，
        # 是把資金用半價鎖住好幾天——2026-08-16 夜間那筆正是如此（D033）。
        market_rate = self.market_rate(trades)
        if market_rate is None:
            return self._skip("近期成交樣本不足，算不出常態成交價，無法設定成交價下限")

        base_rate = self._price_from_depth(book)
        if base_rate is None:
            return self._skip("訂單簿上找不到可用的檔位")

        # **下限只往上拉，不往下壓**：排隊規則算出來的價位若已經高於常態成交價，
        # 那是市場自己給的好價錢，沒有理由砍掉它。
        base_rate = self._quantize(max(base_rate, market_rate * self.market_floor_pct))
        if base_rate < self.minimum_rate:
            return self._skip(
                f"排隊定價加上成交價下限後為年化 {base_rate * 365 * 100:.2f}%，"
                f"仍低於地板年化 {self.minimum_rate * 365 * 100:.2f}%，本輪不賣"
            )

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

    def _price_from_depth(self, book: List[Dict[str, Any]]) -> Optional[float]:
        """挑出「排在我們前面的錢不超過預算」的最高利率。

        `book` 由 `api` 層保證已按利率升冪排序、且只含供給側（正金額）。

        累積時**先加當檔金額再判斷**：同一個利率上是時間優先，我們是新單，
        得排在那一檔現有的錢後面。少加這一筆會系統性高估自己的位置。

        **競爭者不分天期一起算**（保守）。Bitfinex 的撮合是否真的讓不同天期的
        offer 互相排隊，官方文件沒有講清楚，我們也還沒有成交資料可以驗證。
        兩種假設錯的代價不對稱：只算同天期會低估前面的錢、把單子掛高而掛空；
        全部一起算最多是掛低一點、早點成交。在「空轉一天要 9 天才補得回來」的
        規模下，寧可選會成交的那一邊。
        """
        ahead = 0.0
        best: Optional[float] = None
        for level in book:
            ahead += level["amount"]
            if ahead <= self.target_queue_usd:
                best = level["rate"]
            else:
                break

        if best is None:
            # 連第一檔都塞不進預算：代表 `target_queue_usd` 設得比簿子最前面那一檔
            # 還小。掛在簿子最前面是這種設定下唯一合理的解讀（使用者要的是「快」），
            # 真的太低會被 `minimum_rate` 擋下來。
            best = book[0]["rate"]
        return best

    def market_rate(self, trades: Optional[List[Dict[str, Any]]]) -> Optional[float]:
        """近期成交的「常態價位」：**同天期成交的金額加權中位數**。

        意思是「有一半的錢是在這個利率以上換手的」。
        樣本不足時回傳 `None`，呼叫端據此決定本輪不掛。

        **為什麼要用金額加權，而不是每筆一票**：一筆大額借款會被拆成很多筆成交紀錄，
        所以「筆數」衡量的是撮合的破碎程度，不是市場的規模。2026-08-16 夜間實測，
        整段 43 分鐘裡利率低於 0.00016 的成交**佔筆數 11.5%、佔金額 29.9%**——
        那是一道低價牆正在被慢慢啃掉。

        **為什麼不按時間分桶、每桶一票**（最早的寫法，實測不可用）：那會讓
        「1 筆 150 USD 的死時段」與「1211 筆、8,675,257 USD 的活躍時段」各算一票。
        同一個時間點只是把取樣窗從 20 分鐘拉到 43 分鐘，算出來的常態價就從
        年化 8.75% 掉到 5.47%——**這種下限擋不住任何東西**。金額加權天生沒有這個
        問題：死時段的權重本來就趨近於零，而爆發是真的有那麼多錢在那個價位換手。

        **中位數而不是平均**：單一筆離譜的成交拉不動中位數。這與 D030 記過的
        「爆發桶汙染」是同一個防線，只是換成用金額而不是用時間去平衡。

        **只算同天期**：天期溢價非常大（2026-08-16 實測同一小時內，2 天期中位數
        0.000261、30 天期 0.000319、120 天期 0.000320）。混在一起會讓短天期的下限
        被長天期拉高，掛出去就是掛空——那正是 FRR 落後問題換個來源重演。
        代價是天期冷門時樣本會不足，那時寧可不掛。
        """
        if not trades:
            return None

        latest_mts = max(int(trade["mts"]) for trade in trades)
        window_start = latest_mts - int(self.trade_window_hours * 3600 * 1000)

        sample = [
            (float(trade["rate"]), float(trade["amount"]))
            for trade in trades
            if int(trade["period"]) == self.offer_period
            and int(trade["mts"]) >= window_start
            and float(trade["rate"]) > 0
            and float(trade["amount"]) > 0
        ]
        if len(sample) < self.min_trade_samples:
            return None

        sample.sort()
        half = sum(amount for _, amount in sample) / 2
        cumulative = 0.0
        for rate, amount in sample:
            cumulative += amount
            if cumulative >= half:
                return rate
        return sample[-1][0]

    def _quantize(self, rate: float) -> float:
        """把利率**無條件捨去**到交易所可接受的精度。

        **一定要捨去，不能四捨五入。** 對放貸方而言利率越低排得越前面，
        而四捨五入有一半的機率把價格往上推——推上去就可能跨過某一檔，
        從「排在那一檔前面」變成「跟它同價、而且因為時間優先排在它後面」。

        2026-08-16 夜間就是這樣掛出去的：排隊規則算出 0.000149995，
        那個價位排在一道 182 萬 USD 的牆**前面**；`round(x, 6)` 把它變成 0.00015，
        正好等於那道牆的利率，於是我們被送到 182 萬的**後面**（D033）。
        少賺捨去的那點零頭，遠比排錯位置便宜。
        """
        quantum = Decimal(1).scaleb(-self.rate_decimals)
        return float(Decimal(str(rate)).quantize(quantum, rounding=ROUND_DOWN))

    def describe_queue(
        self,
        book: List[Dict[str, Any]],
        rate: float,
        period: Optional[int] = None,
    ) -> Dict[str, float]:
        """回報「掛在 `rate` 時，前面排了多少錢」——同天期與全天期各算一份。

        `period` 不給就採設定檔的 `offer_period`。**要問「場上那張單排在哪」時
        一定要明確傳它**：那張單的天期是掛出去當下決定的，不保證等於設定檔現在的值
        （分桶實驗一旦開始，同時掛 2 天與 30 天就是常態）。拿設定值去描述另一個天期的
        單子，算出來的是一個不存在的隊伍。

        兩個數字都寫進日誌，是為了**讓真實成交來裁決一個還沒驗證的假設**：
        不同天期的掛單到底有沒有在同一個隊伍裡排。如果同天期那個數字才是對的，
        成交會比全天期版本預測的快很多。沒有這兩個數字，事後只會看到「成交了」，
        學不到任何東西。

        **同價位的錢要算進「前面」**（`<=` 而不是 `<`）：同一個利率上是時間優先，
        我們是後到的，得排在那一檔既有金額的後面。這一點原本與 `_price_from_depth()`
        不一致——後者一直是把當檔金額算進去的，只有這裡漏掉——
        於是 2026-08-16 夜間日誌報「前方 1,026 USD」，真實情況卻是 182 萬（D033）。

        已知的小誤差：我們自己那張掛單若已經在場上，也會落在這一檔而被算成「前面」。
        以目前的金額量級（數百 USD vs 數萬起跳的門檻）不影響判斷，而且方向偏保守。
        """
        target_period = self.offer_period if period is None else int(period)
        same_period = sum(
            level["amount"]
            for level in book
            if level["rate"] <= rate and level["period"] == target_period
        )
        all_periods = sum(level["amount"] for level in book if level["rate"] <= rate)
        return {"same_period": same_period, "all_periods": all_periods}

    def _apply_lend_limit(self, balance_usd: float) -> float:
        """套用 maxtolend / maxpercenttolend 上限，回傳本輪實際可掛出的總金額。"""
        limits = []
        if self.max_to_lend_usd > 0:
            limits.append(self.max_to_lend_usd)
        if self.max_percent_to_lend > 0:
            limits.append(balance_usd * self.max_percent_to_lend / 100)
        if not limits:
            return balance_usd
        return min(balance_usd, min(limits))

    def _resolve_spread_count(self, lendable_usd: float) -> int:
        """決定實際能拆成幾筆：金額不足時逐階降回，確保每筆都達到交易所最小單量。"""
        count = self.spread_count
        while count > 1 and lendable_usd < count * self.min_loan_size_usd:
            count -= 1
        return count

    def _split_amount(self, lendable_usd: float, count: int) -> List[float]:
        """把總金額均分成 count 筆；除不盡的餘數併入利率最低、最容易成交的第一筆。

        **全程向下取到分位**：各筆加總必須 `<=` 可用餘額，多一分錢，交易所就會以
        `Invalid offer: not enough USD balance available in deposit wallet`
        拒絕**整筆**掛單（2026-08-15 實單踩過，見 DECISIONS.md D025）。
        以整數分計算同時避開浮點誤差，`Decimal(str(x))` 是為了不讓
        `500.0 - 166.66 * 3` 這種算式吃掉一分錢。
        """
        total_cents = int(Decimal(str(lendable_usd)) * 100)  # int() 截斷 = 向下取分位
        per_cents, remainder_cents = divmod(total_cents, count)
        amounts = [per_cents / 100] * count
        if remainder_cents:
            amounts[0] = (per_cents + remainder_cents) / 100
        return amounts
