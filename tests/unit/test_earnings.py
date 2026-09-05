# -*- coding: utf-8 -*-
"""`core/earnings.py` 的單元測試（P2-2）。

**測試資料是 2026-08-30 對正式帳號唯讀實打抄回來的**（B6／D027 的做法），
不是照官方文件編的——而這一次實打又抓到三件文件沒講的事，
所以 `REAL_LEDGER_ROWS` 存在的意義跟 `REAL_FUNDING_CREDIT` 一樣。

測試分三半：

1. **分類對不對**——尤其是「混進來的東西」有沒有被擋掉。
2. **兩個陷阱有沒有被擋住**：同一筆轉帳出現兩列、正負相反、掛在不同錢包，
   所以「加總」與「只取正數」**兩種做法都會算錯**。
3. **同一天多筆要先合併再寫**——`set_daily_earning()` 是覆蓋，
   但如果這裡沒先合併，同一天的兩筆會互相覆蓋，只留下最後一筆。
"""

import pytest

from core import earnings


# 🔴 **實打抄回來的四列，每一種各一列。** 欄位：
# 0=ID, 1=CURRENCY, **2=WALLET（官方文件標成 placeholder，實測是錢包名）**,
# 3=MTS, 4=None, 5=AMOUNT, 6=BALANCE, 7=None, 8=DESCRIPTION
# **數值全是字串**，與 `funding_credits` 同一族（D027）。
REAL_LEDGER_ROWS = [
    ['10525396780', 'USD', 'funding', '1788053421000', None, '0.04203999',
     '345.06379078', None, 'Margin Funding Payment on wallet funding'],
    ['10503927493', 'USD', 'funding', '1786873048000', None, '184.3',
     '344.30861413', None,
     'Transfer of 184.3 USD from wallet Exchange to Deposit on wallet funding'],
    ['10503927492', 'USD', 'exchange', '1786873048000', None, '-184.3', '0', None,
     'Transfer of 184.3 USD from wallet Exchange to Deposit on wallet exchange'],
    ['10451241455', 'USD', 'exchange', '1782139299000', None, '343.66370051',
     '343.66370051', None, 'Exchange 343.732447 UST for USD @ 0.9998 on wallet exchange'],
]


def entry(
    amount="0.04203999",
    wallet="funding",
    description="Margin Funding Payment on wallet funding",
    mts=1788053421000,
    balance="345.06379078",
):
    """一列**已經走完 `_parse_ledger()`** 的帳本（數值已轉型）。"""
    return {
        "id": "10525396780",
        "currency": "USD",
        "wallet": wallet,
        "mts": mts,
        "amount": float(amount),
        "balance": float(balance),
        "description": description,
    }


def parsed(rows=None):
    """把原始列轉成解析後的形狀，欄位對應與 `_parse_ledger()` 一致。"""
    rows = REAL_LEDGER_ROWS if rows is None else rows
    return [
        {
            "id": row[0],
            "currency": row[1],
            "wallet": row[2],
            "mts": int(row[3]),
            "amount": float(row[5]),
            "balance": float(row[6]),
            "description": row[8],
        }
        for row in rows
    ]


class Test分類:
    def test_利息(self):
        assert earnings.classify(entry()) == earnings.KIND_INTEREST

    def test_轉帳(self):
        assert (
            earnings.classify(
                entry(description="Transfer of 184.3 USD from wallet Exchange to Deposit")
            )
            == earnings.KIND_TRANSFER
        )

    def test_幣別兌換算其他(self):
        assert (
            earnings.classify(
                entry(description="Exchange 343.732447 UST for USD @ 0.9998 on wallet exchange")
            )
            == earnings.KIND_OTHER
        )

    def test_描述對了但錢包不對就不算利息(self):
        """**防的是陷阱 2**：光看描述會把別的錢包那一半也收進來。"""
        assert earnings.classify(entry(wallet="exchange")) == earnings.KIND_OTHER

    def test_沒有描述不會爆掉(self):
        assert earnings.classify({"description": None, "wallet": "funding"}) == earnings.KIND_OTHER
        assert earnings.classify({}) == earnings.KIND_OTHER


