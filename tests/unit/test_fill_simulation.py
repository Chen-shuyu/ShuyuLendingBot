# -*- coding: utf-8 -*-
"""`core/fill_simulation.py` 的單元測試（M2 第 2 步）。

第 1 步的測試問「模型會選什麼」，**這一份問「那個選擇值多少」**。分四半：

1. **成交規則算得對不對**（命中、右設限、中點約定）
2. **右設限有沒有被當成量測值**——這一半是重點。空等的下界一旦被當成
   「等了這麼久然後成交了」，回測就會憑空生出報酬。
3. **持有模型是不是無狀態的**——第一版不是，同一組設定先後跑出
   7.26% 與 6.70%，而兩個數字看起來都很正常。
4. **空等與空轉有沒有進分母**——`wait_report` 的 7.99% 就是漏了這一塊。

測試資料用真實量級（日利率 0.00015～0.00031 ≈ 年化 5.5%～11.5%），
不用 1／2／3 這種漂亮數字——D027 的教訓。
"""

import pytest

from core import fill_simulation as fs


def candles(highs, start_mts=1_788_000_000_000):
    return [
        {"mts": start_mts + index * 3_600_000, "high": high}
        for index, high in enumerate(highs)
    ]


class Test成交規則:
    def test_命中那根算等半根(self):
        """掃單落在該根之內，平均在中點——與 `estimate_wait()` 同一個約定。"""
        result = fs.simulate_fill(candles([0.00015, 0.00015, 0.00031]), 0, 0.00029)
        assert result.hit_index == 2
        assert result.wait_hours == pytest.approx(2.5)
        assert not result.censored

    def test_當下那根就命中就是等半小時(self):
        result = fs.simulate_fill(candles([0.00031, 0.00015]), 0, 0.00029)
        assert result.wait_hours == pytest.approx(0.5)

    def test_從中間起算(self):
        result = fs.simulate_fill(candles([0.00031, 0.00015, 0.00031]), 1, 0.00029)
        assert result.hit_index == 2
        assert result.wait_hours == pytest.approx(1.5)

    def test_剛好等於也算命中(self):
        """`>=` 不是 `>`：掃到我們的價位就是成交。"""
        result = fs.simulate_fill(candles([0.00029879]), 0, 0.00029879)
        assert not result.censored

    def test_越界直接拒絕(self):
        with pytest.raises(IndexError):
            fs.simulate_fill(candles([0.00015]), 5, 0.0002)


class Test右設限不可以被當成量測值:
    """空等的下界一旦被當成「等了這麼久然後成交了」，回測就會憑空生出報酬。"""

    def test_走到尾端沒命中就是右設限(self):
        result = fs.simulate_fill(candles([0.00015] * 6), 0, 0.00029)
        assert result.censored
        assert result.hit_index is None
        assert result.wait_hours == pytest.approx(6.0)

    def test_右設限不給實得年化(self):
        result = fs.simulate_fill(candles([0.00015] * 6), 0, 0.00029)
        assert result.realized_effective(48.0) is None

    def test_成交的才給實得年化(self):
        result = fs.simulate_fill(candles([0.00015, 0.00031]), 0, 0.00029)
        # r × P ÷ (W + P)，W = 1.5、P = 48
        assert result.realized_effective(48.0) == pytest.approx(
            0.00029 * 48 / (1.5 + 48)
        )

    def test_持有時間是零就是賺到零而不是算不出來(self):
        """**「借了但立刻還掉」與「還沒有結果」不是同一件事。**

        `None` 只留給右設限（不知道）。借出 0 小時的實得年化就是 0%，
        那是一個答案，不是缺一個答案。
        """
        result = fs.simulate_fill(candles([0.00031]), 0, 0.00029)
        assert result.realized_effective(0.0) == pytest.approx(0.0)


class Test持有模型必須無狀態:
    """第一版是有狀態的閉包，同一組設定先後跑出 7.26% 與 6.70%。"""

    def test_同一個實例重複呼叫同一個索引給同一個值(self):
        model = fs.empirical_hold([1.84, 45.08, 6.87])
        assert model(0.0002, 0) == model(0.0002, 0) == 1.84

    def test_索引循環(self):
        model = fs.empirical_hold([1.84, 45.08, 6.87])
        assert [model(0.0002, i) for i in range(4)] == [1.84, 45.08, 6.87, 1.84]

    def test_同一個實例跑兩次policy給同一個答案(self):
        """這正是第一版壞掉的地方——回測不能重跑出同一個數字就沒有意義。"""
        model = fs.empirical_hold([1.84, 45.08, 6.87])
        market = candles([0.00015, 0.00031] * 60)
        first = fs.run_policy(_策略(), market, hold_model=model)
        second = fs.run_policy(_策略(), market, hold_model=model)
        assert first.realized_annual_pct == second.realized_annual_pct

    def test_固定模型不看索引(self):
        model = fs.fixed_hold(48.0)
        assert model(0.0002, 0) == model(0.0002, 99) == 48.0

    def test_空樣本直接拒絕(self):
        with pytest.raises(ValueError):
            fs.empirical_hold([])


