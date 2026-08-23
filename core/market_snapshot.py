# -*- coding: utf-8 -*-
"""把一輪巡檢當下抓到的市場原始資料，壓成可以長期存放的摘要（M1 市場資料落地）。

**這個模組刻意不認識任何策略物件。** 每一個回傳的數字都只從「本輪剛抓回來的
那三份原始資料」算出來，不讀策略的 `last_evaluation`、不讀設定檔的價位偏好。
理由是 D041：跨輪殘留的狀態被當成本輪的事實報出去過一次，而日誌印錯還有鄰行
可以拆穿，**DB 裡多一列假資料沒有鄰行會反駁**——而 M2 回測工具會拿它當事實。
把「本輪的決策」留到 M1-b 另外落地，這裡守住一條看得見的界線。

**摘要一定是有損的，所以每一個有損的地方都要自己講出來**（D039 的教訓）：
- `book_truncated` 講的是「可見範圍之上一無所知」，不是「上面沒有東西了」。
- `book_curve` 是等額距切分的累積曲線，解析度就是那 20 個點，不是連續函數。
- `trade_span_minutes` 講的是這批成交涵蓋多長時間——D035 的第一個錯誤結論
  正是敗在樣本窗只有 4 小時，而當時沒有任何欄位記下這件事。
"""

import json
import statistics
from typing import Any, Dict, List, Optional

# 累積曲線切幾個點。20 點 = 每 5% 一個，整條曲線約 250 位元組，
# 而「前面排了多少錢」這個問題在這個解析度下答得出來。
BOOK_CURVE_POINTS = 20

# `get_funding_book()` 目前一次要 250 檔。檔數剛好等於上限時，
# **簿子極可能還有沒看到的部分**——這正是 A2／A3 兩個 bug 的共同根因。
BOOK_LEVEL_CAP = 250


def _weighted_median(pairs: List[tuple]) -> Optional[float]:
    """金額加權中位數：「有一半的錢是在這個利率以上換手的」。

    與 `OrderBookDepthStrategy.market_rate()` 用的是同一個定義（見那裡的完整理由：
    一筆大額借款會被拆成很多筆成交紀錄，所以筆數衡量的是撮合的破碎程度，
    不是市場的規模）。**這裡重寫一份而不是呼叫策略**，是因為這個模組不認識策略；
    定義要是哪天改了，兩邊都得改——這一點寫在這裡當提醒。
    """
    if not pairs:
        return None
    ordered = sorted(pairs, key=lambda pair: pair[0])
    total = sum(weight for _, weight in ordered)
    if total <= 0:
        return None
    half = total / 2
    running = 0.0
    for value, weight in ordered:
        running += weight
        if running >= half:
            return value
    return ordered[-1][0]


