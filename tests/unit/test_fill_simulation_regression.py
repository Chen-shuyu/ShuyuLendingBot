# -*- coding: utf-8 -*-
"""迴歸釘子：成交模擬在**真實歷史**上必須算出已知的答案（M2 第 2 步）。

與 `test_fill_simulation.py` 的分工同第 1 步：那份測「機制對不對」（合成資料），
**這份測「數字對不對」，資料是 403 根真實 K 線**（約 16.8 天）。

## 這份釘的三件事

1. **成交規則的驗收**——模擬的等待對得上真實成交（總量比 0.93×）。
   **這是整個第 2 步能不能被信任的地基**：規則若對不上，上面的實得年化全是假的。
2. **D1 的方向**——策略假設 `P=48` 的實得年化，低於假設 `P` 較小的那些。
3. 🔴 **以及「這個方向不夠強，不足以拿來改參數」**——切半之後前半的結論
   **反過來**。這一條同樣被釘住，**免得日後只記得第 2 條。**

## 為什麼要釘第 3 條

這個專案有六個決策互相推翻的紀錄（D036），而每一次的形狀都一樣：
**一個時間切片上的結論被當成了通則。** 第 2 條讀起來很像「答案找到了」，
所以第 3 條必須跟它綁在同一個檔案裡，紅燈時一起被看到。
"""

import pytest

from core import fill_simulation as fs
from strategies.expected_value import ExpectedValueStrategy
from tests.unit.candles_full_history import (
    HIGHS_FULL_HISTORY,
    HISTORY_START_MTS,
    REAL_FILLS,
)

CONFIG = {
    "strategy": {
        "ev_window_hours": 168,
        "ev_min_hits": 5,
        "ev_min_candles": 48,
        "candle_hours": 1.0,
        "offer_period": 2,
        "minimum_rate": 0.0001,
    }
}


def history(highs=None):
    highs = HIGHS_FULL_HISTORY if highs is None else highs
    return [
        {"mts": HISTORY_START_MTS + index * 3_600_000, "high": high}
        for index, high in enumerate(highs)
    ]


def run(candles, assumed, hold_model=None):
    """**每次都建新的策略實例**：`choose_rate()` 會把「本輪」的評估結果留在
    成員上（D041 的那四個），共用實例等於讓上一組設定的殘留參與下一組。"""
    return fs.run_policy(
        ExpectedValueStrategy(CONFIG),
        candles,
        hold_model=hold_model or fs.empirical_hold(),
        assumed_hold_hours=assumed,
    )


class Test歷史的形狀:
    def test_根數與長度(self):
        assert len(history()) == 403
        assert len(history()) / 24 == pytest.approx(16.8, abs=0.05)


class TestD1的方向:
    """策略假設借滿 48 小時，而實測完成率只有 35.3%（D040）。"""

    def test_假設48比假設實測平均差(self):
        寬鬆 = run(history(), 48.0)
        嚴格 = run(history(), 16.93)
        assert 寬鬆.realized_annual_pct == pytest.approx(6.57, abs=0.02)
        assert 嚴格.realized_annual_pct == pytest.approx(7.26, abs=0.02)
        assert 嚴格.realized_annual_pct > 寬鬆.realized_annual_pct

    def test_假設48的成交率比較低(self):
        """掛得太高的代價之一是空掛——而空掛的時間一樣進分母。"""
        寬鬆 = run(history(), 48.0)
        assert 寬鬆.fill_rate < 1.0
        assert run(history(), 16.93).fill_rate == pytest.approx(1.0)

    def test_四種持有模型下方向都一致(self):
        """換掉「實際借多久」的假設，結論不該翻——翻了就代表它只是巧合。"""
        for hold in (
            fs.empirical_hold(),
            fs.fixed_hold(48.0),
            fs.fixed_hold(16.93),
            fs.fixed_hold(11.61),
        ):
            寬鬆 = run(history(), 48.0, hold)
            嚴格 = run(history(), 16.93, hold)
            assert 嚴格.realized_annual_pct > 寬鬆.realized_annual_pct

    def test_就算實際持有真的是48假設48仍不是最好的(self):
        """**這一條是最違反直覺的那個**：即使模型的世界觀完全成立
        （每筆都借滿 48 小時），假設一個較小的 `P` 仍然比較好。

        機制：假設較小的 `P` 讓策略更怕等待，而那正好補償了 `W` 被低估
        （D047 的乾旱回饋圈）。**兩個錯誤部分互相抵銷**——
        所以「把 48 改成實測值」不是一個安全的動作，它會拆掉其中一半。
        """
        寬鬆 = run(history(), 48.0, fs.fixed_hold(48.0))
        嚴格 = run(history(), 16.93, fs.fixed_hold(48.0))
        assert 寬鬆.realized_annual_pct == pytest.approx(7.27, abs=0.02)
        assert 嚴格.realized_annual_pct == pytest.approx(7.61, abs=0.02)


