# -*- coding: utf-8 -*-
"""逐筆成交資料層（2026-11-01，「放寬天期」研究）。只讀資料。

公開逐筆成交 [ID, MTS, AMOUNT, RATE, PERIOD]。實測（w1102/probe.py）：
  我們每一筆真實成交都能在這裡找到一模一樣的金額與利率，而且 **AMOUNT 是負的**
  → 負號＝「掛單被吃掉」。正號＝有人拿掛單去吃別人的買方掛單，跟我們的掛單無關。
所以「掛在 r 會不會被掃到」看的是**負號成交**，不是 K 線高點（K 線把兩種都算進去）。

記憶體：這台機器只有 7GB、機器人也在上面跑，所以用 array 不用 list of tuple。
"""
import bisect
import json
import os
import sqlite3
from array import array
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
H = 3_600_000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADES_DB = os.path.join(ROOT, "dl_trades", "trades.sqlite3")
SNAP = os.path.join(ROOT, "snap", "lending-latest.sqlite3")


def ms(y, m, d, hh=0, mi=0):
    return int(datetime(y, m, d, hh, mi, tzinfo=CST).timestamp() * 1000)


def fmt(t):
    return datetime.fromtimestamp(t / 1000, CST).strftime("%m-%d %H:%M:%S")


class Series:
    """單一天期、單一方向的成交序列（依時間排序）。"""

    __slots__ = ("mts", "rate", "amt", "hour_max", "hour_idx")

    def __init__(self):
        self.mts = array("q")
        self.rate = array("d")
        self.amt = array("d")
        self.hour_max = {}
        self.hour_idx = {}

    def add(self, t, r, a):
        self.mts.append(t)
        self.rate.append(r)
        self.amt.append(a)

    def finish(self):
        """建每小時索引：掃的時候整小時跳過，沒有 numpy 也夠快。"""
        hm, hi = {}, {}
        for i, (t, r) in enumerate(zip(self.mts, self.rate)):
            h = t // H
            if h not in hi:
                hi[h] = i
                hm[h] = r
            elif r > hm[h]:
                hm[h] = r
        self.hour_max, self.hour_idx = hm, hi

    def __len__(self):
        return len(self.mts)


def load_trades(periods=None, start=None, end=None):
    """回傳 ({period: Series} 負號成交, {period: Series} 正號成交)。負號的 amt 存絕對值。"""
    con = sqlite3.connect(f"file:{TRADES_DB}?mode=ro", uri=True)
    sql = "select mts, amount, rate, period from t"
    args, cond = [], []
    if start:
        cond.append("mts >= ?"); args.append(start)
    if end:
        cond.append("mts < ?"); args.append(end)
    if periods:
        cond.append(f"period in ({','.join(str(int(p)) for p in periods)})")
    if cond:
        sql += " where " + " and ".join(cond)
    sql += " order by mts, id"
    neg, pos = {}, {}
    for t, a, r, p in con.execute(sql, args):
        if a < 0:
            neg.setdefault(p, Series()).add(t, r, -a)
        else:
            pos.setdefault(p, Series()).add(t, r, a)
    for d in (neg, pos):
        for s in d.values():
            s.finish()
    con.close()
    return neg, pos


class FRR:
    """FRR 時間序列（日利率）。08-23 起用機器人的快照（每 10 分鐘），更早用公開 funding stats（× 365）。"""

    def __init__(self):
        self.t, self.v = [], []
        rows = []
        path = os.path.join(ROOT, "dl_stats", "a.json")
        if os.path.exists(path):
            for row in json.load(open(path)):
                if row[3]:
                    rows.append((row[0], row[3] * 365))
        con = sqlite3.connect(f"file:{SNAP}?mode=ro", uri=True)
        for cap, f in con.execute("select captured_at, frr from market_snapshots where frr is not null"):
            rows.append((int(datetime.fromisoformat(cap).timestamp() * 1000), f))
        con.close()
        rows.sort()
        self.t = [r[0] for r in rows]
        self.v = [r[1] for r in rows]

    def at(self, t):
        i = bisect.bisect_right(self.t, t) - 1
        return self.v[max(i, 0)]


def real_offers():
    """真金掛單的存活區間。回傳 [{posted, end, rate, period, amount, filled_at, position}]。

    end＝下一張掛單送出前（機器人先取消再掛）或成交當下；成交靠「同利率同天期、開倉時間落在區間內」配對。
    """
    con = sqlite3.connect(f"file:{SNAP}?mode=ro", uri=True)
    offers = [dict(zip(("created_at", "rate", "duration", "amount", "offer_id"), r)) for r in con.execute(
        "select created_at, rate, duration, amount, offer_id from loan_offers where status='submitted' order by created_at")]
    positions = [dict(zip(("position_id", "kind", "amount", "rate", "period", "opened_at", "closed_at"), r)) for r in con.execute(
        "select position_id, kind, amount, rate, period, opened_at, closed_at from funding_positions where opened_at is not null order by opened_at")]
    con.close()
    for p in positions:
        p["t"] = int(datetime.fromisoformat(p["opened_at"]).timestamp() * 1000)
    out = []
    for i, o in enumerate(offers):
        posted = int(datetime.fromisoformat(o["created_at"]).timestamp() * 1000)
        nxt = int(datetime.fromisoformat(offers[i + 1]["created_at"]).timestamp() * 1000) if i + 1 < len(offers) else ms(2026, 11, 1, 15)
        fills = [p for p in positions if posted - 2000 <= p["t"] < nxt and abs(p["rate"] - o["rate"]) < 2e-8 and p["period"] == o["duration"]]
        fill_t = min((p["t"] for p in fills), default=None)
        out.append({
            "posted": posted,
            "end": fill_t if fill_t else nxt,
            "rate": o["rate"],
            "period": o["duration"],
            "amount": o["amount"],
            "filled_at": fill_t,
            "fills": fills,
        })
    return out
