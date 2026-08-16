# -*- coding: utf-8 -*-
"""通知訊息的統一組裝（TASKS.md P2-3）。

**為什麼需要這支模組**：在它出現之前，專案裡的通知訊息全是**散在各處的裸字串**——
`core/bot_engine.py` 三條退出路徑各拼一句、`FailureTracker` 的告警與恢復各拼一句、
`scripts/notify_failure.py` 四種單元狀態各拼一段。沒有任何地方負責「組訊息」，
`LineNotifier.send()` 只管送、不管內容長什麼樣。結果就是**句型、要不要附狀態欄位、
要不要寫「需不需要人工介入」全看當時寫的人**，手機上收到一排訊息卻看不出哪則是
機器人壞了、哪則只是它在做事。

## 格式（三段式）

```
🔴【系統】機器人已停止：致命錯誤
時間：2026-08-16 15:02:11 +0800
原因：API 金鑰無效
——— 需人工介入
```

- **第一行**：圖示 ＋ `【分類】` ＋ **一句話結論**。手機的通知列往往只看得到這一行，
  所以結論必須在這裡，不能擺到第三行才講。
- **中間**：`欄位：值` 逐行。第一個欄位固定是時間，而且**一律帶 `+0800`**
  ——同一個日誌檔曾經混過兩個時區（見 D028），訊息也不該讓人自己猜。
- **最後一行**：**「需人工介入」或「無需處理」二選一**，沒有第三種。
  D023 的教訓正是「看起來像故障、其實不用管」的訊息會訓練人忽略整個管道。

## 圖示規則（只有五個，不要一個事件配一個）

**正常事件看分類、異常事件看等級**：

| 情況 | 圖示 |
|---|---|
| 【系統】正常 | 🔵 |
| 【交易】正常 | 💰 |
| 【收益】正常 | 📊 |
| 【風控】正常 | 🛡 |
| WARNING（不分分類） | 🟡 |
| ERROR（不分分類） | 🟠 |
| CRITICAL（不分分類） | 🔴 |

這樣「有沒有事」在通知列上一眼就分得出來，而分類負責回答「是哪一面的事」。

## 這支模組不決定「要不要送」

它只負責把事件變成字串。**推播與否由呼叫端決定**，因為那是額度問題不是格式問題：
LINE 免費方案每月 200 則，例行巡檢結果只寫日誌（D024）。

## `scripts/notify_failure.py` 刻意不使用這支模組

那支腳本跑在**容器外**，而且是在「容器可能正是壞掉的那一個」的前提下執行，
所以它只用標準函式庫、不匯入專案任何模組（與 `scripts/healthcheck.py` 同一個約束，
見 TASKS.md A4 與 D024）。它自己有一份同格式的實作——**兩邊各自實作、對照同一份規格**，
改任一邊都要一起改。這件事在兩邊的 docstring 都寫了，因為下一個看到重複程式碼的人
一定會想把它們合併。
"""

from typing import Any, Dict, Iterable, Optional

from utils import clock

# 分類：第一行 `【】` 裡只能是這四個之一，不要隨手新增。
CATEGORY_SYSTEM = "系統"
CATEGORY_TRADE = "交易"
CATEGORY_EARNINGS = "收益"
CATEGORY_RISK = "風控"

# 等級：沿用日誌的四級，語意一致才不會出現「日誌寫 INFO、訊息看起來像天塌了」。
LEVEL_INFO = "INFO"
LEVEL_WARNING = "WARNING"
LEVEL_ERROR = "ERROR"
LEVEL_CRITICAL = "CRITICAL"

NORMAL_ICONS = {
    CATEGORY_SYSTEM: "🔵",
    CATEGORY_TRADE: "💰",
    CATEGORY_EARNINGS: "📊",
    CATEGORY_RISK: "🛡",
}

ABNORMAL_ICONS = {
    LEVEL_WARNING: "🟡",
    LEVEL_ERROR: "🟠",
    LEVEL_CRITICAL: "🔴",
}

FOOTER_ACTION_REQUIRED = "——— 需人工介入"
FOOTER_NO_ACTION = "——— 無需處理"

# 一年的天數，用來把 Bitfinex 的「日利率」換算成看得懂的年化。
# 不用複利：市場報價與這個專案的所有文件都用單利年化（日利率 × 365），
# 換一種算法會讓訊息裡的數字對不上 TASKS.md 的分析。
DAYS_PER_YEAR = 365


def format_timestamp(moment=None) -> str:
    """訊息用的時間戳，秒為精度並帶時區偏移。

    比日誌少了毫秒：訊息是給人在手機上看的，毫秒沒有意義；但時區偏移一定要留，
    這是 D028 的結論——時間戳要自己講清楚它是哪個時區，不要讓讀的人推測。
    """
    return (moment or clock.now()).strftime("%Y-%m-%d %H:%M:%S %z")


