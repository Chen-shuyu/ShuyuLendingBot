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
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from strategies.base import OfferPlan, Strategy


class OrderBookDepthStrategy(Strategy):
    """依訂單簿累積深度決定掛單利率（見 DECISIONS.md D030）。"""

    requires_book = True

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

    def build_offer_plan(
        self,
        balance_usd: float,
        frr: float,
        book: Optional[List[Dict[str, Any]]] = None,
    ) -> List[OfferPlan]:
        """依餘額與市場深度產生掛單計畫。`frr` 只作為記錄用途，不參與定價。"""
        if balance_usd < self.min_required_usd:
            return []

        lendable_usd = self._apply_lend_limit(balance_usd)
        if lendable_usd < self.min_loan_size_usd:
            return []

        # 沒有市場深度就不掛。**刻意不退回 FRR 那條路**：那正是已知會掛空的定價方式，
        # 拿它當備援等於「失敗時自動切換成一個確定無效的策略」，還會讓人以為有在放貸。
        if not book:
            return []

        base_rate = self._price_from_depth(book)
        if base_rate is None or base_rate < self.minimum_rate:
            return []

        count = self._resolve_spread_count(lendable_usd)
        amounts = self._split_amount(lendable_usd, count)

        plans: List[OfferPlan] = []
        for index, amount in enumerate(amounts):
            rate = round(base_rate * (1 + self.spread_step_pct) ** index, 6)
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

    def describe_queue(self, book: List[Dict[str, Any]], rate: float) -> Dict[str, float]:
        """回報「掛在 `rate` 時，前面排了多少錢」——同天期與全天期各算一份。

        兩個數字都寫進日誌，是為了**讓第一筆真實成交來裁決上面那個假設**：
        如果同天期的排隊金額才是對的，成交會比全天期版本預測的快很多。
        沒有這兩個數字，事後只會看到「成交了」，學不到任何東西。
        """
        same_period = sum(
            level["amount"]
            for level in book
            if level["rate"] < rate and level["period"] == self.offer_period
        )
        all_periods = sum(level["amount"] for level in book if level["rate"] < rate)
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
