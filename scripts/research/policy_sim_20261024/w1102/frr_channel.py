import sys, statistics, json
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from sim3 import *
from td import FRR
ch = load_all("frr"); frr = FRR()
weeks = [("08-17～08-31", ms(2026,8,17), ms(2026,9,1)), ("09-01～09-30", ms(2026,9,1), ms(2026,10,1)), ("10-01～10-14", ms(2026,10,1), ms(2026,10,15)), ("10-15～10-31", ms(2026,10,15), ms(2026,11,1))]
print("FRR 管道（負號、貼著 FRR、沒有階梯）每天的量")
tot = {}
for p, s in ch.items():
    tot[p] = sum(s.amt)
top = sorted(tot, key=lambda p: -tot[p])[:10]
print("天期   " + "".join(f"{w[0]:>26s}" for w in weeks))
print("       " + "".join(f"{'萬USD/天':>10s}{'筆/天':>8s}{'<2000/天':>8s}" for _ in weeks))
for p in top:
    s = ch[p]; row = []
    for name, a, b in weeks:
        i, j = bisect.bisect_left(s.mts, a), bisect.bisect_left(s.mts, b)
        d = (b-a)/(24*H)
        am = s.amt[i:j]
        row.append(f"{sum(am)/d/1e4:10.0f}{(j-i)/d:8.0f}{sum(1 for x in am if x<2000)/d:8.1f}")
    print(f"{p:4d}   " + "".join(row))
print("\n距 FRR 的細分佈（10-15～10-31，天期 30、120；單位 pp）：")
a, b = ms(2026,10,15), ms(2026,11,1)
bins = [(-.31,-.2),(-.2,-.1),(-.1,-.07),(-.07,-.05),(-.05,-.03),(-.03,-.01),(-.01,.01),(.01,.05),(.05,.13),(.13,9)]
for p in (30,120):
    s = ch[p]; i, j = bisect.bisect_left(s.mts, a), bisect.bisect_left(s.mts, b)
    d = [(s.rate[k]-frr.at(s.mts[k]))*36500 for k in range(i,j)]
    am = s.amt[i:j]
    print(f" 天期 {p}：{j-i} 筆", {f"{lo}~{hi}": (sum(1 for x in d if lo<=x<hi), round(sum(y for x,y in zip(d,am) if lo<=x<hi)/1e4)) for lo,hi in bins})
print("\n（括號：筆數、萬 USD）")
print("\n10-15～10-31 天期 120、30 最小額的幾筆（證明小額有沒有在裡面）：")
for p in (120,30):
    s = ch[p]; i, j = bisect.bisect_left(s.mts, a), bisect.bisect_left(s.mts, b)
    am = sorted(s.amt[i:j])
    print(f" 天期 {p}：最小 {am[:5]}，中位 {statistics.median(am) if am else 0:,.0f}，150～2000 USD 的 {sum(1 for x in am if 150<=x<2000)} 筆")
