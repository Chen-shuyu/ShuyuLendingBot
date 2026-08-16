# -*- coding: utf-8 -*-
"""`utils/logger.py` 的單元測試。

重點是輪替真的有上限：常駐程式的日誌若無限增長會把磁碟塞爆，而
「固定檔名」這件事本身也需要被守住——一旦有人改回帶時間戳的檔名，
`backup_count` 就只管得住本次啟動那一串，等於沒有上限（見 DECISIONS.md D013）。
"""

import logging
from logging.handlers import RotatingFileHandler

import pytest

from zoneinfo import ZoneInfo

from utils.logger import DEFAULT_BACKUP_COUNT, DEFAULT_MAX_BYTES, BotLogger, ZonedFormatter

LOGGER_NAME = "bfx_lending_bot"


def clear_shared_logger():
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


@pytest.fixture
def make_logger():
    """建立 `BotLogger` 前先清空共用 logger 的 handler。

    pytest 8.4 起會對 `propagate=False` 的 logger 直接掛上 `LogCaptureHandler`
    以便擷取日誌，而 `BotLogger` 的設計是「已經有 handler 就不重複掛」（常駐程式
    該有的行為）。兩者相遇會讓測試裡的 `BotLogger` 一個 handler 都不掛——這是測試
    框架的行為而非程式缺陷，所以在每次建立前清乾淨即可。
    """

    def _build(config=None, log_file=None):
        clear_shared_logger()
        return BotLogger(config if config is not None else {}, log_file)

    return _build


def handlers_of(bot_logger):
    return bot_logger.logger.handlers


def file_handler_of(bot_logger):
    return next(h for h in handlers_of(bot_logger) if isinstance(h, RotatingFileHandler))


class TestHandlers:
    def test_stream_handler_only_without_file(self, make_logger):
        bot_logger = make_logger({"level": "INFO"})
        assert len(handlers_of(bot_logger)) == 1
        assert isinstance(handlers_of(bot_logger)[0], logging.StreamHandler)

    def test_adds_rotating_file_handler(self, make_logger, tmp_path):
        bot_logger = make_logger({"level": "INFO"}, str(tmp_path / "bot.log"))
        assert isinstance(file_handler_of(bot_logger), RotatingFileHandler)

    def test_creates_log_directory(self, make_logger, tmp_path):
        log_file = tmp_path / "nested" / "logs" / "bot.log"
        make_logger({}, str(log_file))
        assert log_file.parent.exists()

    def test_rotation_settings_come_from_config(self, make_logger, tmp_path):
        handler = file_handler_of(
            make_logger({"max_bytes": 2048, "backup_count": 2}, str(tmp_path / "bot.log"))
        )
        assert handler.maxBytes == 2048
        assert handler.backupCount == 2

    def test_rotation_defaults(self, make_logger, tmp_path):
        handler = file_handler_of(make_logger({}, str(tmp_path / "bot.log")))
        assert handler.maxBytes == DEFAULT_MAX_BYTES
        assert handler.backupCount == DEFAULT_BACKUP_COUNT

    def test_does_not_duplicate_handlers(self, make_logger, tmp_path):
        """同一支程式重複建立不能一直疊 handler，否則每則訊息會被寫很多次。"""
        first = make_logger({}, str(tmp_path / "bot.log"))
        BotLogger({}, str(tmp_path / "bot.log"))  # 第二次刻意不清空，模擬程式內重複建立
        assert len(handlers_of(first)) == 2

    def test_does_not_propagate_to_root(self, make_logger, tmp_path):
        bot_logger = make_logger({}, str(tmp_path / "bot.log"))
        assert bot_logger.logger.propagate is False


class TestLevel:
    def test_level_from_config(self, make_logger):
        assert make_logger({"level": "WARNING"}).logger.level == logging.WARNING

    def test_level_is_case_insensitive(self, make_logger):
        assert make_logger({"level": "debug"}).logger.level == logging.DEBUG

    def test_unknown_level_falls_back_to_info(self, make_logger):
        assert make_logger({"level": "VERBOSE"}).logger.level == logging.INFO

    def test_default_level_is_info(self, make_logger):
        assert make_logger({}).logger.level == logging.INFO


