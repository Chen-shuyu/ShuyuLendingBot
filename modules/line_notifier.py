import os
from typing import Optional

import requests


class LineNotifier:
    """Thin wrapper for LINE Notify. It is disabled unless configured."""

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