def format_rate(rate: float) -> str:
    """日利率 ＋ 年化，兩個都給。

    只給日利率看不出划不划算（0.000273 是高是低？），只給年化又對不上交易所畫面上
    的數字，所以兩個一起寫。
    """
    return f"{rate:.6f}/日（年化 {rate * DAYS_PER_YEAR * 100:.2f}%）"


def format_amount(amount: float, currency: str = "USD") -> str:
    return f"{amount:,.2f} {currency}"


def icon(category: str, level: str) -> str:
    """正常事件看分類、異常事件看等級。查不到就退回分類的圖示。"""
    if level in ABNORMAL_ICONS:
        return ABNORMAL_ICONS[level]
    return NORMAL_ICONS.get(category, "🔵")


def build(
    category: str,
    headline: str,
    fields: Optional[Dict[str, Any]] = None,
    level: str = LEVEL_INFO,
    action_required: bool = False,
    moment=None,
) -> str:
    """把一個事件組成三段式訊息。

    `fields` 用 dict 依插入順序輸出（Python 3.7 起有保證），時間會自動插在最前面，
    呼叫端不必每次自己加。值為 None 的欄位直接略過——寧可少一行，也不要出現
    「原因：None」這種讓人以為程式壞了的輸出。
    """
    lines = [f"{icon(category, level)}【{category}】{headline}"]

    merged: Dict[str, Any] = {"時間": format_timestamp(moment)}
    merged.update(fields or {})
    for label, value in merged.items():
        if value is None:
            continue
        lines.append(f"{label}：{value}")

    lines.append(FOOTER_ACTION_REQUIRED if action_required else FOOTER_NO_ACTION)
    return "\n".join(lines)


# --- 系統面 -----------------------------------------------------------------


def startup_check_failed(reason: Optional[str] = None) -> str:
    """啟動檢查沒過，機器人根本沒進主迴圈。"""
    return build(
        CATEGORY_SYSTEM,
        "機器人啟動檢查失敗，已停止運作",
        {"原因": reason, "影響": "沒有進入主迴圈，完全沒有掛單"},
        level=LEVEL_CRITICAL,
        action_required=True,
    )


def fatal_error(reason: str) -> str:
    """致命錯誤：重啟也不會好，systemd 也被設定成不重啟（`RestartPreventExitStatus=2`）。"""
    return build(
        CATEGORY_SYSTEM,
        "機器人發生致命錯誤，已停止運作",
        {"原因": reason, "影響": "機器人不會自行重啟（離開碼 2），掛單維持在交易所上"},
        level=LEVEL_CRITICAL,
        action_required=True,
    )


def unexpected_error(reason: str) -> str:
    """沒被分類過的例外。與致命錯誤不同：這種 systemd 會重啟，有機會自己好。"""
    return build(
        CATEGORY_SYSTEM,
        "機器人發生未預期的例外，已停止運作",
        {"原因": reason, "影響": "systemd 會嘗試自動重啟（離開碼 1）"},
        level=LEVEL_CRITICAL,
        action_required=True,
    )


def consecutive_failures(count: int, reason: str) -> str:
    """連續失敗跨過門檻。機器人還活著，是交易所那一端不通。"""
    return build(
        CATEGORY_SYSTEM,
        f"已連續 {count} 輪巡檢失敗",
        {
            "最近一次原因": reason,
            "機器人狀態": "仍在運行，每輪持續重試",
            "建議確認": "交易所連線與 API 金鑰狀態",
        },
        level=LEVEL_ERROR,
        action_required=True,
    )


def recovered() -> str:
    """從連續失敗中恢復。這則是刻意保留的——只報壞不報好，會讓人不敢相信「沒消息」。"""
    return build(
        CATEGORY_SYSTEM,
        "已恢復正常巡檢",
        {"說明": "先前的連續失敗已解除，機器人回到正常節奏"},
        level=LEVEL_INFO,
    )


# --- 交易面 -----------------------------------------------------------------


def _describe_offers(plans: Iterable[Any], dry_run: bool = False) -> Dict[str, Any]:
    """把掛單計畫攤成訊息欄位。

    一筆的時候攤平寫（金額／利率／天期各一行），多筆才逐筆列——單筆是目前的常態
    （160 USD 掛不出第二筆），為了「以後可能有多筆」就讓常態變難讀並不划算。
    """
    plans = list(plans)
    currency = plans[0].currency if plans else "USD"
    total = sum(plan.amount for plan in plans)

    fields: Dict[str, Any] = {}
    if dry_run:
        # dry-run 的掛單沒有真的送到交易所。不標出來的話，這則訊息會讓人以為錢
        # 已經在市場上了——這正是 D025／D026 那類「以為發生了、其實沒有」的誤會。
        fields["模式"] = "dry-run（未實際送出交易所）"

    if len(plans) == 1:
        plan = plans[0]
        fields["金額"] = format_amount(plan.amount, plan.currency)
        fields["利率"] = format_rate(plan.rate)
        fields["天期"] = f"{plan.duration} 天"
        return fields

    fields["筆數"] = f"{len(plans)} 筆"
    fields["合計"] = format_amount(total, currency)
    for index, plan in enumerate(plans, start=1):
        fields[f"第 {index} 筆"] = (
            f"{format_amount(plan.amount, plan.currency)}／"
            f"{format_rate(plan.rate)}／{plan.duration} 天"
        )
    return fields