class Test兩個陷阱:
    """同一筆轉帳出現兩列、正負相反、掛在不同錢包上。"""

    def test_加總全部會算錯(self):
        """把 `amount` 全部加起來 → 343.71，而真正的利息是 0.042。**差了八千倍。**

        ⚠ 這一批裡兩筆轉帳剛好正負相消，所以誤差全部來自那筆幣別兌換
        ——**那是運氣，不是保護**：兩條腿都落在查詢區間內才會相消，
        只撈到其中一條的話（`--since` 切在中間就會發生）就不會。
        下一條測的正是那個情況。
        """
        全部加總 = sum(row["amount"] for row in parsed())
        只算利息 = earnings.summarize(parsed()).total_interest
        assert 全部加總 == pytest.approx(343.7057405)
        assert 只算利息 == pytest.approx(0.04203999)
        assert 全部加總 / 只算利息 > 8000

    def test_只撈到轉帳的其中一條腿就不會相消(self):
        """**這才是「加總」真正危險的地方。** 查詢區間切在兩條腿中間時，
        帳面上會多出一整筆轉帳金額，而它看起來就像一天賺了 184 USD。"""
        只有一條腿 = parsed([REAL_LEDGER_ROWS[0], REAL_LEDGER_ROWS[1]])
        assert sum(row["amount"] for row in 只有一條腿) == pytest.approx(184.34203999)
        assert earnings.summarize(只有一條腿).total_interest == pytest.approx(0.04203999)

    def test_只取正數也會算錯(self):
        """轉帳的正數那一半仍然會被收進來——**兩種偷懶法都不行**。"""
        正數加總 = sum(row["amount"] for row in parsed() if row["amount"] > 0)
        assert 正數加總 == pytest.approx(528.0057405)
        assert earnings.summarize(parsed()).total_interest == pytest.approx(0.04203999)

    def test_分類的數量都報出來(self):
        """擋掉了幾列要看得見——「混進別的東西」正是這支要擋的事。"""
        summary = earnings.summarize(parsed())
        assert summary.total_rows == 4
        assert summary.interest_rows == 1
        assert summary.transfer_rows == 2
        assert summary.other_rows == 1


class Test每日彙總:
    def test_同一天多筆要先相加(self):
        """🔴 **沒先合併的話，`set_daily_earning()` 是覆蓋，第二筆會蓋掉第一筆。**

        補入帳真的會發生，所以這一條不是假設性的。
        """
        同一天 = [
            entry(amount="0.05", mts=1788053421000),
            entry(amount="0.03", mts=1788055000000),
        ]
        days = earnings.daily_earnings(同一天)
        assert len(days) == 1
        assert days[0].interest == pytest.approx(0.08)
        assert days[0].entry_count == 2

    def test_收盤餘額取當天最後一筆(self):
        days = earnings.daily_earnings(
            [
                entry(amount="0.05", mts=1788053421000, balance="100.0"),
                entry(amount="0.03", mts=1788055000000, balance="100.03"),
            ]
        )
        assert days[0].closing_balance == pytest.approx(100.03)

    def test_依日期由舊到新(self):
        days = earnings.daily_earnings(
            [
                entry(mts=1788053421000),   # 08-30
                entry(mts=1787967016000),   # 08-29
            ]
        )
        assert [day.date for day in days] == ["2026-08-29", "2026-08-30"]

    def test_按CST切日(self):
        """Bitfinex 約 09:30 CST 結息。**時區不是細節**（D028）。"""
        days = earnings.daily_earnings([entry(mts=1788053421000)])
        assert days[0].date == "2026-08-30"

    def test_沒有時間戳的列跳過而不是當成今天(self):
        days = earnings.daily_earnings([entry(mts=None)])
        assert days == []


