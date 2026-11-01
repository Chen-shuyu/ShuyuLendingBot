import json, sys
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
res = json.load(open(ROOT + "/w1102/periods.json"))
T = {tuple(c): o for c, o in res}
PER = sorted({c[0] for c in T})
SEG = ["A 08-17～09-13", "B 09-14～10-13", "C 10-14～10-24", "D 10-25～10-31", "全期"]
for mode, title in (("prod", "只改 offer_period（現行程式原封不動）"), ("clean", "改良定價（看真掃單、窗＝168 小時）")):
    print(f"\n===== {title}：地板 5% =====")
    for scen in ("中", "短", "長"):
        print(f"\n--- 持有假設：{scen} ---")
        print("天期  P  " + " ".join(f"{s[:1]:>6s}" for s in SEG[:-1]) + "  全期(範圍)          利用率 名目  成交次 等待中位h")
        for N in PER:
            for P in (12, 24, 48):
                r = T[(N, P, mode)][scen]; f = r["全期"]
                print(f"{N:4d} {P:3d} " + " ".join(f"{r[s]['net']:6.2f}" for s in SEG[:-1]) + f"  {f['net']:5.2f}（{f['lo']:5.2f}～{f['hi']:5.2f}） {f['util']:5.1f} {f['nom']:5.2f} {f['fills']:5.1f} {r['wait_med'] if r['wait_med'] is not None else float('nan'):6.1f}")
