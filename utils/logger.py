# -*- coding: utf-8 -*-
"""統一的日誌模組，負責輸出到終端機與本地 log 檔。"""

import logging
from datetime import datetime
from pathlib import Path
import re


class BotLogger:
    """簡化版日誌封裝，方便後續維運與除錯。"""

    def __init__(self, config, log_file=None):
        self.logger = logging.getLogger("bfx_lending_bot")
        self.logger.setLevel(getattr(logging, config.get("level", "INFO").upper(), logging.INFO))

        if self.logger.handlers:
            return

        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        self.logger.addHandler(stream_handler)

        if log_file:
            log_path = self._resolve_log_path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

        self.logger.propagate = False

    @staticmethod
    def _resolve_log_path(log_file: str) -> Path:
        path = Path(log_file)
        if re.search(r"_[0-9]{8}_[0-9]{6}$", path.stem):
            return path

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return path.parent / f"{path.stem}_{timestamp}{path.suffix}"

    def info(self, message):
        self.logger.info(message)

    def warning(self, message):
        self.logger.warning(message)

    def error(self, message):
        self.logger.error(message)