class Test實得年化:
    def test_算式(self):
        summary = earnings.summarize(parsed())
        # 0.04203999 ÷ 344.31 × 365 ÷ 15
        assert summary.realized_annual_pct(344.31, 15) == pytest.approx(
            0.04203999 / 344.31 * 365 / 15 * 100
        )

    def test_本金或天數不合理時不給數字(self):
        """**「算不出來」不可以印成 0%**——那會被讀成「這段完全沒賺」。"""
        summary = earnings.summarize(parsed())
        assert summary.realized_annual_pct(0, 15) is None
        assert summary.realized_annual_pct(344.31, 0) is None


class Test真實回應的形狀:
    """實打抄回來的那四列，本身就是一份規格。"""

    def test_九欄(self):
        for row in REAL_LEDGER_ROWS:
            assert len(row) == 9

    def test_第二欄是錢包不是placeholder(self):
        """官方文件把 `[2]` 標成 placeholder，**實測是錢包名稱**。
        照文件寫會丟掉唯一能分辨錢包的欄位。"""
        assert {row[2] for row in REAL_LEDGER_ROWS} == {"funding", "exchange"}

    def test_數值是字串(self):
        """與 `funding_credits` 同一族（D027 第 3 點的第四次現身）。"""
        for row in REAL_LEDGER_ROWS:
            assert isinstance(row[5], str)
            assert isinstance(row[3], str)

    def test_第四與第七欄真的是placeholder(self):
        for row in REAL_LEDGER_ROWS:
            assert row[4] is None
            assert row[7] is None


class Test解析器對得上真實回應:
    """`BitfinexClient._parse_ledger()` 吃真實列的結果。

    **與 `Test真實回應的形狀` 分開**：那一族講「交易所回什麼」，
    這一族講「我們把它讀成什麼」。兩者對不上時要分得出是哪一邊變了。
    """

    @staticmethod
    def _client():
        import logging

        from api.bitfinex_client import BitfinexClient

        return BitfinexClient({"bitfinex": {}}, logging.getLogger("test"), dry_run=True)

    def test_逐欄對應(self):
        row = self._client()._parse_ledger([REAL_LEDGER_ROWS[0]])[0]
        assert row["id"] == "10525396780"
        assert row["currency"] == "USD"
        assert row["wallet"] == "funding"
        assert row["mts"] == 1788053421000
        assert row["amount"] == pytest.approx(0.04203999)
        assert row["balance"] == pytest.approx(345.06379078)
        assert row["description"] == "Margin Funding Payment on wallet funding"

    def test_解析結果直接餵得進分類(self):
        """解析器與 `core/earnings.py` 之間不該再有一層轉換。"""
        rows = self._client()._parse_ledger(REAL_LEDGER_ROWS)
        summary = earnings.summarize(rows)
        assert summary.interest_rows == 1
        assert summary.total_interest == pytest.approx(0.04203999)

    def test_壞掉的一列不害整批失敗(self):
        """但一定要留下原始內容——否則就是「成交了卻沒人知道」的翻版（D026）。"""
        client = self._client()
        壞列 = ["only", "three", "cols"]
        rows = client._parse_ledger([壞列, REAL_LEDGER_ROWS[0]])
        assert len(rows) == 1
        assert rows[0]["id"] == "10525396780"