class TestRotation:
    def test_rotates_and_respects_backup_count(self, make_logger, tmp_path):
        log_file = tmp_path / "bot.log"
        bot_logger = make_logger({"max_bytes": 512, "backup_count": 2}, str(log_file))

        for index in range(200):
            bot_logger.info(f"第 {index} 則訊息，用來把檔案撐大到超過輪替門檻" * 2)

        # 固定檔名 + 最多 backup_count 份輪替檔 = 檔案總數上限
        assert sorted(p.name for p in tmp_path.glob("bot.log*")) == [
            "bot.log",
            "bot.log.1",
            "bot.log.2",
        ]

    def test_each_file_stays_near_max_bytes(self, make_logger, tmp_path):
        log_file = tmp_path / "bot.log"
        bot_logger = make_logger({"max_bytes": 1024, "backup_count": 3}, str(log_file))
        for index in range(200):
            bot_logger.info(f"訊息 {index}")

        for path in tmp_path.glob("bot.log*"):
            # RotatingFileHandler 是「寫入後才判斷是否超過」，允許最後一筆略微超出
            assert path.stat().st_size < 1024 * 2

    def test_restart_reuses_the_same_file(self, make_logger, tmp_path):
        """固定檔名的關鍵驗證：重啟不可另起一串新檔名。"""
        log_file = tmp_path / "bot.log"

        make_logger({}, str(log_file)).info("第一次啟動")
        make_logger({}, str(log_file)).info("第二次啟動")

        assert sorted(p.name for p in tmp_path.glob("*.log*")) == ["bot.log"]
        content = log_file.read_text(encoding="utf-8")
        assert "第一次啟動" in content and "第二次啟動" in content


class TestMethods:
    def test_writes_all_levels(self, make_logger, tmp_path):
        log_file = tmp_path / "bot.log"
        bot_logger = make_logger({"level": "DEBUG"}, str(log_file))
        bot_logger.debug("除錯訊息")
        bot_logger.info("一般訊息")
        bot_logger.warning("警告訊息")
        bot_logger.error("錯誤訊息")

        content = log_file.read_text(encoding="utf-8")
        for text in ("除錯訊息", "一般訊息", "警告訊息", "錯誤訊息"):
            assert text in content

    def test_exception_includes_traceback(self, make_logger, tmp_path):
        log_file = tmp_path / "bot.log"
        bot_logger = make_logger({}, str(log_file))
        try:
            raise ValueError("測試用例外")
        except ValueError:
            bot_logger.exception("掛單時發生未預期錯誤")

        content = log_file.read_text(encoding="utf-8")
        assert "掛單時發生未預期錯誤" in content
        assert "Traceback" in content
        assert "ValueError: 測試用例外" in content

    def test_debug_is_filtered_at_info_level(self, make_logger, tmp_path):
        log_file = tmp_path / "bot.log"
        bot_logger = make_logger({"level": "INFO"}, str(log_file))
        bot_logger.debug("不該出現")
        bot_logger.info("該出現")

        content = log_file.read_text(encoding="utf-8")
        assert "不該出現" not in content
        assert "該出現" in content


class TestZonedFormatter:
    """時間戳的時區必須由程式決定，不能由「這支程式跑在哪」決定。

    2026-08-16 之前 `%(asctime)s` 走行程本地時區，於是機器人在容器裡寫 UTC、
    主機端的 `scripts/notify_failure.py` 寫 CST，兩者混進**同一個日誌檔**差 8 小時，
    而且行內看不出是哪個時區。這組測試就是釘住「不會再退回那個狀態」。
    """

    def make_record(self, created):
        record = logging.LogRecord(
            name=LOGGER_NAME, level=logging.INFO, pathname=__file__, lineno=1,
            msg="測試訊息", args=(), exc_info=None,
        )
        record.created = created
        record.msecs = 123.0
        return record

    def test_renders_in_taipei_regardless_of_process_timezone(self, monkeypatch):
        # 2026-08-16 05:20:48 UTC == 13:20:48 台北。這正是實際踩到的那一輪：
        # 日誌寫 05:20:48，主機腳本寫 13:20:42，兩行相鄰卻差 8 小時。
        monkeypatch.setenv("TZ", "UTC")
        formatter = ZonedFormatter("%(asctime)s %(message)s", ZoneInfo("Asia/Taipei"))
        rendered = formatter.formatTime(self.make_record(1786857648.123))
        assert rendered.startswith("2026-08-16 13:20:48")

    def test_includes_utc_offset_so_each_line_is_self_describing(self):
        formatter = ZonedFormatter("%(asctime)s", ZoneInfo("Asia/Taipei"))
        assert formatter.formatTime(self.make_record(1786857648.123)).endswith("+0800")

    def test_keeps_millisecond_format_compatible_with_old_lines(self):
        """毫秒維持 `,123`，新舊日誌在同一個檔案裡才不會看起來像兩種格式。"""
        formatter = ZonedFormatter("%(asctime)s", ZoneInfo("Asia/Taipei"))
        assert ",123 " in formatter.formatTime(self.make_record(1786857648.123))

    def test_bot_logger_uses_configured_timezone(self, make_logger):
        bot_logger = make_logger({"timezone": "UTC"})
        formatter = bot_logger.logger.handlers[0].formatter
        assert formatter.formatTime(self.make_record(1786857648.123)).startswith(
            "2026-08-16 05:20:48"
        )

    def test_bot_logger_defaults_to_taipei(self, make_logger):
        bot_logger = make_logger({})
        formatter = bot_logger.logger.handlers[0].formatter
        assert formatter.formatTime(self.make_record(1786857648.123)).endswith("+0800")
