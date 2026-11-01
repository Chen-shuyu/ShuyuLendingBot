# -*- coding: utf-8 -*-
"""`scripts/weekly_report.py`（D076）：抓資料、記號、推播。

釘的是**一週只推一次、算不出來要出聲但不要連發、不推的時候不寫 DB**。
算法與判準在 `tests/unit/test_weekly.py`。
"""

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from core import weekly
from core.tape import HOUR_MS
from db.repository import Repository
from scripts import weekly_report
from utils import clock

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
TZ = clock.get_timezone()
NOW = datetime(2026, 11, 1, 18, 40, tzinfo=TZ)
FIRST = date(2026, 10, 25)
START_MS = weekly.to_ms(weekly.midnight(FIRST))


def daily(annual_pct):
    return annual_pct / 36500


class FakeClient:
    """假的交易所客戶端：記下被呼叫幾次，可以設定要失敗。"""

    def __init__(self, pages=None, fail=None):
        self.pages = pages if pages is not None else [self._default_page()]
        self.fail = fail
        self.page_calls = []
        self.candle_calls = []

    @staticmethod
    def _default_page():
        return [(index, START_MS - 1000 * index, -1000.0, daily(7.0), 2) for index in range(1, 61)]

    def get_trades_page(self, currency, start_ms, end_ms, limit):
        self.page_calls.append((currency, start_ms, end_ms, limit))
        if self.fail:
            raise self.fail
        return self.pages.pop(0) if self.pages else []

    def get_rate_candles(self, currency, period, timeframe, limit, end_ms):
        self.candle_calls.append((period, limit, end_ms))
        hour = START_MS // HOUR_MS
        return [
            {"mts": (hour - offset) * HOUR_MS, "high": daily(6.5), "close": daily(6.5)}
            for offset in range(240, 0, -1)
        ]


class FakeNotifier:
    def __init__(self, ok=True):
        self.sent = []
        self.ok = ok

    def send(self, message):
        self.sent.append(message)
        return self.ok


@pytest.fixture
def database(tmp_path):
    """真實 schema，塞第一週的真實資料。"""
    path = tmp_path / "data" / "lending.sqlite3"
    path.parent.mkdir()
    Repository(str(path)).close()
    week = json.loads((FIXTURES / "week_20261025.json").read_text(encoding="utf-8"))
    connection = sqlite3.connect(path)
    connection.executemany(
        "INSERT INTO earnings_daily (date, currency, interest, principal_avg, updated_at) "
        "VALUES (:date, 'USD', :interest, :principal_avg, 'x')",
        week["earnings"],
    )
    connection.executemany(
        "INSERT INTO funding_positions (position_id, currency, amount, rate, period, kind, opened_at, first_seen_at, closed_at) "
        "VALUES (:position_id, :currency, :amount, :rate, :period, :kind, :opened_at, :first_seen_at, :closed_at)",
        week["positions"],
    )
    connection.executemany(
        "INSERT INTO loan_offers (offer_id, currency, amount, rate, duration, status, created_at) "
        "VALUES ('x', 'USD', :amount, :rate, :duration, :status, :created_at)",
        week["offers"],
    )
    connection.commit()
    connection.close()
    (path.parent / weekly_report.BACKUP_STATUS_FILENAME).write_text(
        json.dumps({"last_ok_at": (NOW - timedelta(hours=14)).isoformat()}), encoding="utf-8"
    )
    return path


