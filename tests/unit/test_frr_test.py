# -*- coding: utf-8 -*-
"""`core/frr_test.py`（D076 第三節）：判準先寫死，所以每一條都要釘住。"""

from datetime import datetime, timedelta

import pytest

from core import frr_test
from core.frr_test import FrrTestConfig, FrrTestState, decide_stop, fills_since
from utils import clock

TZ = clock.get_timezone()
START = datetime(2026, 11, 9, 12, 0, tzinfo=TZ)


def days(value):
    return START + timedelta(days=value)


def position(opened, closed=None, period=30, amount=348.0, kind="credit", position_id="1", rate=0.0003):
    return {
        "position_id": position_id,
        "amount": amount,
        "rate": rate,
        "period": period,
        "kind": kind,
        "opened_at": opened.isoformat(),
        "first_seen_at": opened.isoformat(),
        "closed_at": closed.isoformat() if closed else None,
    }


class TestConfig:
    def test_沒設定就是關的(self):
        assert FrrTestConfig.from_config({}).enabled is False

    def test_讀設定(self):
        got = FrrTestConfig.from_config(
            {"frr_test": {"enabled": True, "offer_type": "FRRDELTAVAR", "period": 60, "offset": 0.00001}}
        )
        assert got == FrrTestConfig(True, "FRRDELTAVAR", 60, 0.00001)

    @pytest.mark.parametrize(
        "section",
        [
            {"offer_type": "LIMIT"},
            {"offer_type": "FRRDELTAVAR", "offset": -0.00001},  # 官方文件：VAR 只能是正的
            {"period": 1},
            {"period": 121},
        ],
    )
    def test_寫錯就當場失敗不要帶著去掛真錢(self, section):
        with pytest.raises(ValueError):
            FrrTestConfig.from_config({"frr_test": section})

    def test_FIX可以是負的偏移(self):
        assert FrrTestConfig.from_config({"frr_test": {"offset": -0.00001}}).offset == -0.00001


class TestState:
    def test_存進去讀得回來(self):
        state = FrrTestState(started_at=START, stopped_at=days(3), reason="排不到")
        assert FrrTestState.from_json(state.to_json()) == state

    def test_還在跑的沒有停止時間(self):
        assert FrrTestState.from_json(FrrTestState(started_at=START).to_json()).stopped_at is None

    @pytest.mark.parametrize("raw", ["不是 JSON", '{"started_at": null}'])
    def test_壞掉要講出來(self, raw):
        with pytest.raises(ValueError):
            FrrTestState.from_json(raw)


class TestFillsSince:
    def test_排隊從實測開始或上一筆還回來算起(self):
        rows = [
            position(days(2), days(3), position_id="1"),
            position(days(7), days(7.5), position_id="2"),
        ]
        fills = fills_since(rows, 30, START)
        assert [fill.queue_hours for fill in fills] == [48.0, 96.0]
        assert [fill.hold_hours for fill in fills] == [24.0, 12.0]

    def test_實測開始之前的不算(self):
        """天期 30 的舊部位（D069 那一段）不能算進這次實測。"""
        assert fills_since([position(days(-30), days(-29))], 30, START) == []

    def test_別的天期不算(self):
        """天期 7 的部位收回之後才開始 FRR，那筆不是這個實測的成交。"""
        assert fills_since([position(days(1), days(2), period=7)], 30, START) == []

    def test_還借著的沒有持有時間(self):
        fill = fills_since([position(days(1))], 30, START)[0]
        assert fill.closed_at is None and fill.hold_hours is None

    def test_拆單併成一筆到最後一筆還回來(self):
        rows = [
            position(days(1), days(2), amount=150.0, position_id="1"),
            position(days(1) + timedelta(seconds=14), days(3), amount=198.0, position_id="2"),
        ]
        fills = fills_since(rows, 30, START)
        assert len(fills) == 1
        assert fills[0].closed_at == days(3)

    def test_拆單有一筆還借著就算還借著(self):
        rows = [
            position(days(1), days(2), amount=150.0, position_id="1"),
            position(days(1) + timedelta(seconds=14), None, amount=198.0, position_id="2"),
        ]
        assert fills_since(rows, 30, START)[0].closed_at is None

    def test_有雙胞胎的loan不重複算(self):
        rows = [
            position(days(1), days(2), position_id="1"),
            position(days(1), days(1.1), kind="loan", position_id="2"),
        ]
        assert len(fills_since(rows, 30, START)) == 1


class TestDecideStop:
    def fill(self, queue_days, hold_hours, opened=None):
        opened = opened or days(1)
        return frr_test.Fill(
            opened_at=opened,
            closed_at=opened + timedelta(hours=hold_hours),
            queue_hours=queue_days * 24,
            hold_hours=hold_hours,
        )

    def test_剛開始不停(self):
        assert decide_stop(START, days(1), [], days(0)) is None

    def test_掛滿10天沒成交就停(self):
        stop = decide_stop(START, days(10), [], days(0))
        assert stop.code == "queue_timeout"
        assert "排不到" in stop.summary
        assert not stop.action_required

    def test_差一點還不停(self):
        assert decide_stop(START, days(9.9), [], days(0)) is None

    def test_10月最長空窗167小時不會誤殺(self):
        """D076：少於 7 天就判是不公平的，10 天留了餘裕。"""
        assert decide_stop(START, START + timedelta(hours=167), [], days(0)) is None

    def test_掛單之後有成交過就不算排不到(self):
        """部分成交：剩下的那一點還在場上，但這張單已經證明排得到。"""
        fills = [frr_test.Fill(days(5), None, 120.0, None)]
        assert decide_stop(START, days(11), fills, days(0)) is None

    def test_連兩筆排隊久又持有短就提前停(self):
        fills = [self.fill(3, 23.9), self.fill(4, 2.0)]
        stop = decide_stop(START, days(20), fills, None)
        assert stop.code == "short_holds"
        assert not stop.action_required

    @pytest.mark.parametrize(
        "first, second",
        [((2.9, 2.0), (4, 2.0)), ((3, 24.0), (4, 2.0))],
        ids=["排隊不夠久", "持有夠長"],
    )
    def test_只要有一筆不是就不算提前停(self, first, second):
        stop = decide_stop(START, days(20), [self.fill(*first), self.fill(*second)], None)
        assert stop.code == "ready_to_judge"

    def test_判準的方向是對的(self):
        """🔴 D071／D072 的教訓：提前停要真的是不好的結果。
        排隊 3 天、持有 24 小時的利用率 25%，以 10.8% 算淨 2.3%，比天期 7 差。"""
        utilization = 24 / (72 + 24)
        assert utilization == 0.25
        assert utilization * 10.8 * 0.85 < 4.0

    def test_完成2筆就該判定了要人看(self):
        stop = decide_stop(START, days(20), [self.fill(1, 100), self.fill(1, 100)], None)
        assert stop.code == "ready_to_judge"
        assert stop.action_required

    def test_只完成1筆繼續跑(self):
        assert decide_stop(START, days(20), [self.fill(1, 100)], None) is None

    def test_還借著的不算完成(self):
        fills = [self.fill(1, 100), frr_test.Fill(days(10), None, 24.0, None)]
        assert decide_stop(START, days(20), fills, None) is None

    def test_滿45天該判定了(self):
        stop = decide_stop(START, days(45), [], None)
        assert stop.code == "ready_to_judge"
        assert "滿 45 天" in stop.summary
        assert decide_stop(START, days(44.9), [], None) is None
