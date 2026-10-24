import sys, time, json
sys.path.insert(0, ".")
from sim import *
bags = load_bags()
mk = Market(2)
W = list(WINDOWS.items())
print("=== 一、地板 × P 掃描（天期 2，持有樣本袋）===")
print("              " + "  ".join(f"{w[:1]:>11s}" for w, _ in W))
for P in (12, 24, 48):
    for f in (5, 6, 7, 8):
        pol = EV(floor_pct=f, hold_hours=P)
        row = [across(mk, pol, bags["p2"], s, e, offsets=range(0, 48, 6), cap_hours=48) for _, (s, e) in W]
        print(f"P{P:2d} 地板{f}%  " + "  ".join(f"{r['net']:5.2f}({r['util']:3.0f}%)" for r in row), flush=True)

print("\n=== 二、換持有時間假設：每筆固定 24h ／ 固定 48h（借滿）===")
for label, bag in (("固定24h", [24.0]), ("固定48h", [48.0])):
    for pol in (EV(floor_pct=8, hold_hours=12, label="現行 P12 地板8%"), EV(floor_pct=5, hold_hours=12, label="現行 P12 地板5%"),
                Fixed(8), Fixed(9), Follow(0.5, 72)):
        row = [across(mk, pol, bag, s, e, offsets=range(0, 48, 6), cap_hours=48) for _, (s, e) in W]
        print(f"{label} {pol.name:18s} " + "  ".join(f"{r['net']:5.2f}({r['util']:3.0f}%)" for r in row), flush=True)
