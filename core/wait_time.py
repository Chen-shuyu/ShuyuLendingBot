# -*- coding: utf-8 -*-
"""等待時間的校準量測（見 DECISIONS.md D045）。

**這個模組只量測，不做任何決策**——與 `core/hold_time.py` 是刻意成對的兩支：

    實質年化 = r × P ÷ (W + P)
                   ↑        ↑
            hold_time  wait_time
             量這個 P    量這個 W

`strategies/expected_value.py` 每次掛單都會把「我以為要等多久」寫進
`offer_wait_forecasts`（D038），而「實際等了多久」一直躺在 `loan_offers` 的
`created_at` 與 `funding_positions` 的 `opened_at` 裡。**兩者存了兩週，從來沒有
被對照過。** 這裡負責把它們接起來，**至於 `estimate_wait()` 要怎麼改，等 M2**
——先改參數再建量測正是 D036 記下的錯誤。

四個誠實度來源，每一個都會出現在輸出裡：

1. **沒成交就被取代的掛單是右設限樣本**：只知道「掛了這麼久還沒等到」。
   **丟掉它們，「實際等待」必然偏短**——而這正是這份報告最容易騙人的地方：
   只看成交的那幾筆，會得到「模型高估得離譜」這個過度樂觀的結論。
   做法與 D040 一致：分開報，並給出 `censored_ratio`。
2. **成交時間是我們巡檢時偵測到的時間**，不是交易所實際成交的時間。
   每一筆的等待都被**高估** 0 到一個巡檢間隔。對等待 0.28h 的那筆，
   10 分鐘的間隔是它的 60%——**小樣本的短等待幾乎全是偵測延遲**。
3. **配對是推出來的，不是交易所給的成交回報**：靠「利率相同 ＋ 開倉時間落在這張
   掛單的存活區間」。同一時段掛出兩張同利率的單就分不開，`spread_count > 1`
   的設定下這件事會真的發生（目前是 1，所以還沒踩到）。
4. **預估值只有 D038 之後的掛單才有**：更早的掛單沒有 `offer_wait_forecasts`
   紀錄。**那些筆要說「沒有預估值」，不是填 0**——填 0 會讓它們變成
   「預估 0 小時、實際 3.6 小時」的低估樣本，把結論整個翻過去。

## 為什麼要先把連續的重掛合併成「掛單期間」

2026-08-15～16 那兩天每一輪都取消重掛（D034 的守門檻還沒上線），
於是同一個掛單意圖在 `loan_offers` 裡是一百多列、每列各活 10 分鐘。
逐列去看的話，會得到「一百多筆都沒成交」這個結論——**而事實是那段期間市場上
一直有我們的一張單掛在同一個價位**。

所以連續、同利率的掛單合併成一個 `WaitSpell`（掛單期間）。**合併規則有兩條**：

1. **利率相同**——價格變了就是不同的賭注，這是 D034「重掛判準」在量測側的同一條線；
2. **中間沒有成交過**——資金出去又回來，就是新的一次等待。

第 2 條是實跑正式資料才發現要加的：只有第 1 條的話，08-20 與 08-21 那三張
各自成交過的 9.50% 會被併成一段，**五個校準樣本靜靜地變成兩個**。
合併掉幾列會跟著印出來，不會靜靜地少報。
"""

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.hold_time import MIN_SAMPLES_FOR_QUANTILE, parse_moment
from utils import clock


