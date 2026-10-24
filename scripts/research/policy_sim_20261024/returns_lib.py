# -*- coding: utf-8 -*-
"""2026-10-24 報酬分析的共用函式（只讀 DB 快照，不碰正式環境）。

算法照 D072 第五節：
  ① 現行：入帳日落在窗內
  ② 對齊：入帳日 D 的利息算 D-1 賺的（賺錢窗 [s, e] 取入帳日 [s+1, e+1]）
  ③ 部位推算：利用率 × 名目 × 0.85（capital_utilization，金額加權）
"""
import sqlite3
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, "/workspace/projects/LendingBot/ShuyuLendingBot")

from core import earnings, hold_time  # noqa: E402
from utils import clock  # noqa: E402

TZ = clock.get_timezone()
import os
SNAP = os.environ.get("POLICY_SIM_SNAPSHOT", "snap/lending.sqlite3")  # 正式 DB 的唯讀副本（backup API）
FEE = (100 - earnings.FUNDING_FEE_PCT) / 100


def d(text):
    return datetime.strptime(text, "%Y-%m-%d").date()


def midnight(day):
    return datetime(day.year, day.month, day.day, tzinfo=TZ)


def load(snap=SNAP):
    con = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    ledger = {
        d(r["date"]): (float(r["interest"]), r["principal_avg"])
        for r in con.execute("SELECT * FROM earnings_daily WHERE currency='USD'")
    }
    positions = [dict(r) for r in con.execute("SELECT * FROM funding_positions WHERE currency='USD'")]
    con.close()
    return ledger, positions


def screen_project(positions):
    """專案現行的篩法（D057）：所有 loan 都丟。"""
    return hold_time.screen_positions(positions).kept


def screen_keep_orphans(positions):
    """只丟「有 credit 雙胞胎」的 loan（待改③的改法），孤兒 loan 留下。"""
    credits = [p for p in positions if str(p.get("kind") or "").lower() != "loan"]
    kept = list(credits)
    orphans = []
    for p in positions:
        if str(p.get("kind") or "").lower() != "loan":
            continue
        po = hold_time.parse_moment(p["opened_at"])
        twin = any(
            abs(float(c["amount"]) - float(p["amount"])) < 0.01
            and abs(float(c["rate"]) - float(p["rate"])) < 1e-9
            and abs((hold_time.parse_moment(c["opened_at"]) - po).total_seconds()) <= 300
            for c in credits
        )
        if not twin:
            kept.append(p)
            orphans.append(p)
    return kept, orphans


def ledger_sum(ledger, first, last):
    """入帳日落在 [first, last] 的利息合計。"""
    return sum(v[0] for k, v in ledger.items() if first <= k <= last)


def principal_mean(ledger, first, last):
    vals = [float(v[1]) for k, v in ledger.items() if first <= k <= last and v[1]]
    return sum(vals) / len(vals) if vals else None


def annual(interest, principal, days):
    return interest / principal * 365 / days * 100


def window(ledger, positions, s, e, now, principal_rule="aligned"):
    """賺錢窗 [s, e]（含頭含尾，曆日）。回傳三種算法與分解。"""
    days = (e - s).days + 1
    if principal_rule == "aligned":
        cap = principal_mean(ledger, s + timedelta(days=1), e + timedelta(days=1))
    else:
        cap = principal_mean(ledger, s, e)
    if cap is None:  # 窗內一列都沒有（全閒）→ 往前找最近一筆
        prior = [v[1] for k, v in sorted(ledger.items()) if k <= e + timedelta(days=1) and v[1]]
        cap = float(prior[-1])
    cur = ledger_sum(ledger, s, e)
    ali = ledger_sum(ledger, s + timedelta(days=1), e + timedelta(days=1))
    start = midnight(s)
    end = min(midnight(e + timedelta(days=1)), now)
    got = earnings.capital_utilization(positions, cap, start, end, now=now)
    util = got["utilization_pct"] if got else 0.0
    nominal = got["nominal_annual_pct"] if got else float("nan")
    eff_days = (end - start).total_seconds() / 86400
    # ③ 部位推算：窗內毛利息 × 0.85 ÷ 本金，分母用「真正涵蓋到的天數」
    gross = earnings.expected_gross_interest(positions, now=now, start=start, end=end)
    pos = gross * FEE / cap * 365 / eff_days * 100
    return {
        "s": s, "e": e, "days": days, "cap": cap,
        "util": util, "nominal": nominal,
        "cur": annual(cur, cap, days), "ali": annual(ali, cap, days), "pos": pos,
        "cur_usd": cur, "ali_usd": ali, "pos_usd": gross * FEE,
    }
