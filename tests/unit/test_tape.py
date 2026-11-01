# -*- coding: utf-8 -*-
"""`core/tape.py`（D075／D076）：哪些成交真的掃過簿子、掛單什麼時候被吃到。

釘的重點是**兩個真實事件**（`tests/fixtures/tape_events_202610.json`）：

- **10-14**：K 線高點 11.09% 是 FRR 管道的大單，我們掛 10.95% 沒被吃。K 線規則在這裡算錯，
  這正是 D075 重寫引擎的理由。
- **10-18**：真的掃單，我們 347.73 USD @ 10.95% 在 15:51:44 成交。

其餘用合成資料釘規則的每一條邊界。整段規則與研究版的逐筆等價性已另外用 425 萬筆比對過
（分類 0 差異、成交 4,000 次隨機比對 0 差異、路徑 0 差異，見 D076 追記）。
"""

import json
from pathlib import Path

import pytest

from core import tape as tape_module
from core.tape import HOUR_MS, Carried, FrrSeries, build_tape, find_fill, simulate_path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
T0 = 1_792_000_000_000 - 1_792_000_000_000 % HOUR_MS  # 一個整點，數字本身沒有意義
FRR = 11.0 / 36500


def daily(annual_pct):
    return annual_pct / 36500


def trade(moment_offset_ms, amount, annual_pct, period=30, trade_id=None):
    moment = T0 + moment_offset_ms
    return (trade_id if trade_id is not None else moment, moment, amount, daily(annual_pct), period)


def constant_frr(_moment):
    return FRR


@pytest.fixture(scope="module")
def events():
    return json.loads((FIXTURES / "tape_events_202610.json").read_text(encoding="utf-8"))


class TestTrueEvents:
    """真實事件。**這兩條壞了，就是 D075 整個結論壞了。**"""

    OUR_RATE = 0.0003  # 10.95%

    def test_1014的FRR大單不算掃過簿子(self, events):
        frr = FrrSeries(events["frr"])
        tape = build_tape([tuple(row) for row in events["event_1014"]], frr.at)
        rows = events["event_1014"]

        # 900 萬、1,843 萬那些全進 FRR 管道，真掃單最高只到 10.585%。
        assert max(tape.frr_channel[30].amount) == pytest.approx(18_432_240.65)
        assert 9_000_000.0 in tape.frr_channel[30].amount
        assert max(tape.clean[30].rate) * 36500 < 10.6

        fill, _ = find_fill(tape.evidence(30), self.OUR_RATE, rows[0][1], rows[-1][1] + 1, 347.88)
        assert fill is None

    def test_不分FRR管道就會在1014提早成交(self, events):
        """負控制：這就是 K 線規則的盲點。**同一批資料，分類拿掉就算錯。**"""
        rows = events["event_1014"]
        blind = build_tape([tuple(row) for row in rows], lambda _moment: None)
        fill, accumulated = find_fill(
            blind.evidence(30), self.OUR_RATE, rows[0][1], rows[-1][1] + 1, 347.88
        )
        assert fill == 1_791_993_427_000  # 10-14 23:57:07
        assert accumulated == pytest.approx(9_000_000.0)

    def test_1018真的掃單在實際成交後幾秒內算成交(self, events):
        """實際開倉 15:51:44；規則只看「比我們貴的」，所以是 15:51:48，晚 4 秒。"""
        frr = FrrSeries(events["frr"])
        rows = events["event_1018"]
        tape = build_tape([tuple(row) for row in rows], frr.at)
        assert not tape.frr_channel  # 一路爬上來的階梯，沒有被誤判
        fill, _ = find_fill(tape.evidence(30), self.OUR_RATE, rows[0][1], rows[-1][1] + 1, 347.73)
        assert fill == 1_792_309_908_000  # 15:51:48

    def test_我們的成交在公開資料裡一模一樣而且是負號(self, events):
        """D075 第二節第 1 點：整個規則的起點。"""
        ours = [
            row
            for row in events["event_1018"]
            if row[2] == -347.73 and row[3] == self.OUR_RATE and row[4] == 30
        ]
        assert len(ours) == 1
        assert ours[0][1] == 1_792_309_904_000  # 15:51:44