@dataclass(frozen=True)
class WaitSpell:
    """一段「同一個價位持續掛在場上」的期間，以及它等到了什麼。

    `hours` 對成交的期間是實際值（仍受偵測延遲高估），對沒等到的期間是**下界**
    ——`censored` 就是在講這件事，讀的人不該讓兩者混在同一個平均裡。
    """

    rate: float
    started_at: datetime
    hours: float
    censored: bool
    # **`censored` 只說「沒等到成交」，沒說「為什麼結束」。** 這兩件事被混在
    # 一起講過一次：見 `describe_spell()` 裡的說明。有沒有下一張單接手是查得到
    # 的事實，就記成事實，不要讓敘述層去猜。
    replaced: bool
    offer_count: int
    offer_ids: List[str]
    position_id: Optional[str]
    forecast_mean_hours: Optional[float]
    forecast_median_hours: Optional[float]
    forecast_window_hours: Optional[int]

    @property
    def annual_rate(self) -> float:
        """日利率換算年化（百分比），與日誌其他地方的講法一致。"""
        return self.rate * 365 * 100

    @property
    def has_forecast(self) -> bool:
        """這一段掛出去的當下有沒有留下預估值（D038 之前的沒有）。"""
        return self.forecast_mean_hours is not None

    @property
    def simultaneous(self) -> bool:
        """這一段其實是「同一輪掛出的另一張單」，不是一段真的等待。

        `spread_count > 1` 的時期（2026-08-16 之前是 3）一輪會掛出好幾張不同利率
        的單，時間戳相同。它們在時間軸上互相接續，於是前一張的「存活區間」長度
        是零——**那不是「掛了 0 小時沒成交」，那是根本還沒開始等**。

        門檻用一分鐘：巡檢間隔 600 秒，**真實的掛單期間不可能短於一分鐘**，
        所以低於這個值的一定是同輪的兄弟單，不會誤傷真樣本。

        這些段落**保留在 `spells` 裡但不計入右設限**——刪掉會讓「掛了幾張單」
        對不起來，計進去則會虛報「沒等到」的次數。兩種錯都是在講一個不存在的事。
        """
        return self.censored and self.hours < 1 / 60

    @property
    def overestimate_factor(self) -> Optional[float]:
        """預估等待 ÷ 實際等待。**只在「有預估值 ＋ 已成交」時算得出來。**

        右設限的期間一律回 `None`：它的 `hours` 是下界，拿下界當分母會把倍數
        算得比實際更大，而「模型高估幾倍」正是這份報告唯一想看的數字。

        實際等待為 0 也回 `None`（同一輪偵測到成交，除不了）。
        """
        if self.censored or not self.has_forecast or self.hours <= 0:
            return None
        return self.forecast_mean_hours / self.hours


