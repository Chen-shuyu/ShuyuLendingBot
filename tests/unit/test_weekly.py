# -*- coding: utf-8 -*-
"""`core/weekly.py`（D076）：每週對帳。

🔴 **對帳段最要緊的不是「對得上時說對得上」，是「對不上時會說對不上」**。
一個永遠通過的判準跟沒有判準一樣（D064／D068 的 fail-open 家族），所以每個判準都有反面的測試。

已知答案（D074 第九節，人手算過）：`tests/fixtures/week_20261025.json` 是 10-25～10-31 的真實資料，
帳本 4.08%、部位推算 3.96%、利用率 77.8%、名目 5.98%。
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from core import hold_time, tape as tape_module, weekly
from core.tape import HOUR_MS, PathSummary, build_tape
from utils import clock

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
TZ = clock.get_timezone()
NOW = datetime(2026, 11, 1, 19, 0, tzinfo=TZ)
FIRST = date(2026, 10, 25)
LAST = date(2026, 10, 31)
START_MS = weekly.to_ms(weekly.midnight(FIRST))
END_MS = weekly.to_ms(weekly.midnight(LAST) + timedelta(days=1))


def daily(annual_pct):
    return annual_pct / 36500


def moment(day, hour=0, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def iso(day, hour=0, minute=0):
    return moment(day, hour, minute).isoformat()


def ms(day, hour=0, minute=0):
    return weekly.to_ms(moment(day, hour, minute))


def position(position_id="1", amount=348.0, annual=6.0, period=2, opened=None, closed=None, kind="credit"):
    return {
        "position_id": position_id,
        "currency": "USD",
        "amount": amount,
        "rate": daily(annual),
        "period": period,
        "kind": kind,
        "opened_at": opened,
        "first_seen_at": opened,
        "closed_at": closed,
    }


def offer_row(created_at, annual=6.0, period=2, amount=348.0, status="submitted"):
    return {
        "created_at": created_at,
        "rate": daily(annual),
        "duration": period,
        "amount": amount,
        "status": status,
    }


def summary(net=4.0, low=3.5, high=4.5, util=80.0, nominal=6.0, fills=5.0):
    return PathSummary(net, low, high, util, nominal, fills)


def actual(earned=4.0, positions=4.0):
    return weekly.Actual(
        first=FIRST,
        last=LAST,
        days=7,
        capital=348.0,
        earned_usd=0.27,
        earned_pct=earned,
        position_pct=positions,
        utilization_pct=78.0,
        nominal_pct=6.0,
        ledger_rows=6,
    )


@pytest.fixture(scope="module")
def first_week():
    return json.loads((FIXTURES / "week_20261025.json").read_text(encoding="utf-8"))


class TestLatestCompletedWeek:
    @pytest.mark.parametrize(
        "now, expected",
        [
            (moment(date(2026, 11, 8), 18, 29), date(2026, 10, 25)),  # 週日 18:30 之前：入帳還沒同步
            (moment(date(2026, 11, 8), 18, 30), date(2026, 11, 1)),
            (moment(date(2026, 11, 9), 9, 0), date(2026, 11, 1)),  # 週一：週日沒跑到也補得上
            (moment(date(2026, 11, 14), 23, 59), date(2026, 11, 1)),  # 週六
            (moment(date(2026, 11, 1), 19, 0), date(2026, 10, 25)),
        ],
    )
    def test_週日1830才算上一週(self, now, expected):
        assert weekly.latest_completed_week(now) == expected

    def test_別的時區傳進來也照台灣時間算(self):
        utc = datetime(2026, 11, 8, 10, 31, tzinfo=clock.get_timezone("UTC"))  # = 18:31 CST
        assert weekly.latest_completed_week(utc) == date(2026, 11, 1)


class TestActualNumbers:
    def test_已知答案第一週(self, first_week):
        """D074 第九節手算的數字。**這條壞了就是算法壞了，不是測試要改。**"""
        kept = hold_time.screen_positions(first_week["positions"]).kept
        got = weekly.actual_numbers(first_week["earnings"], kept, FIRST, LAST, NOW)
        assert got.earned_pct == pytest.approx(4.08, abs=0.005)
        assert got.position_pct == pytest.approx(3.96, abs=0.005)
        assert got.utilization_pct == pytest.approx(77.8, abs=0.05)
        assert got.nominal_pct == pytest.approx(5.98, abs=0.005)
        assert got.capital == pytest.approx(348.09, abs=0.005)
        assert got.days == 7

    def test_帳本看哪天賺的(self):
        """週日入帳的算上週六賺的；這週日入帳的不算這週（D072）。"""
        rows = [
            {"date": "2026-10-25", "interest": 9.0, "principal_avg": 348.0},  # 10-24 賺的
            {"date": "2026-10-26", "interest": 0.05, "principal_avg": 348.0},  # 10-25 賺的
            {"date": "2026-11-01", "interest": 0.07, "principal_avg": 348.0},  # 10-31 賺的
            {"date": "2026-11-02", "interest": 9.0, "principal_avg": 348.0},  # 11-01 賺的
        ]
        got = weekly.actual_numbers(rows, [], FIRST, LAST, NOW + timedelta(days=2))
        assert got.earned_usd == pytest.approx(0.12)
        assert got.ledger_rows == 2

    def test_分母是曆日不是入帳列數(self):
        """D069 那個錯了一週的數字。"""
        rows = [{"date": "2026-10-26", "interest": 0.05, "principal_avg": 348.0}]
        got = weekly.actual_numbers(rows, [], FIRST, LAST, NOW)
        assert got.earned_pct == pytest.approx(0.05 / 348 * 365 / 7 * 100)

    def test_整週沒入帳就退回最近的本金(self):
        """整週閒著正是最需要報數字的時候（D073 第四節），不能因為沒有分母就算不出來。"""
        rows = [{"date": "2026-10-12", "interest": 0.05, "principal_avg": 347.0}]
        got = weekly.actual_numbers(rows, [], FIRST, LAST, NOW)
        assert got.capital == 347.0
        assert got.earned_pct == 0.0
        assert got.utilization_pct == 0.0
        assert got.nominal_pct is None

    def test_沒有任何本金紀錄就講清楚不猜(self):
        with pytest.raises(ValueError, match="不猜分母"):
            weekly.actual_numbers([{"date": "2026-10-26", "interest": 0.05, "principal_avg": None}], [], FIRST, LAST, NOW)

    def test_窗還沒結束時部位只算到現在(self):
        """同一個 `min(窗尾, 現在)`（D071 第五節①）：借滿到現在就是 100%。"""
        now = moment(date(2026, 10, 28), 12)
        rows = [{"date": "2026-10-26", "interest": 0.05, "principal_avg": 348.0}]
        positions = [position(opened=iso(date(2026, 10, 24)))]
        got = weekly.actual_numbers(rows, positions, FIRST, LAST, now)
        assert got.utilization_pct == pytest.approx(100.0)


class TestHoldSamples:
    def test_分天期而且照開倉時間排序(self):
        rows = [
            position("2", opened=iso(date(2026, 10, 3)), closed=iso(date(2026, 10, 3), 5)),
            position("1", opened=iso(date(2026, 10, 1)), closed=iso(date(2026, 10, 1), 2)),
            position("3", period=30, opened=iso(date(2026, 10, 2)), closed=iso(date(2026, 10, 2), 9)),
        ]
        got = weekly.hold_samples(hold_time.screen_positions(rows), moment(date(2026, 11, 1)))
        assert got == {2: [2.0, 5.0], 30: [9.0]}

    def test_還借著的不算(self):
        rows = [position(opened=iso(date(2026, 10, 1)), closed=None)]
        assert weekly.hold_samples(hold_time.screen_positions(rows), moment(date(2026, 11, 1))) == {}

    def test_窗之後開倉的不算(self):
        """補算過去的週不能用到未來的樣本。"""
        rows = [position(opened=iso(date(2026, 11, 2)), closed=iso(date(2026, 11, 2), 5))]
        assert weekly.hold_samples(hold_time.screen_positions(rows), moment(date(2026, 11, 1))) == {}

    def test_拆單只算一筆(self):
        closed = iso(date(2026, 10, 1), 12)
        rows = [
            position("1", amount=150.0, opened=iso(date(2026, 10, 1)), closed=closed),
            position("2", amount=198.0, opened=iso(date(2026, 10, 1)), closed=closed),
        ]
        got = weekly.hold_samples(hold_time.screen_positions(rows), moment(date(2026, 11, 1)))
        assert got == {2: [12.0]}

    def test_孤兒loan算但雙胞胎不算(self):
        rows = [
            position("1", opened=iso(date(2026, 10, 1)), closed=iso(date(2026, 10, 1), 12)),
            position("2", kind="loan", opened=iso(date(2026, 10, 1)), closed=iso(date(2026, 10, 1), 1)),
            position("3", kind="loan", period=30, opened=iso(date(2026, 10, 5)), closed=iso(date(2026, 10, 5), 2)),
        ]
        got = weekly.hold_samples(hold_time.screen_positions(rows), moment(date(2026, 11, 1)))
        assert got == {2: [12.0], 30: [2.0]}


class TestPickHolds:
    def test_自己的樣本夠就用自己的(self):
        holds, label = weekly.pick_holds({7: [1.0] * 10, 30: [2.0] * 20}, 7)
        assert holds == [1.0] * 10
        assert "天期 7 實測 10 筆" in label

    def test_不夠就先借比較長的天期(self):
        """D075 的「中」假設：天期 7 剛上線時的狀況。"""
        holds, label = weekly.pick_holds({2: [1.0] * 30, 7: [5.0], 30: [2.0] * 11}, 7)
        assert holds == [2.0] * 11
        assert "天期 7 只有 1 筆" in label and "借天期 30" in label

    def test_沒有更長的才借短的(self):
        holds, label = weekly.pick_holds({2: [1.0] * 30}, 7)
        assert holds == [1.0] * 30
        assert "借天期 2" in label

    def test_誰都不夠就用手上的並講出來(self):
        holds, label = weekly.pick_holds({7: [5.0, 6.0], 30: [2.0]}, 7)
        assert holds == [5.0, 6.0]
        assert "樣本少" in label

    def test_完全沒有樣本就假設借滿(self):
        holds, label = weekly.pick_holds({}, 7)
        assert holds == [168.0]
        assert "假設借滿" in label


class TestStrategyFor:
    def test_只蓋掉三個旋鈕而且不動到原本的設定(self):
        config = {"strategy": {"offer_period": 7, "minimum_rate": 0.1, "market_floor_pct": 0.85}}
        strategy = weekly.strategy_for(config, weekly.PREVIOUS_SETTING)
        assert strategy.offer_period == 2
        assert strategy.assumed_hold_hours == 12.0
        assert strategy.minimum_rate == 0.00013699
        assert strategy.market_floor_pct == 0.85
        assert config["strategy"]["offer_period"] == 7


def _strategy_config():
    return {
        "strategy": {
            "min_required_usd": 150,
            "min_loan_size_usd": 150,
            "spread_count": 1,
            "offer_period": 2,
            "market_floor_pct": 0.85,
            "min_trade_samples": 3,
            "trade_window_hours": 6,
            "ev_min_hits": 5,
            "ev_min_candles": 48,
            "ev_window_hours": 168,
            "candle_hours": 1.0,
            "minimum_rate": 0.00013699,
            "assumed_hold_hours": 12,
        }
    }


def _candles(end_hour, count=240, annual=6.5):
    return [
        {"mts": (end_hour - offset) * HOUR_MS, "high": daily(annual), "close": daily(annual)}
        for offset in range(count, 0, -1)
    ]


def _trades(end_ms, count=60, annual=7.0, period=2):
    return [(end_ms - 1000 * index, end_ms - 1000 * index, -1000.0, daily(annual), period) for index in range(1, count + 1)]


class TestHourlyPrices:
    """掛價直接走 `build_offer_plan()`：不另外實作，才不會跟線上那份分岔。"""

    HOUR = START_MS // HOUR_MS

    def _run(self, tape, candles, setting=weekly.PREVIOUS_SETTING, hours=2):
        return weekly.hourly_prices(
            weekly.strategy_for(_strategy_config(), setting),
            tape,
            candles,
            START_MS,
            START_MS + hours * HOUR_MS,
            348.0,
            lambda _moment: daily(10.8),
        )

    def test_跟正式環境的計畫一模一樣(self):
        tape = build_tape(_trades(START_MS), lambda _moment: None)
        candles = _candles(self.HOUR)
        prices = self._run(tape, candles, hours=1)
        strategy = weekly.strategy_for(_strategy_config(), weekly.PREVIOUS_SETTING)
        plans = strategy.build_offer_plan(348.0, daily(10.8), None, tape.trades_before(START_MS), candles)
        assert prices[self.HOUR] == plans[0].rate

    def test_不偷看這一小時之後的資料(self):
        """🔴 這一小時內才發生的成交與 K 線，都不能影響這一小時開頭的掛價。"""
        base = build_tape(_trades(START_MS), lambda _moment: None)
        spike = build_tape(
            _trades(START_MS) + [(START_MS + 5, START_MS + 5, -9_000_000.0, daily(40.0), 2)],
            lambda _moment: None,
        )
        candles = _candles(self.HOUR)
        later = candles + [{"mts": START_MS, "high": daily(40.0), "close": daily(40.0)}]
        assert self._run(base, candles, hours=1) == self._run(spike, later, hours=1)

    def test_K線與成交只看到當時有的那些(self):
        candles = _candles(self.HOUR + 1)  # 240 根，最後一根是這一小時本身
        tape = build_tape(_trades(START_MS), lambda _moment: None)
        seen = []
        strategy = weekly.strategy_for(_strategy_config(), weekly.PREVIOUS_SETTING)
        original = strategy.build_offer_plan

        def spy(capital, frr, book, trades, window):
            seen.append(window)
            return original(capital, frr, book, trades, window)

        strategy.build_offer_plan = spy
        weekly.hourly_prices(
            strategy, tape, candles, START_MS, START_MS + HOUR_MS, 348.0, lambda _moment: None
        )
        assert seen[0][-1]["mts"] == START_MS - HOUR_MS
        assert len(seen[0]) == 239

    def test_低於地板就是沒有計畫(self):
        """10 月 8% 地板那一段就是這樣閒掉的。"""
        tape = build_tape(_trades(START_MS, annual=5.0), lambda _moment: None)
        prices = self._run(tape, _candles(self.HOUR, annual=5.0), weekly.LEGACY_SETTING, hours=1)
        assert prices[self.HOUR] is None

    def test_同天期成交太少就是沒有計畫(self):
        """地雷④：同天期樣本不足，正式環境整輪不掛。"""
        tape = build_tape(_trades(START_MS, count=2), lambda _moment: None)
        assert self._run(tape, _candles(self.HOUR), hours=1)[self.HOUR] is None

    def test_別的天期的成交不算樣本(self):
        tape = build_tape(_trades(START_MS, period=30), lambda _moment: None)
        assert self._run(tape, _candles(self.HOUR), hours=1)[self.HOUR] is None

    def test_固定價每小時都有(self):
        prices = weekly.fixed_prices(8.0, START_MS, START_MS + 2 * HOUR_MS)
        assert prices == {self.HOUR: daily(8.0), self.HOUR + 1: daily(8.0)}


class TestRealOffers:
    def test_一張單活到下一張送出為止(self):
        rows = [offer_row(iso(FIRST, 1)), offer_row(iso(FIRST, 3))]
        offers = weekly.real_offers(rows, [], END_MS, END_MS)
        assert offers[0].until_ms == ms(FIRST, 3)
        assert offers[1].until_ms == END_MS

    def test_配上同利率同天期的部位(self):
        rows = [offer_row(iso(FIRST, 1), annual=6.0)]
        positions = [
            position("other", annual=9.0, opened=iso(FIRST, 2), closed=iso(FIRST, 3)),
            position("mine", annual=6.0, opened=iso(FIRST, 2), closed=iso(FIRST, 5)),
        ]
        offer = weekly.real_offers(rows, positions, END_MS, END_MS)[0]
        assert offer.filled_at_ms == ms(FIRST, 2)
        assert offer.hold_hours == 3.0

    def test_拆單用金額加權的持有(self):
        rows = [offer_row(iso(FIRST, 1))]
        positions = [
            position("1", amount=100.0, opened=iso(FIRST, 2), closed=iso(FIRST, 3)),
            position("2", amount=300.0, opened=iso(FIRST, 2), closed=iso(FIRST, 7)),
        ]
        offer = weekly.real_offers(rows, positions, END_MS, END_MS)[0]
        assert offer.hold_hours == pytest.approx((1 * 100 + 5 * 300) / 400)

    def test_還借著的持有算到現在(self):
        rows = [offer_row(iso(FIRST, 1))]
        positions = [position(opened=iso(FIRST, 2))]
        offer = weekly.real_offers(rows, positions, END_MS, ms(FIRST, 12))[0]
        assert offer.hold_hours == 10.0

    def test_沒送出去的單不算(self):
        rows = [offer_row(iso(FIRST, 1), status="failed"), offer_row(iso(FIRST, 2), status="dry_run")]
        assert weekly.real_offers(rows, [], END_MS, END_MS) == []

    def test_天期看掛單實際用最久的(self):
        rows = [offer_row(iso(FIRST, 0), period=2), offer_row(iso(FIRST, 4), period=7)]
        offers = weekly.real_offers(rows, [], ms(FIRST, 10), END_MS)
        used = weekly.periods_used(offers, START_MS, ms(FIRST, 10))
        assert used == {2: 4.0, 7: 6.0}

    def test_成交之後就不算在掛(self):
        rows = [offer_row(iso(FIRST, 0)), offer_row(iso(FIRST, 8))]
        positions = [position(opened=iso(FIRST, 1), closed=iso(FIRST, 7))]
        offers = weekly.real_offers(rows, positions, ms(FIRST, 8), END_MS)
        assert weekly.periods_used(offers, START_MS, ms(FIRST, 8)) == {2: 1.0}


class TestFrrOffers:
    """FRR 實測中的掛單（D076 第三節）：rate 是偏移量，配不上部位的利率。"""

    @staticmethod
    def _row(created_at, period=30):
        row = offer_row(created_at, annual=0.0, period=period)
        row["offer_type"] = "FRRDELTAFIX"
        return row

    def test_靠天期與時間配上部位真正的利率來自部位(self):
        positions = [position(annual=10.8, period=30, opened=iso(FIRST, 2), closed=iso(FIRST, 12))]
        offer = weekly.real_offers([self._row(iso(FIRST, 1))], positions, END_MS, END_MS)[0]
        assert offer.is_frr
        assert offer.filled_at_ms == ms(FIRST, 2)
        assert offer.hold_hours == 10.0
        assert offer.fill_rate == pytest.approx(daily(10.8))
        assert offer.filled_amount == 348.0

    def test_別的天期的部位配不上(self):
        positions = [position(annual=10.8, period=7, opened=iso(FIRST, 2), closed=iso(FIRST, 12))]
        offer = weekly.real_offers([self._row(iso(FIRST, 1))], positions, END_MS, END_MS)[0]
        assert offer.filled_at_ms is None

    def test_舊列沒有類型就是一般單(self):
        offer = weekly.real_offers([offer_row(iso(FIRST, 1))], [], END_MS, END_MS)[0]
        assert not offer.is_frr

    def test_FRR單不決定現行設定是哪個天期(self):
        """🔴 D076 第三節的對照組是天期 7；拿 FRR 的天期 30 去跑模型定價就比錯對象了。"""
        offers = weekly.real_offers([self._row(iso(FIRST, 1))], [], END_MS, END_MS)
        assert weekly.periods_used(offers, START_MS, END_MS) == {}
        config = {"strategy": {"offer_period": 7, "assumed_hold_hours": 12, "minimum_rate": 0.00013699}}
        setting = weekly.default_setting(config, [self._row(iso(FIRST, 1))], [], START_MS, END_MS, END_MS)
        assert setting.offer_period == 7

    def test_重播裡照實際算而且佔住資金(self):
        """逐筆規則管不到 FRR 單（D075），但錢借出去的那段不能再成交別的單。"""
        positions = [position(annual=10.8, period=30, opened=iso(FIRST, 2), closed=iso(FIRST, 12))]
        rows = [self._row(iso(FIRST, 1)), offer_row(iso(FIRST, 3), annual=6.0, period=7)]
        offers = weekly.real_offers(rows, positions, END_MS, END_MS)
        tape = build_tape([(1, ms(FIRST, 5), -1000.0, daily(7.0), 7)], lambda _moment: None)
        got = weekly.replay_real_offers(tape, offers, positions, START_MS, END_MS, 348.0, 10.0, END_MS)
        assert (got.fills, got.real_fills) == (0, 0)
        assert got.net_pct == pytest.approx(10 / (7 * 24) * 10.8 * 0.85, abs=1e-6)

    def test_實測中的週判準2與3不適用(self, first_week):
        """判準 2、3 比的是模型定的價，這幾週跑的不是它，比了只會一直響。"""
        rows = first_week["offers"] + [self._row(iso(date(2026, 10, 29), 5))]
        setting = weekly.make_setting(7, 12.0, 0.00013699)
        report = weekly.build_report(_inputs(first_week, offer_rows=rows, setting=setting))
        labels = [check.label for check in report.checks]
        assert "FRR 實測" in labels
        assert "判準 2 現行設定" not in labels
        assert "判準 3 上一版設定" not in labels
        assert report.lost_to_previous is None
        assert any("FRR 實測中" in caveat for caveat in report.caveats)
        assert not report.action_required
        frr_check = next(check for check in report.checks if check.label == "FRR 實測")
        assert "不看單週" in frr_check.detail

    def test_對照組不繼承週初的FRR部位(self, first_week):
        """週初那筆 FRR 部位不是天期 7 掛的。"""
        rows = [self._row(iso(FIRST - timedelta(days=1), 1))]
        positions = [
            position(annual=10.8, period=30, opened=iso(FIRST - timedelta(days=1), 2), closed=iso(LAST, 12))
        ]
        setting = weekly.make_setting(7, 12.0, 0.00013699)
        report = weekly.build_report(
            _inputs(first_week, offer_rows=rows, position_rows=positions, setting=setting)
        )
        assert report.current.net_pct < 1.0  # 不會憑空多一筆 10.8% 借滿一週


class TestDefaultSetting:
    CONFIG = {"strategy": {"offer_period": 7, "assumed_hold_hours": 12, "minimum_rate": 0.00013699}}

    def test_天期看這週實際用的不是設定檔(self):
        """🔴 週中才換設定、或補算過去的週，設定檔的天期都不是那一週跑的。"""
        rows = [offer_row(iso(FIRST, 0), period=2)]
        setting = weekly.default_setting(self.CONFIG, rows, [], START_MS, END_MS, END_MS)
        assert setting.offer_period == 2
        assert setting.assumed_hold_hours == 12.0
        assert setting.label == "天期 2、P12、地板 5%"

    def test_沒掛過單就退回設定檔(self):
        setting = weekly.default_setting(self.CONFIG, [], [], START_MS, END_MS, END_MS)
        assert setting.offer_period == 7


class TestReplay:
    """判準 1 的重播：只有成交規則是推的。"""

    CAPITAL = 348.0

    def _tape(self, rows):
        return build_tape(rows, lambda _moment: None)

    def _replay(self, tape, offers, positions, start=START_MS, end=END_MS, fallback=10.0):
        return weekly.replay_real_offers(
            tape, offers, positions, start, end, self.CAPITAL, fallback, END_MS
        )

    def test_規則對的話跟部位推算一樣(self):
        opened = ms(FIRST, 2)
        positions = [position(opened=iso(FIRST, 2), closed=iso(FIRST, 12))]
        rows = [offer_row(iso(FIRST, 1))]
        offers = weekly.real_offers(rows, positions, END_MS, END_MS)
        tape = self._tape([(1, opened, -1000.0, daily(6.1), 2)])
        got = self._replay(tape, offers, positions)
        hours = 7 * 24
        assert got.net_pct == pytest.approx(10 / hours * 6.0 * 0.85, abs=1e-6)
        assert got.utilization_pct == pytest.approx(10 / hours * 100)
        assert (got.fills, got.real_fills) == (1, 1)

    def test_週初帶進來的部位照實際算而且擋住後面的單(self):
        positions = [position(annual=9.0, opened=iso(FIRST - timedelta(days=1)), closed=iso(FIRST, 10))]
        rows = [offer_row(iso(FIRST, 1))]
        offers = weekly.real_offers(rows, positions, END_MS, END_MS)
        tape = self._tape([(1, ms(FIRST, 5), -1000.0, daily(7.0), 2)])
        got = self._replay(tape, offers, positions)
        assert got.fills == 0
        assert got.net_pct == pytest.approx(10 / (7 * 24) * 9.0 * 0.85, abs=1e-6)

    def test_週初之前就成交的單不重播(self):
        """它已經是帶進來的部位了，不能再成交一次。"""
        positions = [position(opened=iso(FIRST - timedelta(days=1)), closed=iso(FIRST, 1))]
        rows = [offer_row(iso(FIRST - timedelta(days=1), 0))]
        offers = weekly.real_offers(rows, positions, END_MS, END_MS)
        tape = self._tape([(1, ms(FIRST, 2), -1000.0, daily(7.0), 2)])
        assert self._replay(tape, offers, positions).fills == 0

    def test_規則多成交出來的用備援持有(self):
        rows = [offer_row(iso(FIRST, 1))]
        offers = weekly.real_offers(rows, [], END_MS, END_MS)
        tape = self._tape([(1, ms(FIRST, 2), -1000.0, daily(7.0), 2)])
        got = self._replay(tape, offers, [], fallback=24.0)
        assert (got.fills, got.real_fills) == (1, 0)
        assert got.utilization_pct == pytest.approx(24 / (7 * 24) * 100)


class TestCheckReplay:
    def test_差在門檻內就過(self):
        check = weekly.check_replay(actual(positions=4.0), weekly.Replay(3.6, 78.0, 5, 5))
        assert check.passed and not check.action_required

    def test_對不上就要喊紅色而且要人處理(self):
        check = weekly.check_replay(actual(positions=4.0), weekly.Replay(3.4, 60.0, 3, 5))
        assert check.level == weekly.LEVEL_CRITICAL
        assert check.action_required
        assert "成交規則" in check.detail
        assert "成交 3 次（實際 5 次）" in check.detail

    def test_偏高偏低都算(self):
        check = weekly.check_replay(actual(positions=4.0), weekly.Replay(4.6, 90.0, 6, 5))
        assert check.level == weekly.LEVEL_CRITICAL

    def test_負控制規則壞了判準真的會響(self, first_week):
        """🔴 拿真實的第一週，把後半週的成交弄不見（資料缺一段），判準 1 要響。

        正常情況每週都差 0.00pp，所以要確認它不是永遠通過。
        用同一份資料的真實版本會通過，這條才有意義。
        """
        kept = hold_time.screen_positions(first_week["positions"]).kept
        got = weekly.actual_numbers(first_week["earnings"], kept, FIRST, LAST, NOW)
        offers = weekly.real_offers(first_week["offers"], kept, END_MS, weekly.to_ms(NOW))

        # 用實際掛價組一份「每張單成交當下都有人掃過去」的成交紀錄。
        rows = []
        for index, offer in enumerate(offers):
            if offer.filled_at_ms is not None and offer.filled_at_ms >= START_MS:
                rows.append((index, offer.filled_at_ms, -1000.0, offer.rate * 1.01, offer.period))
        whole = build_tape(rows, lambda _moment: None)
        half = build_tape(
            [row for row in rows if row[1] < START_MS + (END_MS - START_MS) // 2],
            lambda _moment: None,
        )

        def replay(tape):
            return weekly.replay_real_offers(
                tape, offers, kept, START_MS, END_MS, got.capital, 24.0, weekly.to_ms(NOW)
            )

        assert weekly.check_replay(got, replay(whole)).passed
        assert weekly.check_replay(got, replay(half)).level == weekly.LEVEL_CRITICAL


class TestCheckCurrent:
    def test_差在門檻內就過(self):
        check = weekly.check_current(actual(earned=4.0), summary(net=3.1), summary(net=9.0), "現行")
        assert check.passed and "≤ 1.0" in check.detail

    def test_沒過但實際持有重跑對得上就是運氣不用人處理(self):
        """10-11、10-18 那兩週就是這樣：差 −2.49／−1.88pp，重跑差 −0.01／−0.20pp。"""
        check = weekly.check_current(actual(earned=0.11), summary(net=2.60), summary(net=0.12), "現行")
        assert check.passed
        assert not check.action_required
        assert "運氣" in check.detail and "運氣" in check.summary

    def test_重跑也對不上才要人處理(self):
        check = weekly.check_current(actual(earned=4.0), summary(net=6.0), summary(net=5.5), "現行")
        assert check.level == weekly.LEVEL_WARNING
        assert check.action_required
        assert "不是持有的運氣" in check.detail

    def test_實得高出模擬也算對不上(self):
        check = weekly.check_current(actual(earned=7.0), summary(net=4.0), summary(net=4.5), "現行")
        assert check.level == weekly.LEVEL_WARNING


class TestCheckPrevious:
    def test_輸不到門檻算打平(self):
        assert not weekly.lost_to_previous(actual(earned=4.0), summary(net=4.29))
        assert weekly.lost_to_previous(actual(earned=4.0), summary(net=4.31))

    def test_贏就過(self):
        check = weekly.check_previous(actual(earned=5.0), summary(net=4.0), "上一版", None)
        assert check.passed

    def test_只輸一週不用人處理(self):
        """單週的持有運氣很大（D076 第四節）。"""
        check = weekly.check_previous(actual(earned=4.0), summary(net=5.0), "上一版", False)
        assert check.passed and not check.action_required
        assert "要連續兩週" in check.detail

    def test_連續兩週輸才要人處理(self):
        check = weekly.check_previous(actual(earned=4.0), summary(net=5.0), "上一版", True)
        assert check.level == weekly.LEVEL_WARNING
        assert check.action_required
        assert "連續兩週" in check.detail

    def test_上週沒紀錄要講出來(self):
        check = weekly.check_previous(actual(earned=4.0), summary(net=5.0), "上一版", None)
        assert "上週沒有紀錄" in check.detail
        assert not check.action_required


class TestCheckLedger:
    def test_兩條路接近就過(self):
        assert weekly.check_ledger(actual(earned=4.08, positions=3.96)).passed

    def test_缺一列入帳要抓得到(self, first_week):
        """🔴 帳本缺列跟「那天真的沒賺」長得一模一樣（D065），靠部位推算才看得出來。"""
        kept = hold_time.screen_positions(first_week["positions"]).kept
        missing = [row for row in first_week["earnings"] if row["date"] != "2026-10-29"]
        got = weekly.actual_numbers(missing, kept, FIRST, LAST, NOW)
        check = weekly.check_ledger(got)
        assert check.level == weekly.LEVEL_WARNING
        assert check.action_required


class TestCheckBackup:
    def test_新鮮就過(self):
        assert weekly.check_backup((NOW - timedelta(hours=10)).isoformat(), NOW).passed

    def test_超過48小時要喊(self):
        check = weekly.check_backup((NOW - timedelta(hours=49)).isoformat(), NOW)
        assert check.level == weekly.LEVEL_WARNING and check.action_required
        assert "49 小時" in check.detail

    def test_沒有紀錄也要喊(self):
        """定時器自己沒跑的時候，這裡是唯一會出聲的地方（D076）。"""
        check = weekly.check_backup(None, NOW)
        assert check.level == weekly.LEVEL_WARNING and check.action_required


def _inputs(first_week, **overrides):
    """第一週的真實資料，配一份每張單成交當下都有人掃過去的成交紀錄。"""
    kept = hold_time.screen_positions(first_week["positions"]).kept
    offers = weekly.real_offers(first_week["offers"], kept, END_MS, weekly.to_ms(NOW))
    rows = _trades(START_MS, count=60, annual=7.0, period=2) + _trades(START_MS, count=60, annual=7.0, period=7)
    for index, offer in enumerate(offers):
        if offer.filled_at_ms is not None and offer.filled_at_ms >= START_MS:
            rows.append((10_000_000 + index, offer.filled_at_ms, -1000.0, offer.rate * 1.01, offer.period))
    tape = build_tape(rows, lambda _moment: None)
    candles = _candles(START_MS // HOUR_MS)
    values = dict(
        config=_strategy_config(),
        tape=tape,
        candles={2: candles, 7: candles},
        earning_rows=first_week["earnings"],
        position_rows=first_week["positions"],
        offer_rows=first_week["offers"],
        frr_at=lambda _moment: daily(10.8),
        first=FIRST,
        last=LAST,
        now=NOW,
        setting=weekly.PREVIOUS_SETTING,
        backup_last_ok_at=(NOW - timedelta(hours=15)).isoformat(),
    )
    values.update(overrides)
    return weekly.WeeklyInputs(**values)


class TestBuildReport:
    def test_第一週的已知答案走完整條路(self, first_week):
        report = weekly.build_report(_inputs(first_week))
        assert report.actual.earned_pct == pytest.approx(4.08, abs=0.005)
        assert report.actual.position_pct == pytest.approx(3.96, abs=0.005)
        assert report.replay.fills == report.replay.real_fills == 7
        assert report.replay.net_pct == pytest.approx(3.96, abs=0.05)
        assert report.periods == pytest.approx({2: report.periods[2]})

    def test_現行設定等於上一版時判準3不適用(self, first_week):
        report = weekly.build_report(_inputs(first_week))
        assert report.previous is None
        assert not [check for check in report.checks if "判準 3" in check.label]

    def test_現行設定不同時有判準3(self, first_week):
        setting = weekly.Setting("天期 7、P12、地板 5%", 7, 12.0, 0.00013699)
        report = weekly.build_report(_inputs(first_week, setting=setting))
        assert report.previous is not None
        assert [check for check in report.checks if "判準 3" in check.label]
        assert report.lost_to_previous is not None

    def test_D074對照組算到1101那週為止(self, first_week):
        assert weekly.build_report(_inputs(first_week)).legacy is not None
        later = _inputs(
            first_week,
            first=date(2026, 11, 8),
            last=date(2026, 11, 14),
            now=moment(date(2026, 11, 15), 19),
        )
        assert weekly.build_report(later).legacy is None

    def test_最好的固定價真的是格子裡最高的(self, first_week):
        report = weekly.build_report(_inputs(first_week))
        assert report.best_fixed_annual in weekly.FIXED_GRID_ANNUAL
        assert report.best_fixed.net_pct >= report.fixed_reference.net_pct

    def test_換過天期要講出來(self, first_week):
        rows = [offer_row(iso(FIRST, 0), period=7, annual=6.0)] + first_week["offers"]
        report = weekly.build_report(_inputs(first_week, offer_rows=rows))
        assert any("換過天期" in caveat for caveat in report.caveats)

    def test_呼叫端的注意事項會帶下去(self, first_week):
        report = weekly.build_report(_inputs(first_week, caveats=["逐筆成交沒有涵蓋到窗尾"]))
        assert "逐筆成交沒有涵蓋到窗尾" in report.caveats
        assert "逐筆成交沒有涵蓋到窗尾" in weekly.format_report(report)
        assert "逐筆成交沒有涵蓋到窗尾" in weekly.line_fields(report)["注意"]

    def test_等級取最嚴重的(self, first_week):
        report = weekly.build_report(_inputs(first_week, backup_last_ok_at=None))
        assert report.level == weekly.LEVEL_WARNING
        assert report.action_required
        report.checks.append(weekly.Check("x", weekly.LEVEL_CRITICAL, "d", "s", True))
        assert report.level == weekly.LEVEL_CRITICAL

    def test_紀錄存得進JSON而且有下週要用的欄位(self, first_week):
        setting = weekly.Setting("天期 7、P12、地板 5%", 7, 12.0, 0.00013699)
        report = weekly.build_report(_inputs(first_week, setting=setting))
        record = json.loads(json.dumps(report.to_record()))
        assert record["first"] == "2026-10-25"
        assert record["lost_to_previous"] in (True, False)
        assert record["earned_pct"] == pytest.approx(4.08, abs=0.005)


class TestFormats:
    def test_完整報告列出每個判準與模擬(self, first_week):
        text = weekly.format_report(weekly.build_report(_inputs(first_week)))
        for needle in ("週報 10-25～10-31", "帳本實得（正式）：4.08%", "判準 1 重播", "判準 2 現行設定", "備份", "固定 8%", "事後看最好的固定價"):
            assert needle in text

    def test_通知第一行就有結論(self, first_week):
        report = weekly.build_report(_inputs(first_week))
        report.checks = [check for check in report.checks if check.passed]
        assert weekly.line_headline(report) == "週報 10-25～10-31：實得 4.08%，判準都過"

    def test_有判準沒過第一行就要講是哪個(self, first_week):
        report = weekly.build_report(_inputs(first_week, backup_last_ok_at=None))
        assert "要看：" in weekly.line_headline(report)
        assert "備份" in weekly.line_headline(report)

    def test_通知欄位有數字(self, first_week):
        fields = weekly.line_fields(weekly.build_report(_inputs(first_week)))
        assert fields["實得"] == "帳本 4.08%／部位 3.96%"
        assert "77.8%" in fields["利用率"]
        assert "判準 1 重播" in fields
        assert "最好的固定價" in fields


class TestFirstWeekWithRealTape:
    """用真實的 `market_rate()` 語意釘住「最新 1 萬筆」：切片跟正式環境一樣。"""

    def test_切片與整份取最後一段的常態價相同(self):
        rows = [
            (index, START_MS - 20_000 + index, -100.0 - index, daily(5.0 + (index % 7) * 0.1), 2)
            for index in range(15_000)
        ]
        tape = build_tape(rows, lambda _moment: None)
        strategy = weekly.strategy_for(_strategy_config(), weekly.PREVIOUS_SETTING)
        moment_ms = START_MS - 5000 + 1
        expected = [
            {"mts": row[1], "amount": abs(row[2]), "rate": row[3], "period": row[4]}
            for row in rows
            if row[1] < moment_ms
        ][-10_000:]
        sliced = tape.trades_before(moment_ms, 10_000)
        assert len(sliced) == 10_000
        assert strategy.market_rate(sliced) == strategy.market_rate(expected)


def test_tape模組與weekly共用同一個小時定義():
    assert tape_module.HOUR_MS == HOUR_MS == 3_600_000