class TestD065推算毛利息:
    """帳本是錢（D051），這一支只是**對帳用的參考線**。

    🔴 **它存在的理由是「沒有任何東西在看帳本」**：2026-09-05 靠人眼發現
    `earnings_daily` 在 08-16／08-20／08-21／08-31 缺列，
    **而缺列與「那天真的沒賺」長得一模一樣**。
    """

    @staticmethod
    def _position(amount, annual_pct, hours, opened="2026-09-01T00:00:00+08:00"):
        from datetime import datetime, timedelta

        start = datetime.fromisoformat(opened)
        return {
            "amount": amount,
            "rate": annual_pct / 365 / 100,
            "opened_at": opened,
            "closed_at": (start + timedelta(hours=hours)).isoformat(),
        }

    def test_一筆借滿兩天的部位算得出合約利息(self):
        # 345 USD、年化 9%、借滿 48 小時 = 345 × 0.09 × 2/365
        position = self._position(345.0, 9.0, 48.0)
        assert earnings.expected_gross_interest([position]) == pytest.approx(
            345.0 * 0.09 * 2 / 365, rel=1e-9
        )

    def test_仍在生息中的部位以現在為止計算(self):
        """**下界**——而下界拿來跟已入帳的利息比，方向是保守的。"""
        from datetime import datetime, timedelta, timezone

        tz = timezone(timedelta(hours=8))
        now = datetime(2026, 9, 2, 0, 0, 0, tzinfo=tz)
        position = {
            "amount": 345.0,
            "rate": 9.0 / 365 / 100,
            "opened_at": "2026-09-01T00:00:00+08:00",
            "closed_at": None,
        }
        assert earnings.expected_gross_interest([position], now=now) == pytest.approx(
            345.0 * 0.09 / 365, rel=1e-9
        )

    def test_起算時間壞掉的列缺席而不是算成零(self):
        """與 `core/hold_time.py` 同一個約定：**算不出來就缺席，不要猜。**"""
        壞掉 = {"amount": 345.0, "rate": 0.00024, "opened_at": None, "first_seen_at": None}
        好的 = self._position(345.0, 9.0, 24.0)
        單獨 = earnings.expected_gross_interest([好的])
        assert earnings.expected_gross_interest([壞掉, 好的]) == pytest.approx(單獨)

    def test_持有時間為負的列被排除(self):
        壞掉 = {
            "amount": 345.0,
            "rate": 0.00024,
            "opened_at": "2026-09-02T00:00:00+08:00",
            "closed_at": "2026-09-01T00:00:00+08:00",
        }
        assert earnings.expected_gross_interest([壞掉]) == 0.0

    def test_空清單回零而不是爆炸(self):
        assert earnings.expected_gross_interest([]) == 0.0

    def test_抽成常數是量出來的而不是查來的(self):
        """🔴 **它只用在對帳，不參與任何定價決策**——利息上的常數乘數
        不改變 `r × P ÷ (W + P)` 的極大點。"""
        assert earnings.FUNDING_FEE_PCT == 15.0


class TestD065對帳的判讀:
    """**判讀那條參考線的方向，比那個數字本身重要。**"""

    class _Summary:
        def __init__(self, total, days=1):
            self.total_interest = total
            self.days = [object()] * days

    @staticmethod
    def _positions(gross_target):
        """造一組部位，讓推算毛利息剛好是 `gross_target`。"""
        return [
            {
                "amount": gross_target * 365 / 0.09 / 2,
                "rate": 0.09 / 365,
                "opened_at": "2026-09-01T00:00:00+08:00",
                "closed_at": "2026-09-03T00:00:00+08:00",
            }
        ]

    def _lines(self, net, gross):
        from scripts.sync_earnings import format_reconciliation

        return "\n".join(
            format_reconciliation(
                self._Summary(net), self._positions(gross), "2026-09-01"
            )
        )

    def test_落在參考線附近時說沒有明顯缺列(self):
        assert "沒有明顯缺列" in self._lines(0.85, 1.0)

    def test_明顯偏低時要講出兩種相反的可能(self):
        """🔴 **「缺了一天」與「推算算多了」的意思完全相反**，
        而這兩個數字分不出是哪一種——所以**兩種都要講，不要挑一個**。"""
        lines = self._lines(0.50, 1.0)
        assert "沒有入帳" in lines and "算多了" in lines

    def test_明顯偏高時指向部位沒記全而不是賺得比合約多(self):
        assert "部位沒被記全" in self._lines(1.05, 1.0)

    def test_沒有部位或沒有利息時整段不印(self):
        """**算不出來就不要印一個看起來像數字的東西。**"""
        from scripts.sync_earnings import format_reconciliation

        assert format_reconciliation(self._Summary(1.0), [], "2026-09-01") == []
        assert format_reconciliation(self._Summary(0.0, days=0), self._positions(1.0), None) == []
