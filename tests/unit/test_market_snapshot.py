# -*- coding: utf-8 -*-
"""`core/market_snapshot.py` 的單元測試。

這個模組產生的是**存下去就回不去**的資料：摘要一旦算錯，M2 回測工具會拿著
錯的數字當事實，而且沒有鄰行可以拆穿它。所以這裡驗的重點不是「有沒有回傳值」，
是**有損的地方有沒有自己講出來**（`truncated`、`span_minutes`），
以及**加權方式對不對**（金額加權 vs 每筆一票，D033 實測差到 3 個百分點）。
"""

import json

from core import market_snapshot


def book_level(rate, amount, period=2):
    return {"rate": rate, "period": period, "amount": amount}


def trade(rate, amount, mts, period=2):
    return {"rate": rate, "amount": amount, "mts": mts, "period": period}


def candle(mts, high, close=0.0002, low=0.0001, open_=0.0002, volume=1000.0):
    return {"mts": mts, "open": open_, "close": close, "high": high, "low": low,
            "volume": volume}


class TestSummarizeBook:
    def test_空簿子回None而不是零(self):
        """**「沒觀測到」跟「觀測到 0」是兩件事。** 回 0 會讓事後分析把一段
        沒有資料的期間讀成一段市場死掉的期間。"""
        assert market_snapshot.summarize_book(None) is None
        assert market_snapshot.summarize_book([]) is None

    def test_記下可見範圍的兩端(self):
        summary = market_snapshot.summarize_book(
            [book_level(0.00020, 100.0), book_level(0.00026, 300.0)]
        )

        assert summary["lowest_rate"] == 0.00020
        assert summary["highest_rate"] == 0.00026
        assert summary["total_amount"] == 400.0
        assert summary["levels"] == 2

    def test_檔數未達上限就不標截斷(self):
        summary = market_snapshot.summarize_book([book_level(0.0002, 100.0)])

        assert summary["truncated"] is False

    def test_檔數等於上限就標成截斷(self):
        """250 檔是 `get_funding_book()` 要的量。檔數剛好等於上限時，
        **簿子極可能還有沒看到的部分**——這正是 A2／A3 兩個 bug 的共同根因，
        少了這一欄，M2 會把截斷值當成真實深度讀。"""
        book = [
            book_level(0.0002 + index * 0.0000001, 100.0)
            for index in range(market_snapshot.BOOK_LEVEL_CAP)
        ]

        assert market_snapshot.summarize_book(book)["truncated"] is True

    def test_累積曲線最後一點等於總額(self):
        summary = market_snapshot.summarize_book(
            [book_level(0.0002, 100.0), book_level(0.0003, 300.0)]
        )
        curve = json.loads(summary["curve_json"])

        assert len(curve) == market_snapshot.BOOK_CURVE_POINTS
        assert curve[-1][1] == 400.0
        # 利率與累積金額都必須單調不減，否則「前面排了多少錢」讀出來會是負的。
        assert curve == sorted(curve)

    def test_曲線讀得出前面排了多少錢(self):
        """一半的錢在 0.0002、一半在 0.0003，所以曲線走到一半時利率仍是 0.0002。"""
        summary = market_snapshot.summarize_book(
            [book_level(0.0002, 500.0), book_level(0.0003, 500.0)]
        )
        curve = json.loads(summary["curve_json"])

        midpoint = curve[market_snapshot.BOOK_CURVE_POINTS // 2 - 1]
        assert midpoint[0] == 0.0002
        assert midpoint[1] == 500.0

    def test_天期分佈分開計(self):
        """D030 量到 86% 的供給擠在 2 天期，而不同天期的價格結構不同。"""
        summary = market_snapshot.summarize_book(
            [
                book_level(0.0002, 800.0, period=2),
                book_level(0.0003, 200.0, period=30),
            ]
        )

        assert json.loads(summary["period_totals_json"]) == {"2": 800.0, "30": 200.0}


class TestSummarizeTrades:
    def test_沒有成交回None(self):
        assert market_snapshot.summarize_trades([]) is None

    def test_金額加權中位數不同於每筆一票(self):
        """**這是 D033 的整段教訓濃縮成一條測試。** 三筆小額掛在高價、
        一筆大額掛在低價：每筆一票會說市場在 0.0003，而實際上七成的錢
        是在 0.0001 換手的。筆數衡量的是撮合的破碎程度，不是市場的規模。"""
        trades = [
            trade(0.0003, 10.0, 1_000),
            trade(0.0003, 10.0, 2_000),
            trade(0.0003, 10.0, 3_000),
            trade(0.0001, 1_000.0, 4_000),
        ]

        summary = market_snapshot.summarize_trades(trades)

        assert summary["rate_median"] == 0.0003
        assert summary["rate_weighted_median"] == 0.0001

    def test_記下樣本涵蓋多久(self):
        """**`span_minutes` 不是裝飾欄位。** 同一個時間點只是把取樣窗從 20 分鐘
        拉到 43 分鐘，常態價就從年化 8.75% 掉到 5.47%（D033 實測）——
        任何拿這一列去比較的分析，都得先看得到樣本窗有多長。"""
        summary = market_snapshot.summarize_trades(
            [trade(0.0002, 10.0, 0), trade(0.0002, 10.0, 30 * 60_000)]
        )

        assert summary["span_minutes"] == 30.0
        assert summary["latest_mts"] == 30 * 60_000

    def test_每個天期各算一個中位數(self):
        """天期溢價非常大（2026-08-16 實測同一小時內 2 天期 0.000261、
        30 天期 0.000319），混在一起算出來的數字不對應任何一個市場。"""
        summary = market_snapshot.summarize_trades(
            [
                trade(0.00026, 100.0, 1_000, period=2),
                trade(0.00032, 100.0, 2_000, period=30),
            ]
        )

        assert json.loads(summary["period_rates_json"]) == {"2": 0.00026, "30": 0.00032}
        assert json.loads(summary["period_counts_json"]) == {"2": 1, "30": 1}


class TestSummarizeCandles:
    def test_沒有K線回None(self):
        assert market_snapshot.summarize_candles([]) is None

    def test_記下high的分佈而不只是最新值(self):
        """`high` 是這個策略唯一在意的欄位：某根 K 的 high ≥ 掛單利率
        就等於那段時間我們會被掃到（D035）。"""
        candles = [candle(index * 3_600_000, high=0.0001 * (index + 1)) for index in range(4)]

        summary = market_snapshot.summarize_candles(candles)

        assert summary["count"] == 4
        assert summary["high_max"] == 0.0004
        assert summary["high_median"] == 0.00025

    def test_close取最新那根而不是最後一個元素(self):
        """K 線的排序由呼叫端保證，但這裡不假設它——順序一旦被誰動過，
        `close_latest` 會安靜地指到一根舊 K，而那種錯誤沒有任何一行會報出來。"""
        summary = market_snapshot.summarize_candles(
            [
                candle(2_000_000, high=0.0003, close=0.00029),
                candle(1_000_000, high=0.0002, close=0.00019),
            ]
        )

        assert summary["latest_mts"] == 2_000_000
        assert summary["close_latest"] == 0.00029
