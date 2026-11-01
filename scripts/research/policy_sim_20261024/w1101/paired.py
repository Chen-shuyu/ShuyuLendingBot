# 成對比較：同一組起跑點與持有序列，短窗 vs 現行 168（P12、地板 5%）
import sys, statistics, json
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from multiprocessing import Pool
from sweep import path, SEGS, START, END
from sim import *

OFFS = list(range(0, 96, 4))  # 24 個起跑點

def one(W):
    mk = Market(2); bag = load_bags()["p2"]
    pol = EV(floor_pct=5, hold_hours=12, label=f"窗{W}")
    pol.s.ev_window_hours = W
    seg_idx = [(mk.idx(a), mk.idx(b)) for _, a, b in SEGS]
    start = mk.idx(START); end = mk.idx(END)
    out = []
    for k, off in enumerate(OFFS):
        interest, lent, fills = path(mk, pol, bag, start + off, end, k, seg_idx)
        total_h = end - (start + off)
        seg_net = []
        for j, (name, a, b) in enumerate(SEGS):
            h = (b - a) / H - (off if j == 0 else 0)
            seg_net.append(interest[j] / h * 365 * 100 * FEE)
        out.append((sum(interest) / total_h * 365 * 100 * FEE, seg_net))
    return W, out

if __name__ == "__main__":
    with Pool(5) as pool:
        res = dict(pool.map(one, [48, 72, 96, 120, 168], chunksize=1))
    base = res[168]
    print(f"現行 窗168：全期平均 {statistics.fmean(x[0] for x in base):.2f}%（{min(x[0] for x in base):.2f}～{max(x[0] for x in base):.2f}），起跑點 {len(OFFS)} 個")
    for W in (48, 72, 96, 120):
        diffs = [a[0] - b[0] for a, b in zip(res[W], base)]
        segd = [statistics.fmean(a[1][j] - b[1][j] for a, b in zip(res[W], base)) for j in range(len(SEGS))]
        print(f"窗{W:3d}：全期 {statistics.fmean(x[0] for x in res[W]):.2f}%，比 168 {statistics.fmean(diffs):+.2f}pp；贏 {sum(d > 0 for d in diffs)}/{len(diffs)} 個起跑點；最差 {min(diffs):+.2f}、最好 {max(diffs):+.2f}；分段差 A/B/C/D = " + " ".join(f"{x:+.2f}" for x in segd))