@dataclass(frozen=True)
class WaitSummary:
    """一批掛單期間的等待摘要。

    **平均／中位數一律只用已成交的期間算**：把下界混進去會讓數字看起來有根據，
    實際上是拿「還沒發生的事」充數（同 `hold_time.HoldSummary`）。
    """

    spells: List[WaitSpell]
    filled_hours: List[float]
    censored: int
    simultaneous: int
    merged_offers: int
    detection_lag_hours: float

    @property
    def filled(self) -> int:
        return len(self.filled_hours)

    @property
    def total(self) -> int:
        return len(self.spells)

    @property
    def comparable(self) -> int:
        """真的講得出等待的段數：扣掉同輪兄弟單那些長度為零的假段落。"""
        return self.total - self.simultaneous

    @property
    def censored_ratio(self) -> float:
        """有多少比例的掛單期間沒等到成交。比例越高，下面的統計量蓋掉的就越多。

        **分母用 `comparable` 而不是 `total`**：同輪的兄弟單不是「沒等到」，
        把它們算進分母會把右設限比例稀釋掉，讓報告看起來比實際可信。
        """
        return self.censored / self.comparable if self.comparable else 0.0

    @property
    def ongoing(self) -> int:
        """右設限的段數裡，有幾段**還在計時**（還沒有下一張單接手）。

        這個數字要出現在報告裡，否則「最長的一段掛了至少 N 小時」會被讀成
        已經定案的觀測——**而它可能還在長**。同輪的兄弟單不算（那不是等待）。
        """
        return sum(
            1
            for spell in self.spells
            if spell.censored and not spell.replaced and not spell.simultaneous
        )

    @property
    def enough_for_quantile(self) -> bool:
        """樣本夠不夠報中位數，還是該直接把原始值攤開來看。"""
        return self.filled >= MIN_SAMPLES_FOR_QUANTILE

    def hours_listing(self) -> str:
        """已成交期間的等待時間，由小到大列出來，給小樣本用。"""
        return "、".join(f"{hours:.2f}h" for hours in sorted(self.filled_hours))

    @property
    def mean_hours(self) -> Optional[float]:
        return statistics.fmean(self.filled_hours) if self.filled_hours else None

    @property
    def median_hours(self) -> Optional[float]:
        return statistics.median(self.filled_hours) if self.filled_hours else None

    @property
    def longest_censored_hours(self) -> Optional[float]:
        """沒等到成交的期間裡最長的那一段。**它是反例的長度**，要單獨看得見。"""
        waits = [
            spell.hours
            for spell in self.spells
            if spell.censored and not spell.simultaneous
        ]
        return max(waits) if waits else None

    # ------------------------------------------------------------------
    # 校準：只用「有預估值 ＋ 已成交」那幾筆
    # ------------------------------------------------------------------

    @property
    def calibratable(self) -> List[WaitSpell]:
        """算得出高估倍數的那些期間。"""
        return [s for s in self.spells if s.overestimate_factor is not None]

    @property
    def overall_factor(self) -> Optional[float]:
        """總預估 ÷ 總實際。**用總量比而不是「逐筆倍數的平均」**。

        逐筆倍數的平均會被「實際等待很短」那幾筆炸掉：實際 0.28h 對預估 8.04h
        是 29.0 倍，而它只佔總等待的 3%。總量比回答的是「整體而言模型把等待
        放大了幾倍」，那才是算式裡 `W` 被誤用的量級。

        **但總量比也只是一個代表值**，所以 `factor_listing()` 一定要跟著印
        ——逐筆從 1.6× 到 29.0× 的東西，用任何單一數字轉述都會失真。
        """
        usable = self.calibratable
        if not usable:
            return None
        predicted = sum(s.forecast_mean_hours for s in usable)
        actual = sum(s.hours for s in usable)
        return predicted / actual if actual > 0 else None

    @property
    def median_factor(self) -> Optional[float]:
        """逐筆高估倍數的中位數。與 `overall_factor` 並列，兩者差很多就是警訊。"""
        factors = [s.overestimate_factor for s in self.calibratable]
        if len(factors) < MIN_SAMPLES_FOR_QUANTILE:
            return None
        return statistics.median(factors)

    def factor_listing(self) -> str:
        """逐筆高估倍數，由小到大。**離散度要跟代表值一起出現。**"""
        factors = sorted(s.overestimate_factor for s in self.calibratable)
        return "、".join(f"{factor:.1f}×" for factor in factors)

    @property
    def overestimated(self) -> int:
        """幾筆是高估（預估比實際久）。全部同號才談得上「系統性」。"""
        return sum(1 for s in self.calibratable if s.overestimate_factor > 1)

    @property
    def underestimated(self) -> int:
        return sum(1 for s in self.calibratable if s.overestimate_factor < 1)

    @property
    def calibration_rate_span(self) -> Optional[str]:
        """校準樣本涵蓋的利率範圍。

        **這是這份報告最重要的但書**：倍數只在有樣本的利率帶才成立，
        而樣本全部來自模型自己選出來的那個窄帶。往帶外外推是 D045 明文擋下的事。
        """
        usable = self.calibratable
        if not usable:
            return None
        rates = [s.annual_rate for s in usable]
        return f"{min(rates):.2f}%～{max(rates):.2f}%"


def _sort_key(offer: Dict[str, Any]) -> str:
    return str(offer.get("created_at") or "")