class TestClassification:
    def test_正號不算掃過簿子(self):
        tape = build_tape([trade(0, 5000.0, 6.0)], constant_frr)
        assert 30 in tape.positive
        assert 30 not in tape.clean and 30 not in tape.frr_channel

    def test_FRR帶以下一律算真掃單(self):
        """帶寬 0.30pp：10.69% 離 FRR 11% 夠遠，不用看階梯。"""
        tape = build_tape([trade(0, -9_000_000.0, 10.69)], constant_frr)
        assert len(tape.clean[30]) == 1

    def test_帶內沒有階梯就是FRR管道(self):
        tape = build_tape([trade(0, -9_000_000.0, 10.98)], constant_frr)
        assert len(tape.frr_channel[30]) == 1
        assert 30 not in tape.clean

    def test_帶內有連續階梯就是真掃單(self):
        tape = build_tape(
            [trade(0, -1000.0, 10.60), trade(1000, -1000.0, 10.80), trade(2000, -1000.0, 11.05)],
            constant_frr,
        )
        assert len(tape.clean[30]) == 3
        assert not tape.frr_channel

    def test_階梯落差超過門檻接不起來(self):
        """10-14 的 FRR 大單前面差 0.44～0.87pp；真掃單差 0.01～0.05pp。"""
        tape = build_tape([trade(0, -1000.0, 10.69), trade(1000, -1000.0, 11.00)], constant_frr)
        assert len(tape.frr_channel[30]) == 1
        assert tape.frr_channel[30].rate[0] == pytest.approx(daily(11.00))

    def test_階梯超過30秒就斷了(self):
        tape = build_tape(
            [trade(0, -1000.0, 10.68), trade(30_001, -1000.0, 10.80)], constant_frr
        )
        assert len(tape.frr_channel[30]) == 1
        ok = build_tape([trade(0, -1000.0, 10.68), trade(30_000, -1000.0, 10.80)], constant_frr)
        assert not ok.frr_channel

    def test_別的天期的成交不算階梯(self):
        """第一版看任何天期，10-14 那批就被別的天期碰巧的成交放行了。"""
        tape = build_tape(
            [trade(0, -1000.0, 10.80, period=120), trade(1000, -9_000_000.0, 10.90, period=30)],
            constant_frr,
        )
        assert len(tape.frr_channel[30]) == 1

    def test_FRR管道自己不能當階梯(self):
        """第二筆 FRR 大單不能踩著第一筆上去，否則一批裡只有第一筆會被抓到。"""
        tape = build_tape(
            [trade(0, -9_000_000.0, 10.95), trade(1000, -18_000_000.0, 11.00)], constant_frr
        )
        assert len(tape.frr_channel[30]) == 2

    def test_FRR每小時才重讀一次(self):
        seen = []

        def frr_at(moment):
            seen.append(moment)
            return FRR

        build_tape(
            [trade(0, -1.0, 5.0), trade(1000, -1.0, 5.0), trade(HOUR_MS + 5, -1.0, 5.0)], frr_at
        )
        assert seen == [T0, T0 + HOUR_MS + 5]

    def test_沒有FRR資料時全部當真掃單(self):
        tape = build_tape([trade(0, -9_000_000.0, 11.0)], lambda _moment: None)
        assert len(tape.clean[30]) == 1

    def test_非正的利率整筆略過(self):
        """同 `get_recent_trades()`。"""
        tape = build_tape([trade(0, -1.0, 0.0), trade(1, 1.0, 0.0)], constant_frr)
        assert len(tape) == 0

    def test_輸入沒排序也照時間算(self):
        tape = build_tape(
            [trade(1000, -1000.0, 10.80), trade(0, -1000.0, 10.60)], constant_frr
        )
        assert not tape.frr_channel


