import sys, json
sys.path.insert(0, ".")
from datetime import datetime, timedelta
from returns_lib import *

ledger, positions = load()
NOW = datetime(2026, 10, 24, 18, 25, tzinfo=TZ)
ps, _ = screen_keep_orphans(positions)
s0 = d("2026-09-14")
row_k, row_v, row_u = [], [], []
for k in range(0, 34):
    s = s0 + timedelta(days=k); e = s + timedelta(days=6)
    w = window(ledger, ps, s, e, NOW, principal_rule="same")
    row_k.append(k); row_v.append(w["ali"]); row_u.append(w["util"])
for k, v, u in zip(row_k, row_v, row_u):
    s = s0 + timedelta(days=k)
    print(f"k={k:2d} {s:%m-%d}~{s+timedelta(days=6):%m-%d}  ② {v:5.2f}%  利用率 {u:5.1f}%")

# 錯過的機會：我們的單掛在場上、而天期 30 的 K 線高點 ≥ 8% 卻 < 我們的掛價 的小時數
p30 = json.load(open("dl/candles_p30.json"))
live = [  # (掛出, 成交或現在, 掛價年化%)
    (datetime(2026,10,12,0,59,tzinfo=TZ), datetime(2026,10,18,15,51,tzinfo=TZ), 10.95),
    (datetime(2026,10,20,18,20,tzinfo=TZ), NOW, 11.00),
]
print()
for a, b, r in live:
    hrs = [(datetime.fromtimestamp(m/1000, TZ), h*36500) for m, o, cl, h, l, v in p30
           if a <= datetime.fromtimestamp(m/1000, TZ) + timedelta(hours=1) and datetime.fromtimestamp(m/1000, TZ) < b]
    miss = [(t, h) for t, h in hrs if 8 <= h < r]
    hit = [(t, h) for t, h in hrs if h >= r]
    print(f"掛 {r}% {a:%m-%d %H:%M} → {b:%m-%d %H:%M}（{(b-a).total_seconds()/3600:.0f}h）：K 線 {len(hrs)} 根，"
          f"高點 ≥ 我們掛價 {len(hit)} 根 {[f'{t:%m-%d %H}時 {h:.2f}' for t,h in hit]}，"
          f"8%～掛價之間 {len(miss)} 根 {[f'{t:%m-%d %H}時 {h:.2f}' for t,h in miss]}")