class _策略:
    """最小的假策略：永遠選同一個價位。

    **不用真的 `ExpectedValueStrategy`**——這一份測的是模擬器，
    把策略也綁進來的話，紅燈時分不出是誰壞了。
    """

    ev_min_candles = 0

    def __init__(self, rate=0.00029, period=2):
        self.offer_period = period
        self.rate = rate

    def choose_rate(self, candles):
        return self.rate


class _不掛單的策略(_策略):
    def choose_rate(self, candles):
        return None


class Test空等與空轉都要進分母:
    """`wait_report` 印的 7.99% 就是因為少了這一塊才偏樂觀。"""

    def test_不掛單的時間算空轉(self):
        outcome = fs.run_policy(
            _不掛單的策略(), candles([0.00015] * 10), hold_model=fs.fixed_hold(48.0)
        )
        assert outcome.cycles == []
        assert outcome.idle_hours == pytest.approx(10.0)
        assert outcome.realized_annual_pct == pytest.approx(0.0)

    def test_全程沒成交實得是零而不是None(self):
        """**「沒賺到」與「算不出來」不是同一件事。**"""
        outcome = fs.run_policy(
            _策略(rate=0.00099), candles([0.00015] * 20), hold_model=fs.fixed_hold(48.0)
        )
        assert len(outcome.cycles) == 1
        assert outcome.cycles[0].censored
        assert outcome.realized_annual_pct == pytest.approx(0.0)

    def test_右設限的循環不貢獻利息但佔時間(self):
        cycle = fs.Cycle(
            decided_index=0,
            rate=0.00029,
            wait_hours=20.0,
            hold_hours=None,
            censored=True,
            realized_effective=None,
        )
        assert cycle.interest_hours == 0.0
        assert cycle.occupied_hours == pytest.approx(20.0)

    def test_實得年化是時間加權(self):
        """`Σ(r × P) ÷ Σ(W + P)`，不是逐筆平均。"""
        market = candles([0.00031] + [0.00015] * 200)
        outcome = fs.run_policy(
            _策略(), market, hold_model=fs.fixed_hold(48.0)
        )
        filled = outcome.filled
        assert filled
        expected = (
            sum(c.rate * c.hold_hours for c in filled)
            / (
                sum(c.occupied_hours for c in outcome.cycles)
                + outcome.idle_hours
            )
            * 365
            * 100
        )
        assert outcome.realized_annual_pct == pytest.approx(expected)


class Test資金回來才重新選價:
    def test_循環之間不重疊(self):
        """每根 K 都重選一次會憑空多出很多次不可能發生的機會。"""
        market = candles([0.00031] * 300)
        outcome = fs.run_policy(_策略(), market, hold_model=fs.fixed_hold(48.0))
        indexes = [cycle.decided_index for cycle in outcome.cycles]
        assert indexes == sorted(indexes)
        for earlier, later in zip(outcome.cycles, outcome.cycles[1:]):
            assert later.decided_index >= earlier.decided_index + int(
                earlier.occupied_hours
            ) - 1

    def test_策略以為的P與實際持有是分開的(self):
        """D1 問的正是「模型的假設錯了會怎樣」，綁在一起就問不出來。"""
        market = candles([0.00031] + [0.00015] * 200)
        strategy = _策略()
        outcome = fs.run_policy(
            strategy,
            market,
            hold_model=fs.fixed_hold(11.61),
            assumed_hold_hours=48.0,
        )
        assert outcome.cycles[0].hold_hours == pytest.approx(11.61)
        # 旋鈕轉完要還原（同第 1 步的 `assumed_hold_hours`）
        assert strategy.offer_period == 2


class Test成交規則的驗收:
    def test_右設限的期間不列入對照(self):
        """右設限沒有「實際等待」可以對照，把下界當量測值是 D026 那一族。"""

        class _期間:
            def __init__(self, rate, hours, censored, started_at):
                self.rate, self.hours = rate, hours
                self.censored, self.started_at = censored, started_at

        from datetime import datetime, timedelta, timezone

        tz = timezone(timedelta(hours=8))
        start = datetime.fromtimestamp(1_788_000_000, tz)
        market = candles([0.00015, 0.00031], start_mts=1_788_000_000_000)
        validation = fs.validate_against_real_fills(
            [
                _期間(0.00029, 1.5, False, start),
                _期間(0.00029, 9.9, True, start),
            ],
            market,
        )
        assert len(validation.rows) == 1

    def test_總量比(self):
        assert fs.FillValidation(
            rows=[
                fs.FillValidationRow(None, 0.0002, actual_hours=4.0, simulated_hours=2.0),
                fs.FillValidationRow(None, 0.0002, actual_hours=6.0, simulated_hours=3.0),
            ]
        ).total_ratio() == pytest.approx(0.5)

    def test_解析度以下的樣本被分出來(self):
        validation = fs.FillValidation(
            rows=[
                fs.FillValidationRow(None, 0.0002, actual_hours=0.06, simulated_hours=0.0),
                fs.FillValidationRow(None, 0.0002, actual_hours=3.60, simulated_hours=3.91),
            ]
        )
        assert len(validation.comparable) == 2
        assert len(validation.above_resolution) == 1
