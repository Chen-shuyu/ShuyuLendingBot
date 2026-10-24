import sys, json
sys.path.insert(0, ".")
from sim import *
from returns_lib import load, screen_keep_orphans, window as real_window, d as dd, TZ
bags = load_bags()
mk = Market(2)
ledger, positions = load()
ps, _ = screen_keep_orphans(positions)
NOW = datetime(2026, 10, 24, 18, 25, tzinfo=TZ)
weeks = []
s0 = datetime(2026, 8, 17, tzinfo=CST)
while s0 < datetime(2026, 10, 24, tzinfo=CST):
    e0 = min(s0 + timedelta(days=7), datetime(2026, 10, 24, tzinfo=CST))
    weeks.append((s0, e0)); s0 = e0
pols = [EV(floor_pct=8, hold_hours=12, label="天期2 P12 地板8%"), EV(floor_pct=5, hold_hours=12, label="天期2 P12 地板5%")]
print("週（賺錢窗）      實際   | 天期2 地板8%  天期2 地板5%   ← 模擬（天期2，跨起跑點平均）")
wins = 0
for s, e in weeks:
    real = real_window(ledger, ps, s.date(), (e - timedelta(days=1)).date(), NOW, principal_rule="same")["ali"]
    sims = [across(mk, p, bags["p2"], int(s.timestamp()*1000), int(e.timestamp()*1000), offsets=range(0, 24, 4), cap_hours=48)["net"] for p in pols]
    wins += sims[1] >= sims[0] - 1e-9
    print(f"{s:%m-%d}～{e - timedelta(days=1):%m-%d}   {real:5.2f}%  |   {sims[0]:5.2f}%       {sims[1]:5.2f}%")
print(f"地板 5% 不輸地板 8% 的週數：{wins}/{len(weeks)}")

# 地板 5% 之後實際用什麼價借出去（全期，單一起跑點，記下每筆成交價）
pol = EV(floor_pct=5, hold_hours=12)
s, e = WINDOWS["全期 08-17～10-23"]
t = float(mk.idx(s)); end = mk.idx(e); fills = []; cyc = 0
while t < end:
    i = int(t); c = mk.hours[i]
    if c is None: t = i + 1.0; continue
    r = pol.price(mk, i)
    if r is not None and c["high"] >= r:
        h = min(bags["p2"][cyc % len(bags["p2"])], 48); cyc += 1
        fills.append((mk.when(i), r * 36500, h)); t = (t + i + 1) / 2 + h
    else:
        t = i + 1.0
rates = [r for _, r, _ in fills]
print(f"\n地板 5% 的成交價（全期 {len(fills)} 筆）：最低 {min(rates):.2f}%、p10 {quantile(rates,.1):.2f}%、中位 {quantile(rates,.5):.2f}%、p90 {quantile(rates,.9):.2f}%")
for label, lo, hi in (("< 6%", 0, 6), ("6～7%", 6, 7), ("7～8%", 7, 8), ("≥ 8%", 8, 99)):
    print(f"   {label}: {sum(lo <= r < hi for r in rates)} 筆")
oct_ = [r for t_, r, _ in fills if t_ >= datetime(2026, 10, 14, tzinfo=CST)]
print(f"   10-14 之後 {len(oct_)} 筆：{[round(x, 2) for x in oct_]}")