class TestTradesBefore:
    def test_形狀同get_recent_trades而且金額取絕對值(self):
        tape = build_tape([trade(0, -1000.0, 6.0, period=2)], constant_frr)
        rows = tape.trades_before(T0 + 1)
        assert rows == [{"mts": T0, "amount": 1000.0, "rate": daily(6.0), "period": 2}]

    def test_不包含當下那一刻之後的成交(self):
        tape = build_tape([trade(0, -1.0, 6.0), trade(1000, -1.0, 6.0)], constant_frr)
        assert len(tape.trades_before(T0 + 1000)) == 1

    def test_只取最新的limit筆而且不分天期(self):
        """正式環境就是抓最新 1 萬筆（所有天期）。"""
        tape = build_tape(
            [trade(index, -1.0, 6.0, period=2 + index % 2) for index in range(5)], constant_frr
        )
        rows = tape.trades_before(T0 + 10, limit=2)
        assert [row["mts"] for row in rows] == [T0 + 3, T0 + 4]
        assert {row["period"] for row in rows} == {2, 3}


class TestFindFill:
    def _tape(self, rows):
        return build_tape(rows, lambda _moment: None)

    def test_只算高於掛價的成交(self):
        """同價位的排隊順序看不到，保守算沒輪到。"""
        tape = self._tape([trade(0, -1000.0, 6.0)])
        assert find_fill(tape.evidence(30), daily(6.0), T0, T0 + HOUR_MS, 348.0)[0] is None
        assert find_fill(tape.evidence(30), daily(5.99), T0, T0 + HOUR_MS, 348.0)[0] == T0

    def test_寬鬆模式等於也算(self):
        tape = self._tape([trade(0, -1000.0, 6.0)])
        assert find_fill(tape.evidence(30), daily(6.0), T0, T0 + HOUR_MS, 348.0, strict=False)[0] == T0

    def test_金額要累積到掛單金額(self):
        tape = self._tape(
            [trade(0, -200.0, 7.0), trade(1000, -100.0, 7.0), trade(2000, -100.0, 7.0)]
        )
        fill, accumulated = find_fill(tape.evidence(30), daily(6.0), T0, T0 + HOUR_MS, 348.0)
        assert fill == T0 + 2000
        assert accumulated == pytest.approx(400.0)

    def test_沒累積夠要把進度帶回去(self):
        tape = self._tape([trade(0, -200.0, 7.0), trade(HOUR_MS, -200.0, 7.0)])
        fill, accumulated = find_fill(tape.evidence(30), daily(6.0), T0, T0 + HOUR_MS, 348.0)
        assert fill is None and accumulated == pytest.approx(200.0)
        fill, _ = find_fill(
            tape.evidence(30), daily(6.0), T0 + HOUR_MS, T0 + 2 * HOUR_MS, 348.0, accumulated
        )
        assert fill == T0 + HOUR_MS

    def test_比掛單天期長的成交不算證據(self):
        """天期 30 的成交可能是天期 ≥ 30 的買方，吃不到天期 7 的單。"""
        tape = self._tape([trade(0, -1000.0, 7.0, period=30)])
        assert find_fill(tape.evidence(7), daily(6.0), T0, T0 + HOUR_MS, 348.0)[0] is None

    def test_比掛單天期短的成交算證據(self):
        """天期 2 的掃單照價格吃，一定先吃到更便宜的天期 7。"""
        tape = self._tape([trade(0, -1000.0, 7.0, period=2)])
        assert find_fill(tape.evidence(7), daily(6.0), T0, T0 + HOUR_MS, 348.0)[0] == T0

    def test_跨天期要合併排序再累積(self):
        tape = self._tape(
            [
                trade(0, -200.0, 7.0, period=7),
                trade(1000, -200.0, 7.0, period=2),
                trade(2000, -200.0, 7.0, period=7),
            ]
        )
        fill, _ = find_fill(tape.evidence(7), daily(6.0), T0, T0 + HOUR_MS, 348.0)
        assert fill == T0 + 1000

    def test_窗是左閉右開(self):
        tape = self._tape([trade(1000, -1000.0, 7.0)])
        assert find_fill(tape.evidence(30), daily(6.0), T0 + 1001, T0 + HOUR_MS, 348.0)[0] is None
        assert find_fill(tape.evidence(30), daily(6.0), T0, T0 + 1000, 348.0)[0] is None
        assert find_fill(tape.evidence(30), daily(6.0), T0 + 1000, T0 + 1001, 348.0)[0] == T0 + 1000

    def test_沒有證據不會爆炸(self):
        assert find_fill([], daily(6.0), T0, T0 + HOUR_MS, 348.0) == (None, 0.0)


