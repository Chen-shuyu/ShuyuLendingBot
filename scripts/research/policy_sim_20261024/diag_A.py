import sys
sys.path.insert(0, ".")
from sim import *
from collections import Counter
mk = Market(2)
s, e = WINDOWS["A 短天期實測期 08-17～09-13"]
pol = EV(floor_pct=8.0, hold_hours=12)
st = Counter(); prices = []
skips_by_day = Counter()
for i in range(mk.idx(s), mk.idx(e)):
    c = mk.hours[i]
    candles = [x for x in mk.hours[max(0, i - 3000):i] if x][-240:]
    base = pol.s.choose_rate(candles)
    if base is None:
        st["模型選不出價"] += 1; skips_by_day[mk.when(i).strftime('%m-%d')] += 1; continue
    closes = [x["close"] for x in mk.hours[max(0, i - 6):i] if x]
    floored = max(base, statistics.median(closes) * 0.85)
    if floored < pol.floor:
        st["低於 8% 地板，不借"] += 1; skips_by_day[mk.when(i).strftime('%m-%d')] += 1; continue
    prices.append(floored * 36500)
    st["有掛價"] += 1
    if c and c["high"] >= floored: st["該小時會成交"] += 1
print(dict(st))
print("掛價分佈：中位", round(statistics.median(prices), 2), "p10", round(quantile(prices, .1), 2), "p90", round(quantile(prices, .9), 2))
print("不借的小時（按天）:", dict(sorted(skips_by_day.items())))
