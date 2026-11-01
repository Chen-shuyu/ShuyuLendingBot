# 校準 FRR 管道判準：我們掛著卻沒被吃到的期間，所有比我們貴的負號成交，分類後還剩多少？
import sys, statistics
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from sim3 import *
from td import real_offers, fmt, FRR
clean = load_all("clean", [2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 15, 20, 21, 30])
frrch = load_all("frr", [2, 30])
frr = FRR()
offers = [o for o in real_offers() if o["period"] in (2, 30)]
data_end = max(s.mts[-1] for s in clean.values())
for label, ser_fn in (("已篩後還違規（同天期）", lambda o: [clean[o["period"]]]),
                      ("已篩後還違規（天期 ≤ N）", lambda o: evidence(clean, o["period"])),
                      ("被判成 FRR 管道（同天期）", lambda o: [frrch[o["period"]]] if o["period"] in frrch else [])):
    rows = []
    live = {2: 0.0, 30: 0.0}
    for o in offers:
        a, b = o["posted"] + 5000, min(o["end"] - 3000, data_end)
        if b <= a: continue
        live[o["period"]] += (b - a) / H
        for s in ser_fn(o):
            i, j = bisect.bisect_left(s.mts, a), bisect.bisect_left(s.mts, b)
            for k in range(i, j):
                if s.rate[k] > o["rate"] * 1.0000001:
                    rows.append((o["period"], s.mts[k], s.rate[k], s.amt[k], o["rate"], frr.at(s.mts[k]), s.period))
    print(f"\n=== {label}：掛單存活 {({k: round(v,1) for k,v in live.items()})} 小時，違規 {len(rows)} 筆")
    for per in (2, 30):
        sub = [r for r in rows if r[0] == per]
        if not sub: continue
        amt = [r[3] for r in sub]
        dist = [(r[2]-r[5])*36500 for r in sub]
        print(f"  掛天期 {per}：{len(sub)} 筆、金額中位 {statistics.median(amt):,.0f}、距 FRR 分佈", {f"{lo}~{hi}": sum(1 for d in dist if lo <= d < hi) for lo, hi in ((-99,-3),(-3,-1),(-1,-.3),(-.3,.12),(.12,99))})
        for r in sorted(sub, key=lambda r: r[1])[:10]:
            print(f"     {fmt(r[1])} 成交天期 {r[6]:3d} 金額 {r[3]:>12,.2f} 利率 {r[2]*36500:6.3f}% 我們掛 {r[4]*36500:6.3f}% FRR {r[5]*36500:6.3f}%")
