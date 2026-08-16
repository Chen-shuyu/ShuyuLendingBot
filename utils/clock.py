# -*- coding: utf-8 -*-
"""全專案唯一的時區來源。

**為什麼需要這支模組**：2026-08-16 之前，專案裡有三個各自為政的時間戳來源，
結果同一個日誌檔裡混了兩個時區——機器人在容器裡跑（沒設 `TZ`，Debian 映像預設 UTC）
寫出 `05:20:48`，主機端的 `scripts/notify_failure.py` 用同樣的 `datetime.now()`
卻拿到 CST 而寫出 `13:20:42`，兩行緊挨著差 8 小時。`notify_failure.py` 的
`timestamp()` docstring 當時還寫著「與機器人日誌同格式的時間戳，讓兩邊的行可以
一起看」——**意圖是對的，但它依賴的是行程的本地時區，而那是環境決定的，不是程式決定的**。
對帳時看到日誌停在 04:23 會以為機器人掛了，其實那是 12:23 CST。

所以時區在這裡被定成**明確的應用程式屬性**，而不是繼承自容器環境：
不靠 `TZ` 環境變數、也不靠 Dockerfile 裝 tzdata（`python:3.11-slim` 本來就帶了，
已實測 `ZoneInfo("Asia/Taipei")` 在容器內可用）。要改時區就改這裡或設 `BFX_TIMEZONE`。
"""

import os
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# 專案的預設時區。使用者在台灣，日誌與 DB 一律以 CST（UTC+8）記錄。
DEFAULT_TIMEZONE = "Asia/Taipei"

# 環境變數名稱。刻意不放進 config.yaml：`db/repository.py` 的時間戳函式是模組層級的、
# 拿不到 config，而 `scripts/notify_failure.py` 根本不讀 config.yaml（見 D024 的獨立實作
# 原則）。用環境變數才能讓這三個地方走同一條規則。
TIMEZONE_ENV = "BFX_TIMEZONE"


def get_timezone(name: str = None) -> tzinfo:
    """取得專案時區；查不到時退回 UTC 而不是讓程式爆掉。

    退回 UTC 是刻意的：時區資料缺失不該讓一支放貸機器人停止運作——那是拿真金去換
    一個顯示問題。而且退回之後不會變成無聲的錯誤，因為時間戳一律帶 `+0000` 偏移，
    看日誌的人立刻會發現它不是預期的 `+0800`。
    """
    raw = name or os.getenv(TIMEZONE_ENV) or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def now(name: str = None) -> datetime:
    """目前時間，**一定帶時區**（aware）。

    帶時區這件事不只是為了好看：`scripts/healthcheck.py` 會把這個值跟
    `datetime.now(timezone.utc)` 相減算心跳年齡，兩邊只要有一邊是 naive 就會
    直接拋 `TypeError`。aware 的值不管存的是 `+08:00` 還是 `+00:00`，相減都正確。
    """
    return datetime.now(get_timezone(name))
