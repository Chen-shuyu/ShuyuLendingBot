import sys, time, json
sys.path.insert(0, ".")
from sim import *
bags = load_bags()
mk = Market(2)
W = list(WINDOWS.items())
policies = [Fixed(x) for x in (4, 5, 6, 7, 8, 9, 10, 11)]
policies += [EV(floor_pct=f, hold_hours=12, label=f"現行模型 P12 地板{f:g}%") for f in (8, 6, 5, 4, 0)]
policies += [EV(floor_pct=8, hold_hours=48, label="現行模型 P48 地板8%")]
for L in (24, 72, 168):
    for q in (0.3, 0.5, 0.7, 0.9):
        policies.append(Follow(q, L))
results = {}
for pol in policies:
    t = time.time()
    row = {}
    for wname, (s, e) in W:
        row[wname] = across(mk, pol, bags["p2"], s, e, cap_hours=48)
    results[pol.name] = row
    print(f"{pol.name:24s}", "  ".join(f"{row[w]['net']:5.2f}({row[w]['util']:3.0f}%)" for w, _ in W), f"[{time.time()-t:.0f}s]", flush=True)
json.dump(results, open("results_main.json", "w"), ensure_ascii=False)
print("窗：", [w for w, _ in W])
print("實際：", [ACTUAL[w] for w, _ in W])