class Test這個方向還不足以拿來改參數:
    """🔴 **這一族與上一族同等重要，不要只記得上一族。**"""

    def test_切半之後前半的結論反過來(self):
        """前半說 48 比較好，後半說 16.93 比較好——**跨時段站不住**。"""
        前半 = history()[: len(HIGHS_FULL_HISTORY) // 2 + 168]
        後半 = history()[len(HIGHS_FULL_HISTORY) // 2 - 168 :]

        前半寬鬆 = run(前半, 48.0).realized_annual_pct
        前半嚴格 = run(前半, 16.93).realized_annual_pct
        後半寬鬆 = run(後半, 48.0).realized_annual_pct
        後半嚴格 = run(後半, 16.93).realized_annual_pct

        assert 前半寬鬆 > 前半嚴格, "前半應該是 48 較好——這正是不能拿去改參數的理由"
        assert 後半嚴格 > 後半寬鬆, "後半應該是 16.93 較好"

    def test_細掃出來的最佳值是雜訊(self):
        """相鄰幾列差 0.1～0.3 個百分點，而曲線不是單調的。

        **挑最高的那一列就是 `target_queue_usd` 的死法**（D032）：
        拿一個十幾天、十幾次循環的樣本去挑一個常數。
        """
        結果 = {
            假設: run(history(), float(假設)).realized_annual_pct
            for 假設 in (20, 18, 16, 14, 12, 10)
        }
        最佳 = max(結果, key=結果.get)
        最差 = min(結果, key=結果.get)
        # 整段區間的高低差很小——小到不足以在這個樣本數下分辨
        assert 結果[最佳] - 結果[最差] < 0.5
        # 而且不是單調的：14 比 16 好，但 12 又比 14 差
        assert 結果[14] > 結果[16]
        assert 結果[12] < 結果[14]

    def test_可重跑(self):
        """回測跑兩次必須同值，否則「這次比較好」永遠分不清是策略還是狀態殘留。

        第一版的 `empirical_hold()` 是有狀態的閉包，同一組設定先後跑出
        7.26% 與 6.70%——**兩個數字看起來都很正常**。
        """
        model = fs.empirical_hold()
        assert run(history(), 16.93, model).realized_annual_pct == pytest.approx(
            run(history(), 16.93, model).realized_annual_pct
        )


class Test成交規則對得上真實成交:
    """🔴 **這一族是整個第 2 步的地基。**

    上面每一個實得年化都站在「`high >= rate` 就會成交」這條規則上。
    規則若對不上真實成交，那些數字全部是假的——而它們看起來會完全正常。
    """

    @staticmethod
    def _spells():
        """把 fixture 還原成 `validate_against_real_fills()` 吃的形狀。"""
        from datetime import datetime

        class _期間:
            censored = False

            def __init__(self, started_at, rate, hours):
                self.started_at = datetime.fromisoformat(started_at)
                self.rate = rate
                self.hours = hours

        return [_期間(*row) for row in REAL_FILLS]

    def test_十二筆全部比對得到(self):
        validation = fs.validate_against_real_fills(self._spells(), history())
        assert len(validation.comparable) == 12

    def test_總量比(self):
        """**要讀的是這個數字**，不是逐筆倍數。

        對照組：策略自己的 `estimate_wait()` 在同一批樣本上是 4.25 倍高估
        （D045）。**模擬器準了一個數量級**，這是它能拿來當裁判的理由。
        """
        validation = fs.validate_against_real_fills(self._spells(), history())
        assert validation.total_ratio() == pytest.approx(0.93, abs=0.01)

    def test_扣掉解析度以下的樣本仍然對得上(self):
        """12 筆裡有 7 筆的實際等待不到一根 K，逐筆倍數在那裡讀不出意思。"""
        validation = fs.validate_against_real_fills(self._spells(), history())
        above = validation.above_resolution
        assert len(above) == 5
        assert validation.total_ratio(above) == pytest.approx(0.95, abs=0.01)

    def test_模擬的成交偏快而不是偏慢(self):
        """`high >= rate` 沒說掃掉的量足夠輪到我們那 345 USD，
        所以模擬一定偏樂觀。**方向要被釘住**——哪天它變成偏慢，
        代表規則或資料出了事。"""
        validation = fs.validate_against_real_fills(self._spells(), history())
        assert validation.total_ratio() < 1.0
