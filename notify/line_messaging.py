# -*- coding: utf-8 -*-
"""LINE 通知層。

**目前的實作仍打 2025-03 已停用的 LINE Notify 端點，因此 `send()` 永遠回傳
False**，告警實際上只會留在日誌與 DB 裡。檔名先依目標架構定為
`line_messaging`，內容改寫成 LINE Messaging API push 是
`feature/m4-line-messaging` 分支的工作，卡在使用者尚未申請 Channel 憑證
（見 DECISIONS.md D002、TASKS.md）。屆時環境變數名也要一併從
`LINE_NOTIFY_TOKEN` / `LINE_NOTIFY_CHANNEL` 改為
`LINE_CHANNEL_ACCESS_TOKEN` / `LINE_TO_USER_ID`。
"""

import os
from typing import Optional

import requests


class LineNotifier:
    """LINE 通知的薄封裝；未設定或未啟用時一律不送出。"""

    def __init__(self, config):
        self.enabled = bool(config.get("enabled", False))
        self.token = config.get("token") or os.getenv("LINE_NOTIFY_TOKEN")
        self.channel = config.get("channel") or os.getenv("LINE_NOTIFY_CHANNEL")

    def send(self, message: str) -> bool:
        if not self.enabled or not self.token:
            return False

        try:
            response = requests.post(
                "https://notify-api.line.me/api/notify",
                headers={"Authorization": f"Bearer {self.token}"},
                data={"message": message},
                timeout=10,
            )
            response.raise_for_status()
            return True
        except Exception:
            return False
