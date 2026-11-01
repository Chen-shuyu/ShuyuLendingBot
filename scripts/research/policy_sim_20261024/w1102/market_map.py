# 市場地圖：各天期 × 各價位，「從任意時刻掛上去」平均要等多久才被真掃單吃到（看 M ≤ N 的證據），跟同天期只看自己的差多少。
# 另外看買方掛單（正號成交）：每天各天期最高多少、多少量——那是可以「直接成交」的價。
import sys, statistics, json
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from sim3 import *
clean = load_all("clean")
pos = load_all("pos")
data_end = max(s.mts[-1] for s in clean.values())
SEGS = [("熱 08-17～10-07", ms(2026,8,17), ms(2026,10,8)), ("冷 10-08～10-31", ms(2026,10,8), ms(2026,11,1))]
PER = [2, 3, 4, 5, 7, 10, 14, 20, 30, 60, 90, 120]
RATES = [5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5, 9, 9.5, 10, 10.5, 11]

def mean_wait(ev, r, a, b, step_h=3, need=CAPITAL):
    """每 step_h 小時進場一次，等到被吃到（窗尾截斷算到窗尾）"""
    waits = []
    t = a
    while t < b:
        ft, _ = find_fill(ev, r/36500, t, b, need)
        waits.append(((ft if ft else b) - t) / H)
        t += step_h * H
    return statistics.fmean(waits), statistics.median(waits)

for name, a, b in SEGS:
    print(f"\n=== {name}：掛 (r, N) 要等幾小時（平均）。證據＝天期 ≤ N 的真掃單，累積 ≥ 348 USD ===")
    print("價位\\天期 " + "".join(f"{p:>7d}" for p in PER))
    for r in RATES:
        cells = []
        for p in PER:
            ev = evidence(clean, p)
            m, _ = mean_wait(ev, r, a, b)
            cells.append(f"{m:7.1f}")
        print(f"{r:7.1f}%  " + "".join(cells), flush=True)

print("\n=== 買方掛單（正號成交）：每週各天期的最高成交價與金額（萬 USD）===")
weeks = []
t = ms(2026,8,17)
while t < ms(2026,11,1):
    weeks.append(t); t += 7*24*H
print("週起點  " + "".join(f"{'p'+str(p):>14s}" for p in (2,7,30,60,90,120)))
for w in weeks:
    cells = []
    for p in (2,7,30,60,90,120):
        s = pos.get(p)
        if not s:
            cells.append(f"{'-':>14s}"); continue
        i, j = bisect.bisect_left(s.mts, w), bisect.bisect_left(s.mts, w+7*24*H)
        if j <= i:
            cells.append(f"{'-':>14s}"); continue
        cells.append(f"{max(s.rate[i:j])*36500:6.2f}/{sum(s.amt[i:j])/1e4:7.0f}")
    print(fmt(w)[:5], "  " + "".join(cells))
