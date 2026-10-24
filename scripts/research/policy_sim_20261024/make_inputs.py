# -*- coding: utf-8 -*-
"""產生 sim.py 需要的兩份輸入：hold_samples.json、market_rate_by_hour.json（2026-10-24 當天在指令列跑的版本）。

用法：在工作目錄（有 snap/lending.sqlite3）執行 `python3 make_inputs.py`。
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from returns_lib import load, screen_keep_orphans  # noqa: E402
from core import hold_time  # noqa: E402

H = 3_600_000
SNAP = os.environ.get("POLICY_SIM_SNAPSHOT", "snap/lending.sqlite3")

# ① 真實持有時間（篩掉有 credit 雙胞胎的 loan，孤兒 loan 留下；依開倉時間排序）
ledger, positions = load(SNAP)
kept, _ = screen_keep_orphans(positions)
out = {}
for per in (2, 30):
    rows = []
    for p in kept:
        if int(p["period"]) != per or not p["closed_at"]:
            continue
        o = hold_time.parse_moment(p["opened_at"]); c = hold_time.parse_moment(p["closed_at"])
        rows.append((p["opened_at"], float(p["rate"]), (c - o).total_seconds() / 3600))
    rows.sort()
    out[str(per)] = [(r, h) for _, r, h in rows]
json.dump(out, open("hold_samples.json", "w"))

# ② 每小時的「同天期金額加權中位數」（market_snapshots，08-23 起）——快照只供「下一個整點開始的那一小時」使用，不偷看未來
con = sqlite3.connect(f"file:{SNAP}?mode=ro", uri=True)
table = {"2": {}, "30": {}}
for cap, pr in con.execute("select captured_at, trade_period_rates_json from market_snapshots order by captured_at"):
    t = int(datetime.fromisoformat(cap).timestamp() * 1000)
    hour = (t // H) * H + H
    rates = json.loads(pr or "{}")
    for per in ("2", "30"):
        if per in rates:
            table[per][str(hour)] = rates[per]
json.dump(table, open("market_rate_by_hour.json", "w"))
print({k: len(v) for k, v in out.items()}, {k: len(v) for k, v in table.items()})