class TestSimulatePath:
    CAPITAL = 348.0

    def _tape(self, rows):
        return build_tape(rows, lambda _moment: None)

    def _prices(self, annual_pct=6.0, hours=48):
        return {T0 // HOUR_MS + hour: daily(annual_pct) for hour in range(hours)}

    def test_成交之後持有再掛回去(self):
        tape = self._tape(
            [trade(1000, -1000.0, 7.0), trade(5 * HOUR_MS, -1000.0, 7.0)]
        )
        result = simulate_path(
            tape.evidence(30), self._prices(), [2.0], T0, T0 + 10 * HOUR_MS, self.CAPITAL
        )
        assert result.fills == 2
        assert result.utilization_pct == pytest.approx(40.0, abs=0.1)
        assert result.nominal_pct == pytest.approx(6.0)
        assert result.net_pct == pytest.approx(0.4 * 6.0 * 0.85, abs=0.01)

    def test_閒置算在分母裡(self):
        tape = self._tape([])
        result = simulate_path(
            tape.evidence(30), self._prices(), [2.0], T0, T0 + 10 * HOUR_MS, self.CAPITAL
        )
        assert result.fills == 0
        assert result.net_pct == 0.0
        assert result.nominal_pct is None

    def test_沒有計畫的小時手上沒單就空等(self):
        """地板擋掉的小時：沒單可掛，掃單來了也不算（這正是 8% 地板那兩週的樣子）。"""
        tape = self._tape([trade(1000, -1000.0, 7.0), trade(HOUR_MS + 1000, -1000.0, 7.0)])
        prices = self._prices()
        prices[T0 // HOUR_MS] = None
        result = simulate_path(tape.evidence(30), prices, [1.0], T0, T0 + 2 * HOUR_MS, self.CAPITAL)
        assert result.trades[0][0] == T0 + HOUR_MS + 1000

    def test_沒有計畫的小時場上的單留著(self):
        """同 `bot_engine`「本輪無新計畫，維持場上既有掛單」。"""
        tape = self._tape([trade(HOUR_MS + 1000, -1000.0, 7.0)])
        prices = self._prices()
        prices[T0 // HOUR_MS + 1] = None
        result = simulate_path(tape.evidence(30), prices, [1.0], T0, T0 + 3 * HOUR_MS, self.CAPITAL)
        assert result.trades[0][0] == T0 + HOUR_MS + 1000
        assert result.trades[0][1] == daily(6.0)

    def test_價差超過2pct才重掛而且排隊歸零(self):
        tape = self._tape([trade(1000, -200.0, 7.0), trade(HOUR_MS + 1000, -200.0, 7.0)])
        moved = self._prices()
        moved[T0 // HOUR_MS + 1] = daily(6.2)  # +3.2%：重掛，累積的 200 歸零
        result = simulate_path(tape.evidence(30), moved, [1.0], T0, T0 + 2 * HOUR_MS, self.CAPITAL)
        assert result.fills == 0

        small = self._prices()
        small[T0 // HOUR_MS + 1] = daily(6.05)  # +0.8%：不重掛，累積到 400
        result = simulate_path(tape.evidence(30), small, [1.0], T0, T0 + 2 * HOUR_MS, self.CAPITAL)
        assert result.fills == 1
        assert result.trades[0][1] == daily(6.0)

    def test_持有上限(self):
        tape = self._tape([trade(1000, -1000.0, 7.0)])
        result = simulate_path(
            tape.evidence(30), self._prices(), [100.0], T0, T0 + 48 * HOUR_MS, self.CAPITAL, cap_hours=2.0
        )
        assert result.trades[0][2] == 2.0

    def test_持有樣本輪流取而且可以換起點(self):
        tape = self._tape(
            [trade(1000, -1000.0, 7.0), trade(2 * HOUR_MS, -1000.0, 7.0), trade(4 * HOUR_MS, -1000.0, 7.0)]
        )
        result = simulate_path(
            tape.evidence(30), self._prices(), [1.0, 1.5], T0, T0 + 6 * HOUR_MS, self.CAPITAL, rotate=1
        )
        assert [row[2] for row in result.trades] == [1.5, 1.0, 1.5]

    def test_持有超過窗尾只算到窗尾(self):
        tape = self._tape([trade(0, -1000.0, 7.0)])
        result = simulate_path(
            tape.evidence(30), self._prices(), [100.0], T0, T0 + 10 * HOUR_MS, self.CAPITAL
        )
        assert result.utilization_pct == pytest.approx(100.0)

    def test_沒有持有樣本要講清楚(self):
        with pytest.raises(ValueError):
            simulate_path([], {}, [], T0, T0 + HOUR_MS, self.CAPITAL)


class TestCarried:
    """週初帶進來的部位：是事實，不是模型的結果（D076 追記）。"""

    CAPITAL = 348.0

    def test_利息算進去而且還回來才開始掛(self):
        tape = build_tape(
            [trade(1000, -1000.0, 7.0), trade(5 * HOUR_MS, -1000.0, 7.0)], lambda _moment: None
        )
        prices = {T0 // HOUR_MS + hour: daily(6.0) for hour in range(10)}
        carried = Carried(rate=daily(9.0), share=1.0, until_ms=T0 + 4 * HOUR_MS)
        result = simulate_path(
            tape.evidence(30), prices, [1.0], T0, T0 + 10 * HOUR_MS, self.CAPITAL, carried=carried
        )
        # 第一筆掃單發生在部位還借著的時候，不能算成交。
        assert result.fills == 1
        assert result.trades[0][0] == T0 + 5 * HOUR_MS
        assert result.utilization_pct == pytest.approx(50.0)
        assert result.net_pct == pytest.approx((9.0 * 4 + 6.0 * 1) / 10 * 0.85, abs=1e-6)

    def test_借過窗尾就整週都是它(self):
        carried = Carried(rate=daily(9.0), share=1.0, until_ms=T0 + 100 * HOUR_MS)
        result = simulate_path(
            [], {}, [1.0], T0, T0 + 10 * HOUR_MS, self.CAPITAL, carried=carried
        )
        assert result.utilization_pct == pytest.approx(100.0)
        assert result.net_pct == pytest.approx(9.0 * 0.85)

    def test_部分資金借出照比例算(self):
        carried = Carried(rate=daily(9.0) * 0.5, share=0.5, until_ms=T0 + 100 * HOUR_MS)
        result = simulate_path(
            [], {}, [1.0], T0, T0 + 10 * HOUR_MS, self.CAPITAL, carried=carried
        )
        assert result.utilization_pct == pytest.approx(50.0)
        assert result.nominal_pct == pytest.approx(9.0)


class TestAcrossStarts:
    CAPITAL = 348.0

    def test_平均與範圍(self):
        tape = build_tape([trade(HOUR_MS + 1000, -1000.0, 7.0)], lambda _moment: None)
        prices = {T0 // HOUR_MS + hour: daily(6.0) for hour in range(48)}
        summary = tape_module.across_starts(
            tape.evidence(30),
            prices,
            [1.0, 3.0],
            T0,
            T0 + 24 * HOUR_MS,
            self.CAPITAL,
            offsets_hours=[0, 1, 2],
        )
        # 第三個起跑點已經錯過那筆掃單。
        assert summary.low_pct == 0.0
        assert summary.high_pct > summary.net_pct > 0.0
        assert summary.fills == pytest.approx(2 / 3)

    def test_不輪替時每條路徑都從第一筆持有開始(self):
        tape = build_tape([trade(HOUR_MS + 1000, -1000.0, 7.0)], lambda _moment: None)
        prices = {T0 // HOUR_MS + hour: daily(6.0) for hour in range(48)}
        kept = tape_module.across_starts(
            tape.evidence(30),
            prices,
            [1.0, 3.0],
            T0,
            T0 + 24 * HOUR_MS,
            self.CAPITAL,
            offsets_hours=[0, 0],
            rotate_holds=False,
        )
        assert kept.low_pct == pytest.approx(kept.high_pct)

    def test_有帶入部位時起跑點固定只換持有(self):
        tape = build_tape([trade(5 * HOUR_MS, -1000.0, 7.0)], lambda _moment: None)
        prices = {T0 // HOUR_MS + hour: daily(6.0) for hour in range(24)}
        summary = tape_module.across_starts(
            tape.evidence(30),
            prices,
            [1.0, 3.0],
            T0,
            T0 + 24 * HOUR_MS,
            self.CAPITAL,
            offsets_hours=[0, 12],
            carried=Carried(rate=daily(9.0), share=1.0, until_ms=T0 + 4 * HOUR_MS),
        )
        # 起跑點若真的往後移 12 小時，會錯過那筆掃單；固定的話兩條都成交。
        assert summary.fills == 1.0
        assert summary.high_pct > summary.low_pct


class TestCollectPages:
    @staticmethod
    def _row(trade_id, moment):
        return (trade_id, moment, -1.0, 0.0002, 2)

    def test_換頁重複的那幾筆要去掉(self):
        pages = [
            [self._row(1, 100), self._row(2, 200), self._row(3, 300)],
            [self._row(3, 300), self._row(4, 400)],
        ]
        cursors = []

        def fetch(start, _end, _size):
            cursors.append(start)
            return pages.pop(0)

        rows = tape_module.collect_pages(fetch, 100, 1000, page_size=3)
        assert [row[0] for row in rows] == [1, 2, 3, 4]
        assert cursors == [100, 300]

    def test_不滿一頁就是最後一頁(self):
        calls = []

        def fetch(start, _end, _size):
            calls.append(start)
            return [self._row(1, 100)]

        assert len(tape_module.collect_pages(fetch, 100, 1000, page_size=3)) == 1
        assert len(calls) == 1

    def test_空頁就結束(self):
        assert tape_module.collect_pages(lambda *_: [], 100, 1000) == []

    def test_同一毫秒超過一頁不會卡死(self):
        pages = [
            [self._row(1, 100), self._row(2, 100)],
            [self._row(3, 101)],
        ]
        cursors = []

        def fetch(start, _end, _size):
            cursors.append(start)
            return pages.pop(0)

        rows = tape_module.collect_pages(fetch, 100, 1000, page_size=2)
        assert cursors == [100, 101]
        assert [row[0] for row in rows] == [1, 2, 3]

    def test_兩頁之間要停一下(self):
        """公開端點跟機器人共用 IP。"""
        pages = [[self._row(1, 100), self._row(2, 200)], [self._row(3, 300)]]
        pauses = []
        tape_module.collect_pages(
            lambda *_: pages.pop(0), 100, 1000, page_size=2, pause=lambda: pauses.append(1)
        )
        assert pauses == [1]


class TestFrrSeries:
    def test_取那一刻最新的值(self):
        frr = FrrSeries([(200, 0.2), (100, 0.1)])
        assert frr.at(150) == 0.1
        assert frr.at(200) == 0.2
        assert frr.at(500) == 0.2

    def test_比第一筆早就用第一筆(self):
        assert FrrSeries([(100, 0.1)]).at(50) == 0.1

    def test_沒有資料回None(self):
        assert FrrSeries([]).at(50) is None

    def test_最久空窗包含頭尾(self):
        frr = FrrSeries([(T0 + HOUR_MS, 0.1), (T0 + 2 * HOUR_MS, 0.1)])
        assert frr.longest_gap_hours(T0, T0 + 10 * HOUR_MS) == 8.0
        assert FrrSeries([]).longest_gap_hours(T0, T0 + 3 * HOUR_MS) == 3.0