def summarize_book(book: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """供給側掛單簿的摘要。簿子是空的就回 `None`（沒觀測到就不要造一列出來）。

    **`highest_rate` 與 `truncated` 是這份摘要最重要的兩個欄位。**
    2026-08-19 現場：250 檔可見最高只到年化 9.04%，而機器人掛的是 9.78%
    ——價位在簿子之外。少了這兩欄，M2 回測會把截斷值當成真實深度讀，
    於是「前面排了多少錢」在每一個高價位上都得到同一個答案，
    判準退化成純比利率而看起來一切正常（D037／D039 記的正是這個）。
    """
    if not book:
        return None

    levels = sorted(book, key=lambda level: float(level["rate"]))
    total_amount = sum(float(level["amount"]) for level in levels)
    if total_amount <= 0:
        return None

    # 累積曲線：第 i 個點是「累積金額首次達到總額 i/20 時的利率」。
    # 反過來讀就是「掛在這個利率，前面大約排了多少錢」，而那正是 M2 要問的問題。
    curve: List[List[float]] = []
    running = 0.0
    index = 0
    for step in range(1, BOOK_CURVE_POINTS + 1):
        target = total_amount * step / BOOK_CURVE_POINTS
        while index < len(levels) and running < target:
            running += float(levels[index]["amount"])
            index += 1
        rate = float(levels[min(index, len(levels)) - 1]["rate"])
        curve.append([rate, round(running, 2)])

    # 天期分佈：D030 量到 86% 的供給擠在 2 天期，而不同天期的價格結構不同。
    # 存總額而不是各自的曲線，是刻意的取捨——已知的問題（`all_periods` 要多少錢）
    # 這樣答得出來，`same_period` 只答得出近似值。真的需要時再加欄位，
    # 但**現在不存就永遠回不去**的是原始簿子，不是這個取捨。
    period_totals: Dict[str, float] = {}
    for level in levels:
        key = str(int(level["period"]))
        period_totals[key] = round(period_totals.get(key, 0.0) + float(level["amount"]), 2)

    return {
        "levels": len(levels),
        "lowest_rate": float(levels[0]["rate"]),
        "highest_rate": float(levels[-1]["rate"]),
        "truncated": len(levels) >= BOOK_LEVEL_CAP,
        "total_amount": round(total_amount, 2),
        "curve_json": json.dumps(curve, separators=(",", ":")),
        "period_totals_json": json.dumps(period_totals, separators=(",", ":")),
    }


def summarize_trades(trades: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """近期成交的摘要。沒有成交就回 `None`。

    **`span_minutes` 不是裝飾欄位。** 同一個時間點只是把取樣窗從 20 分鐘拉到
    43 分鐘，常態價就從年化 8.75% 掉到 5.47%（D033 實測）——所以任何拿這一列
    去比較的分析，都得先看得到「這批樣本涵蓋多久」。
    """
    if not trades:
        return None

    rates = [float(trade["rate"]) for trade in trades]
    amounts = [abs(float(trade["amount"])) for trade in trades]
    timestamps = [int(trade["mts"]) for trade in trades]

    # 每個天期各算一個金額加權中位數。天期溢價非常大（2026-08-16 實測同一小時內
    # 2 天期 0.000261、30 天期 0.000319），混在一起算出來的數字不對應任何一個市場。
    by_period: Dict[str, List[tuple]] = {}
    for trade in trades:
        key = str(int(trade["period"]))
        by_period.setdefault(key, []).append(
            (float(trade["rate"]), abs(float(trade["amount"])))
        )
    period_rates = {
        key: median
        for key, median in (
            (key, _weighted_median(pairs)) for key, pairs in by_period.items()
        )
        if median is not None
    }
    period_counts = {key: len(pairs) for key, pairs in by_period.items()}

    return {
        "count": len(trades),
        "span_minutes": round((max(timestamps) - min(timestamps)) / 60000, 2),
        "latest_mts": max(timestamps),
        "volume": round(sum(amounts), 2),
        "rate_min": min(rates),
        "rate_median": statistics.median(rates),
        "rate_weighted_median": _weighted_median(list(zip(rates, amounts))),
        "rate_max": max(rates),
        "period_rates_json": json.dumps(period_rates, separators=(",", ":")),
        "period_counts_json": json.dumps(period_counts, separators=(",", ":")),
    }


def summarize_candles(candles: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """K 線的摘要。**原始 K 線另外整根存進 `market_candles`**，這裡只留指標。

    分開存的理由是重複度：K 線每小時才換一根，而巡檢 600 秒一輪。
    照「每輪存一份窗」的作法，同一根 K 一天會被寫進去 6 次、240 根的窗一天
    就是三萬多列在講 24 根 K 的事。
    """
    if not candles:
        return None

    highs = [float(candle["high"]) for candle in candles]
    ordered = sorted(highs)
    return {
        "count": len(candles),
        "latest_mts": max(int(candle["mts"]) for candle in candles),
        "high_median": statistics.median(ordered),
        "high_p75": ordered[min(int(len(ordered) * 0.75), len(ordered) - 1)],
        "high_max": max(highs),
        "close_latest": float(max(candles, key=lambda candle: int(candle["mts"]))["close"]),
    }