@pytest.fixture
def notifier(monkeypatch):
    fake = FakeNotifier()
    monkeypatch.setattr(weekly_report.line_messaging, "build_notifier", lambda *_: fake)
    # 測試不碰真的金鑰檔，也不要真的等 5 秒。
    monkeypatch.setattr(weekly_report.settings, "load_secrets_from_disk", lambda _root: None)
    monkeypatch.setattr(weekly_report.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("BFX_DB_PATH", "")
    return fake


def kv(path, key):
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT value FROM bot_kv WHERE key = ?", (key,)).fetchone()
    finally:
        connection.close()
    return row[0] if row else None


def run(path, *extra, client=None, now=NOW):
    return weekly_report.main(["--db", str(path), *extra], client=client or FakeClient(), now=now)


class TestPushLine:
    def test_推一則而且記下來(self, database, notifier):
        assert run(database, "--push-line") == 0
        assert len(notifier.sent) == 1
        text = notifier.sent[0]
        assert "【收益】週報 10-25～10-31：實得 4.08%" in text
        assert text.endswith("——— 無需處理") or text.endswith("——— 需人工介入")
        assert kv(database, weekly_report.SENT_KEY) == "2026-10-25"
        record = json.loads(kv(database, f"{weekly_report.RECORD_PREFIX}2026-10-25"))
        assert record["earned_pct"] == pytest.approx(4.08, abs=0.005)

    def test_同一週第二次什麼都不做也不打網路(self, database, notifier):
        """定時器每天叫一次：週一～週六這六次都要立刻結束。"""
        assert run(database, "--push-line") == 0
        second = FakeClient()
        assert run(database, "--push-line", client=second, now=NOW + timedelta(days=1)) == 0
        assert len(notifier.sent) == 1
        assert second.page_calls == [] and second.candle_calls == []

    def test_下一週到了就算下一週(self, database, notifier):
        assert run(database, "--push-line") == 0
        assert run(database, "--push-line", now=datetime(2026, 11, 8, 18, 40, tzinfo=TZ)) == 0
        assert len(notifier.sent) == 2
        assert kv(database, weekly_report.SENT_KEY) == "2026-11-01"
        assert "11-01～11-07" in notifier.sent[1]

    def test_錯過好幾週只補最新那一週不連發(self, database, notifier):
        """同 D053：停機幾天後只補最新的一則。"""
        assert run(database, "--push-line", now=datetime(2026, 11, 25, 18, 40, tzinfo=TZ)) == 0
        assert len(notifier.sent) == 1
        assert kv(database, weekly_report.SENT_KEY) == "2026-11-15"

    def test_先記再推推失敗也不會重推(self, database, monkeypatch, notifier):
        """🔴 D053：LINE 額度每月 200 則，推不出去的週報不能每天再試一次。"""
        notifier.ok = False
        assert run(database, "--push-line") == 1
        assert kv(database, weekly_report.SENT_KEY) == "2026-10-25"
        notifier.ok = True
        assert run(database, "--push-line", now=NOW + timedelta(days=1)) == 0
        assert len(notifier.sent) == 1

    def test_算不出來要出聲但一週只出聲一次(self, database, notifier):
        boom = FakeClient(fail=RuntimeError("交易所掛了"))
        assert run(database, "--push-line", client=boom) == 1
        assert len(notifier.sent) == 1
        assert "週報 10-25～10-31 算不出來" in notifier.sent[0]
        assert "交易所掛了" in notifier.sent[0]
        assert notifier.sent[0].endswith("——— 需人工介入")
        assert kv(database, weekly_report.SENT_KEY) is None

        # 隔天還是失敗：不再推。
        again = FakeClient(fail=RuntimeError("還是掛了"))
        assert run(database, "--push-line", client=again, now=NOW + timedelta(days=1)) == 1
        assert len(notifier.sent) == 1

    def test_算不出來隔天好了就照常推(self, database, notifier):
        """記號只有算出來才寫，所以定時器會自己補上。"""
        assert run(database, "--push-line", client=FakeClient(fail=RuntimeError("x"))) == 1
        assert run(database, "--push-line", now=NOW + timedelta(days=1)) == 0
        assert len(notifier.sent) == 2
        assert "實得 4.08%" in notifier.sent[1]
        assert kv(database, weekly_report.SENT_KEY) == "2026-10-25"

    def test_抓資料停頓(self, database, notifier, monkeypatch):
        """公開端點跟機器人共用 IP：每頁之間、每次 K 線之前都要停。"""
        pauses = []
        monkeypatch.setattr(weekly_report.time, "sleep", lambda seconds: pauses.append(seconds))
        page = [(index, START_MS + index, -1.0, daily(7.0), 2) for index in range(10_000)]
        client = FakeClient(pages=[page, []])
        assert run(database, client=client) == 0
        assert pauses.count(weekly_report.PAGE_PAUSE_SECONDS) >= 2

    def test_容器沒有DB要講清楚(self, tmp_path, notifier):
        assert run(tmp_path / "nope.sqlite3", "--push-line") == 1
        assert notifier.sent == []


class TestSaved:
    """這台機器的 user journal 沒有保存，完整報告只留得住在 DB 裡。"""

    def test_推過的週印得出完整報告而且不打網路(self, database, notifier, capsys):
        assert run(database, "--push-line") == 0
        capsys.readouterr()
        client = FakeClient()
        assert run(database, "--saved", "2026-10-25", client=client) == 0
        out = capsys.readouterr().out
        assert "週報 10-25～10-31" in out
        assert "判準 1 重播" in out
        assert client.page_calls == []

    def test_沒有紀錄要講清楚(self, database, notifier, capsys):
        assert run(database, "--saved", "2026-10-25") == 1
        assert "沒有 2026-10-25 那週的紀錄" in capsys.readouterr().err

    def test_舊紀錄沒有全文就印摘要(self, database, notifier, capsys):
        repository = Repository(str(database))
        repository.set_kv(f"{weekly_report.RECORD_PREFIX}2026-10-18", json.dumps({"earned_pct": 2.84}))
        repository.close()
        assert run(database, "--saved", "2026-10-18") == 0
        assert "2.84" in capsys.readouterr().out


class TestReadOnlyByDefault:
    def test_沒給pushline不寫DB也不推(self, database, notifier, capsys):
        before = database.read_bytes()
        assert run(database) == 0
        assert notifier.sent == []
        assert kv(database, weekly_report.SENT_KEY) is None
        assert database.read_bytes() == before
        assert "週報 10-25～10-31" in capsys.readouterr().out

    def test_手動跑不看記號(self, database, notifier, capsys):
        """推過了也要印得出來：人手動跑就是想看。"""
        assert run(database, "--push-line") == 0
        capsys.readouterr()
        assert run(database) == 0
        assert "週報 10-25～10-31" in capsys.readouterr().out
        assert len(notifier.sent) == 1


class TestInputs:
    def test_逐筆從週初往前多抓6小時而且K線帶窗尾(self, database, notifier):
        client = FakeClient()
        assert run(database, client=client) == 0
        currency, start_ms, end_ms, limit = client.page_calls[0]
        assert currency == "USD"
        assert start_ms == START_MS - 6 * HOUR_MS
        assert end_ms == START_MS + 7 * 24 * HOUR_MS
        assert limit == 10_000
        # 現行設定是天期 2（這週實際用的），加上 D074 對照組，都是天期 2，只抓一次。
        assert [call[0] for call in client.candle_calls] == [2]
        assert client.candle_calls[0][1] >= 240 + 168
        assert client.candle_calls[0][2] == end_ms

    def test_上週輸過會傳給判準3(self, database, notifier):
        repository = Repository(str(database))
        repository.set_kv(
            f"{weekly_report.RECORD_PREFIX}2026-10-18", json.dumps({"lost_to_previous": True})
        )
        repository.close()
        assert weekly_report.lost_last_week(database, FIRST) is True
        assert weekly_report.lost_last_week(database, FIRST - timedelta(days=7)) is None

    def test_壞掉的紀錄當沒有(self, database, notifier):
        repository = Repository(str(database))
        repository.set_kv(f"{weekly_report.RECORD_PREFIX}2026-10-18", "不是 JSON")
        repository.close()
        assert weekly_report.lost_last_week(database, FIRST) is None

    def test_讀得到備份狀態(self, database):
        assert weekly_report.read_backup_last_ok(database) == (NOW - timedelta(hours=14)).isoformat()

    def test_備份狀態檔不見要回None讓判準喊(self, database):
        (database.parent / weekly_report.BACKUP_STATUS_FILENAME).unlink()
        assert weekly_report.read_backup_last_ok(database) is None

    def test_備份狀態檔壞掉也回None(self, database):
        (database.parent / weekly_report.BACKUP_STATUS_FILENAME).write_text("???", encoding="utf-8")
        assert weekly_report.read_backup_last_ok(database) is None

    def test_沒有FRR快照要講出來(self, database, notifier, capsys):
        assert run(database) == 0
        assert "沒有 FRR 快照" in capsys.readouterr().out

    def test_FRR空窗太久要講出來(self, database, notifier, capsys):
        connection = sqlite3.connect(database)
        connection.execute(
            "INSERT INTO market_snapshots (captured_at, currency, frr) VALUES (?, 'USD', ?)",
            (datetime(2026, 10, 26, 0, 0, tzinfo=TZ).isoformat(), daily(10.8)),
        )
        connection.commit()
        connection.close()
        assert run(database) == 0
        assert "FRR 快照最久空窗 144 小時" in capsys.readouterr().out

    def test_帳本還沒同步要講出來(self, database, notifier, capsys):
        connection = sqlite3.connect(database)
        connection.execute("DELETE FROM earnings_daily WHERE date >= '2026-11-01'")
        connection.commit()
        connection.close()
        assert run(database) == 0
        assert "2026-11-01 那筆可能還沒同步" in capsys.readouterr().out


class TestOverrides:
    def test_換個參數跑第二次(self, database, notifier, capsys):
        """「工具只在被跑過的那條路上是對的」：補算舊設定要走得通。"""
        assert run(database, "--period", "7", "--assumed-hold", "48", "--floor-annual", "8") == 0
        out = capsys.readouterr().out
        assert "現行設定 天期 7、P48、地板 8%" in out
        assert "判準 3 上一版設定" in out

    def test_自訂窗(self, database, notifier, capsys):
        assert run(database, "--since", "2026-10-26", "--until", "2026-10-28") == 0
        assert "週報 10-26～10-28" in capsys.readouterr().out

    def test_指定一週(self, database, notifier, capsys):
        assert run(database, "--week", "2026-10-25") == 0
        assert "週報 10-25～10-31" in capsys.readouterr().out


class TestResolveWindow:
    @pytest.mark.parametrize(
        "extra",
        [
            ["--week", "2026-10-26"],  # 不是週日
            ["--week", "不是日期"],
            ["--since", "2026-10-26"],  # 少一邊
            ["--until", "2026-10-26"],
            ["--since", "2026-10-28", "--until", "2026-10-26"],
        ],
    )
    def test_不合理的參數直接退出不打網路(self, database, notifier, extra):
        client = FakeClient()
        assert run(database, *extra, client=client) == 2
        assert client.page_calls == []
