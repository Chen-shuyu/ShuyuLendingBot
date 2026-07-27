# -*- coding: utf-8 -*-
"""統一的日誌模組，負責輸出到終端機與本地 log 檔。

24 小時常駐執行時，單一 log 檔會無限增大，因此檔案輸出改用
`RotatingFileHandler`：固定檔名，超過 `max_bytes` 就輪替成 `.1`、`.2`……，
最多保留 `backup_count` 份，磁碟使用量才真的有上限。
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 單檔 10MB
DEFAULT_BACKUP_COUNT = 5


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
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            # 固定檔名 + 大小輪替。不再於檔名附加啟動時間戳：那樣每次重啟都會另起
            # 一串新檔案，backup_count 只管得住本次啟動那一串，長期下來等於沒有上限。
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=int(config.get("max_bytes", DEFAULT_MAX_BYTES)),
                backupCount=int(config.get("backup_count", DEFAULT_BACKUP_COUNT)),
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

        self.logger.propagate = False

    def debug(self, message):
        self.logger.debug(message)

    def info(self, message):
        self.logger.info(message)

    def warning(self, message):
        self.logger.warning(message)

    def error(self, message):
        self.logger.error(message)

    def exception(self, message):
        """記錄錯誤並附上例外堆疊，只能在 except 區塊內呼叫。"""
        self.logger.exception(message)