def offers_placed(plans: Iterable[Any], first_cycle: bool = False, dry_run: bool = False) -> str:
    """掛單重新出現在場上。

    **這是狀態轉換，不是每輪的例行結果**：機器人每輪都會全取消重掛，若每次都推，
    一天 144 則、不到兩天燒光整月額度（D024）。只有「原本場上沒有我們的單 →
    現在有了」才值得一則訊息。
    """
    headline = "啟動後首輪掛單已送出" if first_cycle else "掛單已重新上線"
    return build(CATEGORY_TRADE, headline, _describe_offers(plans, dry_run))


def offers_gone(reason: str) -> str:
    """掛單從場上消失，**而且查過部位、確認不是成交**。

    成交偵測（P2-1）做出來之後，這則訊息的意思變窄也變準了：機器人每輪都會核對
    已借出部位，真的成交會走 `positions_opened()`。所以還會走到這裡，代表掛單消失
    **不是**因為被借走——比較可能是餘額被移走、或是掛單被交易所端取消。

    仍然刻意不把原因寫死：訊息只講查得到的事實，推測留給人。猜錯一次，
    這個管道就再也不會被相信（同 D023 的判斷）。
    """
    return build(
        CATEGORY_TRADE,
        "掛單已不在場上",
        {
            "機器人的說法": reason,
            "已排除": "本輪沒有偵測到新的已借出部位，所以不是成交",
            "可能原因": "融資錢包餘額被移走，或掛單在交易所端被取消",
        },
        level=LEVEL_WARNING,
    )


def _describe_positions(positions: Iterable[Any]) -> Dict[str, Any]:
    """把已借出部位攤成訊息欄位（單筆攤平、多筆逐列，與掛單的寫法一致）。

    部位可能是交易所回傳的 dict，也可能是從 DB 讀回來的列；兩者的鍵名刻意取成一樣
    （`amount` / `rate` / `period`），這裡才不必分兩套。
    """
    positions = list(positions)
    total = sum(float(item["amount"]) for item in positions)

    fields: Dict[str, Any] = {}
    if len(positions) == 1:
        item = positions[0]
        fields["金額"] = format_amount(float(item["amount"]))
        fields["利率"] = format_rate(float(item["rate"]))
        fields["天期"] = f"{int(item['period'])} 天"
        return fields

    fields["筆數"] = f"{len(positions)} 筆"
    fields["合計"] = format_amount(total)
    for index, item in enumerate(positions, start=1):
        fields[f"第 {index} 筆"] = (
            f"{format_amount(float(item['amount']))}／"
            f"{format_rate(float(item['rate']))}／{int(item['period'])} 天"
        )
    return fields


def positions_opened(positions: Iterable[Any], balance_usd: Optional[float] = None) -> str:
    """**錢真的借出去了。**

    這是整個專案存在的理由，也是最值得花額度的一則訊息（TASKS.md P2-4）。
    在成交偵測做出來之前，這件事發生時機器人只會寫一句「可放貸金額不足，略過本輪」
    ——與「錢包本來就是空的」完全無法區分（P2-1）。
    """
    fields = _describe_positions(positions)
    if balance_usd is not None:
        fields["剩餘可放貸"] = format_amount(balance_usd)
    return build(CATEGORY_TRADE, "資金已借出（成交）", fields)


def positions_closed(positions: Iterable[Any], balance_usd: Optional[float] = None) -> str:
    """借出的資金已還回來（到期或提前結清）。

    值得推一則：錢回到融資錢包代表**下一輪就會重新掛單**，而重新掛單就是重新定價。
    使用者若想在這個時間點調整策略，這是唯一的時機。
    """
    fields = _describe_positions(positions)
    if balance_usd is not None:
        fields["目前可放貸"] = format_amount(balance_usd)
    fields["後續"] = "下一輪會重新掛單"
    return build(CATEGORY_TRADE, "借出的資金已收回", fields)


def offer_failed(plan: Any, reason: str, retryable: bool = True) -> str:
    """交易所拒絕掛單。罕見，所以每次都推。"""
    return build(
        CATEGORY_TRADE,
        "掛單被交易所拒絕",
        {
            "金額": format_amount(plan.amount, plan.currency),
            "利率": format_rate(plan.rate),
            "天期": f"{plan.duration} 天",
            "原因": reason,
            "後續": "下一輪會自動重算金額並重試" if retryable else "機器人已停止，不會自行重試",
        },
        level=LEVEL_ERROR if retryable else LEVEL_CRITICAL,
        action_required=not retryable,
    )
