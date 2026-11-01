# 工具回歸：拿新抓的 K 線與新查表，重現 D074 第三節記錄的數字（地板 × P 掃描的四格）
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim import *
bags = load_bags()
mk = Market(2)
W = list(WINDOWS.items())
doc = {("P12", 5): (6.86, 6.28, 5.03, 6.33), ("P12", 8): (5.17, 5.92, 1.39, 4.83)}
for (Pn, f), want in doc.items():
    pol = EV(floor_pct=f, hold_hours=12)
    row = [across(mk, pol, bags["p2"], s, e, offsets=range(0, 48, 6), cap_hours=48) for _, (s, e) in W]
    got = [r["net"] for r in row]
    print(Pn, f"地板{f}%", [round(x, 2) for x in got], "文件", want, "最大差", round(max(abs(a-b) for a, b in zip(got, want)), 3), flush=True)
