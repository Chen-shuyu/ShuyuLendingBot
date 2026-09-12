# -*- coding: utf-8 -*-
"""`scripts/sync_earnings.py` 的單元測試（D069）。

🔴 **這支報告以前一條測試都沒有，而那正是問題所在。**

`sync_earnings.py` 是「唯一一條交易所自己說的錢」（D051）的出口，
但它的**排版**從來沒被驗過。於是 2026-09-06～09-12 之間發生了這件事：

1. `format_summary()` 只在呼叫端給了 `--principal` 時才印實得年化；
2. 而它**從來沒讀回** D065 落地的 `earnings_daily.principal_avg`；
3. 所以照 STATUS 寫的維運指令跑（不給 `--principal`），**什麼都不印**；
4. 於是人自己手算，用了「有入帳的天數」當分母，算出 **7.75%**
   ——誠實的數字是 **6.83%**。

👉 **教訓：「少印一行」比「印錯一行」更危險。** 印錯的會被看到；
少印的會被人用腦內算式補上，而腦內算式不會留下它用了什麼分母。

所以這一組釘的不是「算得對不對」，是**「該印的有沒有印出來」**。
"""

import sqlite3
from pathlib import Path

import pytest

from core import earnings
from scripts import sync_earnings


def _entry(mts, amount, balance):
    """一列**已經走完 `_parse_ledger()`** 的帳本利息（形狀同 `test_earnings.entry()`）。"""
    return {
        "id": "1",
        "currency": "USD",
        "wallet": "funding",
        "mts": mts,
        "amount": float(amount),
        "balance": float(balance),
        "description": "Margin Funding Payment on wallet funding",
    }


def _mts(year, month, day):
    from datetime import datetime, timedelta, timezone

    tz = timezone(timedelta(hours=8))
    # 09:30 CST——Bitfinex 大約這個時間結一次放貸利息（見 `core/earnings.py`）。
    return int(datetime(year, month, day, 9, 30, tzinfo=tz).timestamp() * 1000)


@pytest.fixture
def summary_三天有一天空白():
    """09-06、09-08 有入帳，09-07 沒有——曆日 3 天、入帳列數 2。"""
    return earnings.summarize(
        [
            _entry(_mts(2026, 9, 6), 0.08, 345.1),
            _entry(_mts(2026, 9, 8), 0.07, 345.2),
        ],
        currency="USD",
    )


class TestD069分母是曆日不是入帳列數:
    """🔴 **這是那個錯數字的本體。**

    利息按每筆單子的 24 小時結算點入帳，不是按日曆日，所以帳本會有空白日
    ——**而空白日與「那天真的沒賺」長得一模一樣**。
    """

    def test_報告會講明曆日與入帳列數是兩件事(self, summary_三天有一天空白):
        out = sync_earnings.format_summary(
            summary_三天有一天空白,
            None,
            "2026-09-06",
            capital={
                "value": 345.0,
                "days": 3,
                "first": "2026-09-06",
                "last": "2026-09-08",
            },
        )
        assert "分母是曆日" in out
        assert "共 3 天" in out
        assert "入帳列數" in out

    def test_有空白日就要出聲而且不依賴有沒有給本金(self, summary_三天有一天空白):
        """🔴 **以前這段躲在 `if principal:` 裡面。**

        空白日常常是最重要的訊號（沒借出去、或錢不在 funding 錢包），
        **它不該因為呼叫端沒給本金就消失**。
        """
        out = sync_earnings.format_summary(summary_三天有一天空白, None, "2026-09-06")
        assert "1 天完全沒有利息入帳" in out
        assert "不要拿「入帳列數」當分母" in out

    def test_曆日數含頭含尾(self, summary_三天有一天空白):
        """09-06 → 09-08 是 **3 天**，不是相減得到的 2 天。

        以前這裡是 `(last - start).days`，而同一個函式裡的空白日判斷用
        `elapsed + 1`——**同一份報告裡兩種天數**。差一天在 7 天窗上就是 14%。
        """
        out = sync_earnings.format_summary(
            summary_三天有一天空白,
            345.0,
            "2026-09-06",
        )
        assert "共 3 天" in out
        # 0.15 USD / 3 天 / 345 USD × 365 = 5.29%
        assert "5.29%" in out


