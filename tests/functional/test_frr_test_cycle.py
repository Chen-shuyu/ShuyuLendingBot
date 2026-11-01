# -*- coding: utf-8 -*-
"""FRR 小額實測的一整輪（D076 第三節）：真的策略、真的 SQLite，只把交易所換成替身。

🔴 **最要緊的兩件事**：實測關著的時候一般路徑一行都不變；場上的 FRR 單絕不重掛（排隊位置就是要量的東西）。
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from core import bot_engine, frr_test
from core.bot_engine import BotEngine
from core.frr_test import FrrTestConfig, FrrTestState
from strategies.expected_value import ExpectedValueStrategy
from utils import clock
from utils.exceptions import FatalError, RetryableError, SkipCycleError

TZ = clock.get_timezone()
HOUR_MS = 3_600_000
ON = FrrTestConfig(enabled=True, offer_type="FRRDELTAFIX", period=30, offset=0.0)


def daily(annual_pct):
    return annual_pct / 36500


class FakeClient:
    """交易所替身。掛單會真的出現在場上，取消會真的把錢放回來。"""

    def __init__(self, balance=348.1199, active_offers=None, offer_error=None, cancel_works=True, cancel_error=None):
        self.balance = balance
        self.active_offers = list(active_offers or [])
        self.offer_error = offer_error
        self.cancel_works = cancel_works
        self.cancel_error = cancel_error
        self.cancel_calls = 0
        self.offers = []

    def get_active_positions(self, _currency):
        return []

    def get_active_offers(self, _currency=None):
        return list(self.active_offers)

    def get_available_balance(self, _currency):
        return self.balance

    def get_frr(self, _currency):
        return daily(10.8)

    def get_funding_book(self, _currency):
        return []

    def get_recent_trades(self, _currency, limit=10_000):
        now_ms = int(clock.now().timestamp() * 1000)
        return [
            {"mts": now_ms - 1000 * index, "amount": 1000.0, "rate": daily(7.0), "period": 7}
            for index in range(60)
        ]

    def get_rate_candles(self, _currency, period=7, timeframe="1h", limit=240):
        now_hour = int(clock.now().timestamp() * 1000) // HOUR_MS
        return [
            {
                "mts": (now_hour - offset) * HOUR_MS,
                "open": daily(6.5),
                "close": daily(6.5),
                "high": daily(6.5),
                "low": daily(4.0),
                "volume": 1000.0,
            }
            for offset in range(240, 0, -1)
        ]

    def cancel_active_offers(self, _currency):
        self.cancel_calls += 1
        if self.cancel_error:
            raise self.cancel_error
        released = list(self.active_offers)
        if self.cancel_works:
            self.balance += sum(float(offer["amount"]) for offer in released)
            self.active_offers = []
        return released

    def create_loan_offer(self, currency, amount, rate, duration, offer_type="LIMIT"):
        self.offers.append(
            {"currency": currency, "amount": amount, "rate": rate, "duration": duration, "type": offer_type}
        )
        if self.offer_error:
            raise self.offer_error
        self.balance -= amount
        created = {
            "id": 1000 + len(self.offers),
            "symbol": f"f{currency}",
            "created_at_ms": int(clock.now().timestamp() * 1000),
            "amount": amount,
            "type": offer_type,
            "rate": rate,
            "period": duration,
        }
        self.active_offers.append(created)
        return {"status": "submitted", **created}


def strategy():
    return ExpectedValueStrategy(
        {
            "strategy": {
                "min_required_usd": 150,
                "min_loan_size_usd": 150,
                "spread_count": 1,
                "offer_period": 7,
                "assumed_hold_hours": 12,
                "minimum_rate": 0.00013699,
                "market_floor_pct": 0.85,
                "min_trade_samples": 3,
                "trade_window_hours": 6,
                "ev_min_hits": 5,
                "ev_min_candles": 48,
                "ev_window_hours": 168,
                "candle_hours": 1.0,
            }
        }
    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(bot_engine.time, "sleep", lambda _seconds: None)


def engine_for(logger, notifier, client, repository, config=ON):
    return BotEngine(logger, notifier, strategy(), client, repository, frr_test=config)


def frr_offer(amount=348.11, created=None, offer_id=7):
    created = created or clock.now()
    return {
        "id": offer_id,
        "symbol": "fUSD",
        "created_at_ms": int(created.timestamp() * 1000),
        "amount": amount,
        "type": "FRRDELTAFIX",
        "rate": 0.0,
        "period": 30,
    }


def limit_offer(amount=348.11, annual=6.0):
    return {
        "id": 9,
        "symbol": "fUSD",
        "created_at_ms": int(clock.now().timestamp() * 1000),
        "amount": amount,
        "type": "LIMIT",
        "rate": daily(annual),
        "period": 7,
    }


def add_closed_position(repository, opened, closed, position_id="1", period=30, amount=348.11, rate=None):
    with repository.connection:
        repository.connection.execute(
            "INSERT INTO funding_positions (position_id, currency, amount, rate, period, kind, opened_at, first_seen_at, closed_at) "
            "VALUES (?, 'USD', ?, ?, ?, 'credit', ?, ?, ?)",
            (position_id, amount, rate or daily(10.8), period, opened.isoformat(), opened.isoformat(), closed.isoformat()),
        )


def state_of(repository):
    raw = repository.get_kv(frr_test.STATE_KEY)
    return FrrTestState.from_json(raw) if raw else None


def start_state(repository, started_at):
    repository.set_kv(frr_test.STATE_KEY, FrrTestState(started_at=started_at).to_json())


class TestOff:
    def test_關著的時候走一般路徑而且什麼都不記(self, fake_logger, fake_notifier, repository):
        client = FakeClient()
        engine_for(fake_logger, fake_notifier, client, repository, FrrTestConfig()).run_once()
        assert [offer["type"] for offer in client.offers] == ["LIMIT"]
        assert client.offers[0]["duration"] == 7
        assert repository.get_kv(frr_test.STATE_KEY) is None

    def test_沒傳設定就是關的(self, fake_logger, fake_notifier, repository):
        client = FakeClient()
        BotEngine(fake_logger, fake_notifier, strategy(), client, repository).run_once()
        assert client.offers[0]["type"] == "LIMIT"


class TestFirstRound:
    def test_場上沒單就掛一張FRR單(self, fake_logger, fake_notifier, repository):
        client = FakeClient()
        engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert client.offers == [
            {"currency": "USD", "amount": 348.11, "rate": 0.0, "duration": 30, "type": "FRRDELTAFIX"}
        ]
        assert state_of(repository).stopped_at is None
        row = repository.connection.execute(
            "SELECT offer_type, duration, status FROM loan_offers"
        ).fetchone()
        assert tuple(row) == ("FRRDELTAFIX", 30, "submitted")

    def test_金額向下取到分位(self, fake_logger, fake_notifier, repository):
        """多一分錢，交易所就拒絕整筆（D025）。"""
        client = FakeClient(balance=348.1199)
        engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert client.offers[0]["amount"] == 348.11

    def test_開始只通知一次(self, fake_logger, fake_notifier, repository):
        client = FakeClient()
        engine = engine_for(fake_logger, fake_notifier, client, repository)
        engine.run_once()
        engine.run_once()
        started = [message for message in fake_notifier.sent if "FRR 實測開始" in message]
        assert len(started) == 1
        assert "10 天沒成交就撤" in started[0]

    def test_場上的一般單要先撤(self, fake_logger, fake_notifier, repository):
        client = FakeClient(balance=0.1, active_offers=[limit_offer()])
        engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert client.cancel_calls == 1
        assert client.offers[0]["type"] == "FRRDELTAFIX"

    def test_撤不掉就不掛以免雙倍曝險(self, fake_logger, fake_notifier, repository):
        """同 D031：回應說取消了，單子可能還在場上。"""
        client = FakeClient(balance=0.1, active_offers=[limit_offer()], cancel_works=False)
        with pytest.raises(SkipCycleError):
            engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert client.offers == []

    def test_行情照樣落地(self, fake_logger, fake_notifier, repository):
        """🔴 D036：實測期間的市場資料一樣重抓不回來。"""
        engine_for(fake_logger, fake_notifier, FakeClient(), repository).run_once()
        count = repository.connection.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
        assert count == 1

    def test_心跳照樣更新(self, fake_logger, fake_notifier, repository):
        """健康檢查看的是這個：實測路徑不能讓容器被判 unhealthy。"""
        engine_for(fake_logger, fake_notifier, FakeClient(), repository).run_once()
        assert "FRR 實測" in repository.get_state()["last_action"]


class TestKeepsQueuePosition:
    def test_場上的FRR單絕不重掛(self, fake_logger, fake_notifier, repository):
        """🔴 這條壞掉，每 10 分鐘就把自己送回隊伍末端，實測就白做了。"""
        client = FakeClient(balance=0.1, active_offers=[frr_offer()])
        engine = engine_for(fake_logger, fake_notifier, client, repository)
        for _ in range(3):
            engine.run_once()
        assert client.cancel_calls == 0
        assert client.offers == []
        assert client.active_offers == [frr_offer(created=datetime.fromtimestamp(client.active_offers[0]["created_at_ms"] / 1000, TZ))]

    def test_部分成交之後錢回來就再掛一張不動舊的(self, fake_logger, fake_notifier, repository):
        client = FakeClient(balance=198.0, active_offers=[frr_offer(amount=150.0)])
        engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert client.cancel_calls == 0
        assert [offer["amount"] for offer in client.offers] == [198.0]

    def test_錢借出去了就什麼都不做(self, fake_logger, fake_notifier, repository):
        client = FakeClient(balance=0.1)
        engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert client.offers == []
        assert client.cancel_calls == 0
        assert "不夠再掛" in repository.get_state()["last_action"]


class TestStops:
    def test_10天沒成交就撤單回一般路徑(self, fake_logger, fake_notifier, repository):
        started = clock.now() - timedelta(days=10, hours=1)
        start_state(repository, started)
        client = FakeClient(balance=0.1, active_offers=[frr_offer(created=started)])
        engine = engine_for(fake_logger, fake_notifier, client, repository)

        engine.run_once()
        assert client.cancel_calls == 1
        assert client.offers == []
        assert "排不到" in state_of(repository).reason
        stopped = [message for message in fake_notifier.sent if "FRR 實測結束" in message]
        assert len(stopped) == 1 and stopped[0].endswith("——— 無需處理")

        # 下一輪：一般路徑，天期 7、LIMIT。
        engine.run_once()
        assert [(offer["type"], offer["duration"]) for offer in client.offers] == [("LIMIT", 7)]

    def test_撤單失敗就不算停下一輪再來(self, fake_logger, fake_notifier, repository):
        started = clock.now() - timedelta(days=11)
        start_state(repository, started)
        client = FakeClient(
            balance=0.1, active_offers=[frr_offer(created=started)], cancel_error=RetryableError("逾時")
        )
        with pytest.raises(RetryableError):
            engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert state_of(repository).stopped_at is None
        assert not [message for message in fake_notifier.sent if "FRR 實測結束" in message]

    def test_連兩筆排隊久持有短就停(self, fake_logger, fake_notifier, repository):
        now = clock.now()
        started = now - timedelta(days=9)
        start_state(repository, started)
        add_closed_position(repository, started + timedelta(days=3), started + timedelta(days=3, hours=5), "1")
        add_closed_position(repository, started + timedelta(days=7), started + timedelta(days=7, hours=5), "2")
        client = FakeClient(balance=348.11)
        engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert client.offers == []
        assert "提前停" in state_of(repository).reason

    def test_完成2筆就停下來要人判定(self, fake_logger, fake_notifier, repository):
        now = clock.now()
        started = now - timedelta(days=30)
        start_state(repository, started)
        add_closed_position(repository, started + timedelta(days=1), started + timedelta(days=11), "1")
        add_closed_position(repository, started + timedelta(days=12), started + timedelta(days=22), "2")
        client = FakeClient(balance=348.11)
        engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert "可以判定了" in state_of(repository).reason
        stopped = [message for message in fake_notifier.sent if "FRR 實測結束" in message]
        assert stopped[0].endswith("——— 需人工介入")

    def test_實測之前的天期30舊部位不算(self, fake_logger, fake_notifier, repository):
        """D069 那一段的部位有好幾筆，算進來會第一輪就「完成 2 筆」。"""
        now = clock.now()
        add_closed_position(repository, now - timedelta(days=50), now - timedelta(days=48), "1")
        add_closed_position(repository, now - timedelta(days=40), now - timedelta(days=38), "2")
        client = FakeClient()
        engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert client.offers[0]["type"] == "FRRDELTAFIX"
        assert state_of(repository).stopped_at is None

    def test_停了就是停了重啟不會重新開始(self, fake_logger, fake_notifier, repository):
        repository.set_kv(
            frr_test.STATE_KEY,
            FrrTestState(
                started_at=clock.now() - timedelta(days=11), stopped_at=clock.now(), reason="排不到"
            ).to_json(),
        )
        client = FakeClient()
        engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert [offer["type"] for offer in client.offers] == ["LIMIT"]

    def test_狀態看不懂就走一般路徑(self, fake_logger, fake_notifier, repository):
        repository.set_kv(frr_test.STATE_KEY, "不是 JSON")
        client = FakeClient()
        engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert [offer["type"] for offer in client.offers] == ["LIMIT"]


class TestOfferFailure:
    def test_交易所拒單不能讓機器人停掉(self, fake_logger, fake_notifier, repository):
        """🔴 偏移量 0 能不能掛 FIX，官方文件沒講，上線才知道。拒了就回一般路徑，不是整台停下來。"""
        client = FakeClient(offer_error=FatalError("建立放貸掛單失敗：invalid rate"))
        engine = engine_for(fake_logger, fake_notifier, client, repository)
        engine.run_once()
        assert "交易所拒絕 FRR 單" in state_of(repository).reason
        stopped = [message for message in fake_notifier.sent if "FRR 實測結束" in message]
        assert stopped[0].endswith("——— 需人工介入")
        failed = repository.connection.execute(
            "SELECT status FROM loan_offers ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        assert failed == "failed"

        client.offer_error = None
        engine.run_once()
        assert client.offers[-1]["type"] == "LIMIT"

    def test_暫時性錯誤不算實測結束(self, fake_logger, fake_notifier, repository):
        client = FakeClient(offer_error=RetryableError("逾時"))
        with pytest.raises(RetryableError):
            engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert state_of(repository).stopped_at is None

    def test_餘額不足照一般路徑的處理(self, fake_logger, fake_notifier, repository):
        client = FakeClient(offer_error=SkipCycleError("融資錢包餘額不足"))
        with pytest.raises(SkipCycleError):
            engine_for(fake_logger, fake_notifier, client, repository).run_once()
        assert state_of(repository).stopped_at is None


class TestLeftoverOfferOnNormalPath:
    """實測停了但 FRR 單撤不掉（取消是非同步的）：一般路徑不能拿它的 rate 去比價。"""

    def test_一般路徑會撤掉它再掛一般單(self, fake_logger, fake_notifier, repository):
        client = FakeClient(balance=0.1, active_offers=[frr_offer()])
        BotEngine(fake_logger, fake_notifier, strategy(), client, repository).run_once()
        assert client.cancel_calls == 1
        assert [offer["type"] for offer in client.offers] == ["LIMIT"]

    def test_就算它回報的是很高的利率也不會被留下來(self, fake_logger, fake_notifier, repository):
        """rate 欄位如果回當下的 FRR（約 10.8%），「往下重掛不划算」那道門不能把它留在場上。"""
        offer = frr_offer()
        offer["rate"] = daily(10.8)
        client = FakeClient(balance=0.1, active_offers=[offer])
        BotEngine(fake_logger, fake_notifier, strategy(), client, repository).run_once()
        assert client.cancel_calls == 1
        assert [offer["type"] for offer in client.offers] == ["LIMIT"]
