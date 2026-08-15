# -*- coding: utf-8 -*-
"""LINE 通知層 —— Messaging API push。

取代 2025-03 已停用的 LINE Notify（見 DECISIONS.md D002、D024）。
憑證來自 `secrets.env` 的 `LINE_CHANNEL_ACCESS_TOKEN` 與 `LINE_TO_USER_ID`
（位置與掛載方式見 D022），設定檔只留空字串佔位。

**額度是這個模組的主要設計限制**：免費方案每月 200 則（實查該帳號為
`{"type": "limited", "value": 200}`）。巡檢間隔 600 秒的話，「每輪推一則」
等於一天 144 則——**不到兩天就會把整個月的額度用光**，之後真正的故障告警
一則都送不出去。所以這個管道只送**事件**（連續失敗、恢復、致命錯誤、
systemd 放棄重啟），例行的「本輪巡檢完成」只寫日誌，見 D024。

**`send()` 永遠不拋例外**：它被呼叫的位置包含致命錯誤的退出路徑，
通知送不出去不該再影響離開碼或蓋掉原始錯誤（與 `_record_exit_reason()`
同一個原則，見 D019）。失敗一律回傳 False 並記日誌。
"""

import os
from typing import Optional

import requests

PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"
# LINE 文字訊息單則上限 5000 字，超過整包會被退掉，寧可截斷也要把訊息送出去
MAX_TEXT_LENGTH = 5000
TIMEOUT_SECONDS = 10


class LineNotifier:
    """LINE 通知的薄封裝；未設定或未啟用時一律不送出。"""

    def __init__(self, config, logger=None):
        self.enabled = bool(config.get("enabled", False))
        self.token = config.get("token") or os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or ""
        self.to_user_id = config.get("to_user_id") or os.getenv("LINE_TO_USER_ID") or ""
        self.logger = logger

    def _log(self, level: str, message: str) -> None:
        """有 logger 就記，沒有就安靜——通知層自己不該是壞掉的原因。"""
        if self.logger is not None:
            getattr(self.logger, level, self.logger.info)(message)

    def _describe_failure(self, status: int, body: str) -> str:
        """把 HTTP 狀態翻成「看得懂、知道要做什麼」的說明。

        LINE 的錯誤碼有幾個特別容易誤判，值得寫清楚：401 是 token 本身的問題，
        重試幾次都一樣；403 最常見的原因其實是「對方不是好友」而不是權限設定；
        429 則要分辨「這個月的 200 則用完了」與「短時間送太多」。
        """
        hints = {
            401: "Channel Access Token 無效或已重新發行，請到 LINE Developers Console 重新取得",
            403: "沒有權限送出。最常見的原因是收訊人已封鎖或未加該官方帳號為好友",
            404: "找不到收訊對象，請確認 LINE_TO_USER_ID 是這個 channel 底下的 user ID",
            429: "已達訊息額度上限（免費方案每月 200 則）或短時間送出過多",
        }
        hint = hints.get(status, "")
        detail = f"（{hint}）" if hint else ""
        return f"HTTP {status}{detail}，回應：{body[:200]}"

    def send(self, message: str) -> bool:
        """送出一則文字推播，成功回傳 True。

        刻意**不重試**：這個管道失敗時，事件本身已經寫進日誌與 DB
        （`FailureTracker` 與 `notify_failure.py` 都是先記錄再通知），
        而 `send()` 出現在退出路徑上，重試只會拖慢機器人結束的時間。
        """
        if not self.enabled:
            return False
        if not self.token or not self.to_user_id:
            self._log("warning", "LINE 通知已啟用，但 Channel Access Token 或收訊人 ID 未設定，略過推播")
            return False

        text = message if len(message) <= MAX_TEXT_LENGTH else message[: MAX_TEXT_LENGTH - 1] + "…"

        try:
            response = requests.post(
                PUSH_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                json={"to": self.to_user_id, "messages": [{"type": "text", "text": text}]},
                timeout=TIMEOUT_SECONDS,
            )
        except Exception as exc:  # 連線問題、逾時、DNS…一律不讓它往外拋
            self._log("error", f"LINE 推播失敗（連線層）：{type(exc).__name__}: {exc}")
            return False

        if response.status_code == 200:
            return True

        # 訊息內容不記進日誌——它可能很長，而且日誌裡本來就已經有同一則事件
        self._log("error", f"LINE 推播失敗：{self._describe_failure(response.status_code, response.text)}")
        return False


def build_notifier(config, logger=None) -> LineNotifier:
    """給 bootstrap 用的建構捷徑，讓 `main.py` 不必知道設定鍵長什麼樣。"""
    return LineNotifier(config.get("line", {}), logger)