def build_spells(
    offers: List[Dict[str, Any]],
    positions: List[Dict[str, Any]],
    forecasts: Optional[Dict[str, Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    rate_tolerance: float = 1e-9,
) -> List[WaitSpell]:
    """把掛單紀錄與部位紀錄接成一串「掛單期間」。

    **配對規則**：一段期間結束於「下一段期間開始」或「現在」；期間內第一個
    利率相同、開倉時間落在區間內的部位，就是它等到的那一筆。

    `rate_tolerance` 用絕對值比較而不是 `==`：利率是浮點數，而 `loan_offers`
    與 `funding_positions` 的值分別來自掛單回應與部位查詢兩條路徑
    ——**兩邊經過的序列化不同，不保證位元相同**。
    """
    now = now or clock.now()
    forecasts = forecasts or {}

    usable = []
    for offer in sorted(offers, key=_sort_key):
        started = parse_moment(offer.get("created_at"))
        rate = offer.get("rate")
        if started is None or not rate:
            # 起算時間或利率壞掉的列算不出等待。**不要猜**——上層會報出有幾筆缺席。
            continue
        usable.append((started, float(rate), offer))

    # 每個部位的開倉時刻，用來切斷合併（見底下第二個條件）。
    opened_moments = []
    for position in positions:
        opened = parse_moment(position.get("opened_at")) or parse_moment(
            position.get("first_seen_at")
        )
        if opened is not None:
            opened_moments.append((opened, float(position.get("rate") or 0.0)))

    # 連續、同利率的掛單合併成一段（理由見模組 docstring），但**成交會切斷合併**。
    #
    # 🔴 **第二個條件是實跑正式資料才發現要加的。** 只比利率的話，
    # 08-20 15:15、08-21 16:09、08-21 19:11 三張 9.50% 的單會被合併成一段
    # ——而那三張**各自成交過**，中間資金出去又回來。合併掉的結果是
    # 五個校準樣本只剩兩個，而且那一段的「等 3.93 小時」講的是第一次成交，
    # 卻掛著三張單的名義。**一條合併規則靜靜地吃掉三個樣本，正是 D026
    # 「靜默失效」的樣子**：報告照樣印得出來，數字也不離譜，只是少了一半。
    groups: List[List[tuple]] = []
    for item in usable:
        started, rate, _ = item
        if groups and abs(groups[-1][-1][1] - rate) <= rate_tolerance:
            group_started = groups[-1][0][0]
            filled_between = any(
                group_started <= moment <= started
                and abs(position_rate - rate) <= rate_tolerance
                for moment, position_rate in opened_moments
            )
            if not filled_between:
                groups[-1].append(item)
                continue
        groups.append([item])

    spells: List[WaitSpell] = []
    for index, group in enumerate(groups):
        started = group[0][0]
        rate = group[0][1]
        # 這一段的結束點：下一段開始，或還沒有下一段就是現在。
        #
        # **「有沒有下一段」是事實，「為什麼結束」不是。** 最後一段的結束點取
        # `now`，那只代表「到報告產生為止還沒有下一張單接手」——它可能還躺在
        # 場上等，也可能已經消失而還沒補掛。分不出來就不要在敘述裡選一個講。
        replaced = index + 1 < len(groups)
        ends_at = groups[index + 1][0][0] if replaced else now

        matched = None
        for position in positions:
            opened = parse_moment(position.get("opened_at")) or parse_moment(
                position.get("first_seen_at")
            )
            if opened is None:
                continue
            if not (started <= opened <= ends_at):
                continue
            if abs(float(position.get("rate") or 0.0) - rate) > rate_tolerance:
                continue
            if matched is None or opened < matched[0]:
                matched = (opened, position)

        if matched is not None:
            hours = (matched[0] - started).total_seconds() / 3600
            censored = False
            position_id = str(matched[1].get("position_id", ""))
        else:
            hours = (ends_at - started).total_seconds() / 3600
            censored = True
            position_id = None

        if hours < 0:
            # 時鐘倒退或資料錯亂。負的等待沒有任何解讀方式，一律排除。
            continue

        # 預估值取這一段裡**第一張**單的紀錄：那是「決定掛這個價位」的那一刻，
        # 後面的重掛只是同一個決定的延續（同 D034 對重掛的認定）。
        forecast = None
        for _, _, offer in group:
            candidate = forecasts.get(str(offer.get("offer_id") or ""))
            if candidate:
                forecast = candidate
                break

        spells.append(
            WaitSpell(
                rate=rate,
                started_at=started,
                hours=hours,
                censored=censored,
                replaced=replaced,
                offer_count=len(group),
                offer_ids=[str(o.get("offer_id") or "") for _, _, o in group],
                position_id=position_id,
                forecast_mean_hours=(
                    float(forecast["mean_hours"])
                    if forecast and forecast.get("mean_hours") is not None
                    else None
                ),
                forecast_median_hours=(
                    float(forecast["median_hours"])
                    if forecast and forecast.get("median_hours") is not None
                    else None
                ),
                forecast_window_hours=(
                    int(forecast["window_hours"])
                    if forecast and forecast.get("window_hours") is not None
                    else None
                ),
            )
        )
    return spells


def summarize(
    offers: List[Dict[str, Any]],
    positions: List[Dict[str, Any]],
    forecasts: Optional[Dict[str, Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    detection_lag_hours: float = 0.0,
) -> WaitSummary:
    """把掛單與部位彙總成 `WaitSummary`。

    `detection_lag_hours` 傳巡檢間隔（小時）。它不參與計算，只是跟著摘要一起走，
    好讓輸出能講出「這些數字被高估的上界是多少」——量測值旁邊沒有誤差來源，
    下一個讀到它的人就會把它當成精確值（同 D040）。
    """
    spells = build_spells(offers, positions, forecasts=forecasts, now=now)
    filled = [spell for spell in spells if not spell.censored]
    return WaitSummary(
        spells=spells,
        filled_hours=[spell.hours for spell in filled],
        censored=sum(1 for spell in spells if spell.censored and not spell.simultaneous),
        simultaneous=sum(1 for spell in spells if spell.simultaneous),
        merged_offers=sum(spell.offer_count for spell in spells) - len(spells),
        detection_lag_hours=detection_lag_hours,
    )


def describe_spell(spell: WaitSpell) -> str:
    """單筆的一行敘述。

    沒等到成交的期間改口說「至少」——與 D039 對排隊位置越界、D040 對仍在借出中
    的部位一致：**講得出下界就講下界，不要把下界說成量測值。**

    右設限的期間再分兩種講法：**被下一張單取代**（已經結束的觀測）與
    **還在計時**（下界會繼續長）。兩者混講會讓後者被當成前者，理由見下面。
    """
    merged = f"（{spell.offer_count} 次重掛）" if spell.offer_count > 1 else ""
    if spell.has_forecast:
        forecast = f"，掛出時預估 平均 {spell.forecast_mean_hours:.2f}h"
        factor = spell.overestimate_factor
        if factor is not None:
            forecast += f"——高估 {factor:.1f} 倍"
    else:
        forecast = "，掛出時沒有留下預估值（早於 D038）"

    if spell.simultaneous:
        return (
            f"{spell.started_at:%m-%d %H:%M} 年化 {spell.annual_rate:.2f}%{merged}"
            f"：與同一輪的另一張單同時掛出（`spread_count > 1` 的時期），"
            f"**分不出誰先誰後，不算一段等待**"
        )
    if spell.censored:
        # 🔴 **這裡曾經對兩種情況說同一句話。** 舊版無論如何都寫「被下一張單取代」，
        # 於是**還躺在場上等的那一段會被讀成「已經結束、沒等到」**。
        # 2026-08-29 那筆年化 10.95% 正是這樣被誤述的：報告說它被取代了，
        # 而它當時還掛在場上、才躺了 1.85 小時。
        #
        # 為什麼這一句值得單獨修：**D045 的結論全靠高價端有沒有樣本撐著**，
        # 而高價端的樣本幾乎都是右設限的。把「還在計時」講成「已經結束」，
        # 等於把一個會繼續長的下界固定成量測值——D026 靜默失效的同一族，
        # 報告照樣印得出來、數字也不離譜，只是講了一件沒查證過的事。
        tail = (
            "，被下一張單取代"
            if spell.replaced
            else "，**這一段還在計時**（到報告產生為止還沒有下一張單接手，下界會繼續長）"
        )
        return (
            f"{spell.started_at:%m-%d %H:%M} 年化 {spell.annual_rate:.2f}%{merged}"
            f"：至少掛了 {spell.hours:.2f} 小時**沒有成交**{tail}{forecast}"
        )
    return (
        f"{spell.started_at:%m-%d %H:%M} 年化 {spell.annual_rate:.2f}%{merged}"
        f"：等 {spell.hours:.2f} 小時成交（部位 {spell.position_id}）{forecast}"
    )