class TestD069本金要自己讀回來:
    """D065 讓機器人把「已部署資金」寫進 `earnings_daily`，
    但**這支報告從來沒讀回來過**——STATUS 卻已經寫了「本金不必再手打了」。
    """

    @staticmethod
    def _db(tmp_path: Path, rows):
        path = tmp_path / "lending.sqlite3"
        connection = sqlite3.connect(str(path))
        connection.execute(
            "CREATE TABLE earnings_daily (date TEXT NOT NULL, currency TEXT NOT NULL,"
            " interest REAL NOT NULL DEFAULT 0, principal_avg REAL,"
            " updated_at TEXT NOT NULL, PRIMARY KEY (date, currency))"
        )
        connection.executemany(
            "INSERT INTO earnings_daily VALUES (?, 'USD', 0.07, ?, '2026-09-12T00:00:00+08:00')",
            rows,
        )
        connection.commit()
        connection.close()
        return path

    def test_讀回已部署資金的平均與天數(self, tmp_path):
        path = self._db(
            tmp_path,
            [("2026-09-10", 100.0), ("2026-09-11", 200.0), ("2026-09-12", 300.0)],
        )
        got = sync_earnings.load_deployed_capital(path, "USD", None)
        assert got["value"] == pytest.approx(200.0)
        assert got["days"] == 3
        assert got["first"] == "2026-09-10"
        assert got["last"] == "2026-09-12"

    def test_since_會把窗以外的列篩掉(self, tmp_path):
        path = self._db(
            tmp_path, [("2026-09-01", 100.0), ("2026-09-11", 300.0)]
        )
        got = sync_earnings.load_deployed_capital(path, "USD", "2026-09-10")
        assert got["value"] == pytest.approx(300.0)
        assert got["days"] == 1

    def test_全是NULL就回None而不是零(self, tmp_path):
        """**零會被當成「本金是 0」然後算出無限大的年化。**"""
        path = self._db(tmp_path, [("2026-09-10", None), ("2026-09-11", None)])
        assert sync_earnings.load_deployed_capital(path, "USD", None) is None

    def test_沒給principal也要印出實得年化(self, summary_三天有一天空白):
        """🔴 **這一條就是那個缺陷的驗收。**"""
        out = sync_earnings.format_summary(
            summary_三天有一天空白,
            None,
            "2026-09-06",
            capital={
                "value": 345.0,
                "days": 3,
                "first": "2026-09-06",
                "last": "2026-09-08",
            },
        )
        assert "實得年化" in out
        assert "機器人自己觀測的已部署資金" in out

    def test_principal_勝過觀測值(self, summary_三天有一天空白):
        """使用者明確說的話勝過我們自己觀測到的。"""
        out = sync_earnings.format_summary(
            summary_三天有一天空白,
            690.0,
            "2026-09-06",
            capital={
                "value": 345.0,
                "days": 3,
                "first": "2026-09-06",
                "last": "2026-09-08",
            },
        )
        assert "本金 690.00 USD" in out
        assert "本金是呼叫端給的" in out

    def test_兩者都沒有就要講明為什麼算不出來(self, summary_三天有一天空白):
        """**不可以默默不印**——那正是這一整組測試存在的理由。"""
        out = sync_earnings.format_summary(summary_三天有一天空白, None, "2026-09-06")
        assert "算不出實得年化" in out
        assert "不要自己拿合計去除入帳列數" in out

    def test_觀測天數少於期間要出聲(self, summary_三天有一天空白):
        out = sync_earnings.format_summary(
            summary_三天有一天空白,
            None,
            "2026-09-06",
            capital={
                "value": 345.0,
                "days": 1,
                "first": "2026-09-08",
                "last": "2026-09-08",
            },
        )
        assert "只有 1 天有觀測值，期間卻有 3 天" in out


class TestD069利用率分解要印出來:
    """帳本告訴你賺了多少，**但不告訴你為什麼**。這一段就是那個「為什麼」。"""

    @staticmethod
    def _position(amount, annual_pct, opened, closed):
        return {
            "amount": amount,
            "rate": annual_pct / 365 / 100,
            "opened_at": opened,
            "closed_at": closed,
            "currency": "USD",
        }

    def _capital(self):
        return {
            "value": 345.0,
            "days": 3,
            "first": "2026-09-06",
            "last": "2026-09-08",
        }

    def test_兩邊對不上就要說對不上(self, summary_三天有一天空白):
        """借滿整個窗、名目 9%：0.15 USD / 3 天 / 345 = 5.29%，
        而 1.00 × 9% × 0.85 = 7.65% ——**差 2.36pp，所以應該說對不上**。

        🔴 **這一條釘的是「它真的在比」，不是無條件印一個 ✅。**
        一個永遠說「對得上」的對帳段，跟沒有對帳段一樣
        ——那正是 D064／D068 那個 fail-open 家族的長相。
        """
        positions = [
            self._position(
                345.0, 9.0, "2026-09-06T00:00:00+08:00", "2026-09-09T00:00:00+08:00"
            )
        ]
        out = "\n".join(
            sync_earnings.format_utilization(
                summary_三天有一天空白, positions, "2026-09-06", self._capital()
            )
        )
        assert "資金利用率 **100.0%**" in out
        assert "金額加權名目年化 **9.00%**" in out
        assert "🔴" in out and "差 " in out

    def test_利用率掉下來就看得見(self, summary_三天有一天空白):
        """只借了窗的三分之一 → 利用率 33.3%。"""
        positions = [
            self._position(
                345.0, 9.0, "2026-09-06T00:00:00+08:00", "2026-09-07T00:00:00+08:00"
            )
        ]
        out = "\n".join(
            sync_earnings.format_utilization(
                summary_三天有一天空白, positions, "2026-09-06", self._capital()
            )
        )
        assert "資金利用率 **33.3%**" in out

    def test_沒有本金就整段不印(self, summary_三天有一天空白):
        """**分母沒有就不要猜**——猜一個出來，這一段就從觀測變成推論。"""
        positions = [
            self._position(
                345.0, 9.0, "2026-09-06T00:00:00+08:00", "2026-09-09T00:00:00+08:00"
            )
        ]
        assert (
            sync_earnings.format_utilization(
                summary_三天有一天空白, positions, "2026-09-06", None
            )
            == []
        )

    def test_有提醒名目不含沒成交的掛單(self, summary_三天有一天空白):
        """**沒成交的掛單不在名目裡**，它的代價算在利用率上
        ——不講清楚的話，會有人拿這個名目去對照「我掛了多少」。
        """
        positions = [
            self._position(
                345.0, 9.0, "2026-09-06T00:00:00+08:00", "2026-09-09T00:00:00+08:00"
            )
        ]
        out = "\n".join(
            sync_earnings.format_utilization(
                summary_三天有一天空白, positions, "2026-09-06", self._capital()
            )
        )
        assert "不是「掛單價」" in out
        assert "金額加權" in out
