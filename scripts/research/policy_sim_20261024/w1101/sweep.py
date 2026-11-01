# P × ev_window_hours 掃描（天期 2、地板 5%）：同一條路徑上分段記帳，看高原（D032）與跨段一致性（D055）
import sys, json, math, statistics
from multiprocessing import Pool
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from sim import *

SEGS = [("A 08-17～09-13", ms(2026,8,17), ms(2026,9,14)),
        ("B 09-14～10-13", ms(2026,9,14), ms(2026,10,14)),
        ("C 10-14～10-24", ms(2026,10,14), ms(2026,10,25)),
        ("D 10-25～10-31", ms(2026,10,25), ms(2026,11,1))]
START, END = ms(2026,8,17), ms(2026,11,1)

def path(mk, pol, bag, start_i, end_i, shift, seg_idx):
    t = float(start_i); cyc = shift
    interest = [0.0]*len(seg_idx); lent = [0.0]*len(seg_idx); fills = [0]*len(seg_idx)
    def add(a, b, r):
        for k, (lo, hi) in enumerate(seg_idx):
            x, y = max(a, lo), min(b, hi)
            if y > x:
                interest[k] += r*(y-x); lent[k] += y-x
    while t < end_i:
        i = int(math.floor(t)); c = mk.hours[i]
        if c is None: t = i+1.0; continue
        r = pol.price(mk, i)
        if r is not None and c["high"] >= r:
            tf = (t+i+1)/2.0; h = min(bag[cyc % len(bag)], 48); cyc += 1
            add(tf, min(tf+h, end_i), r)
            for k, (lo, hi) in enumerate(seg_idx):
                if lo <= tf < hi: fills[k] += 1
            t = tf+h
        else:
            t = i+1.0
    return interest, lent, fills

def one(cfg):
    P, W, floor = cfg
    mk = Market(2); bag = load_bags()["p2"]
    pol = EV(floor_pct=floor, hold_hours=P, label=f"P{P}/窗{W}")
    pol.s.ev_window_hours = W
    if W < pol.s.ev_min_candles: pol.s.ev_min_candles = W
    seg_idx = [(mk.idx(a), mk.idx(b)) for _, a, b in SEGS]
    res = []
    for k, off in enumerate(range(0, 48, 6)):
        res.append(path(mk, pol, bag, mk.idx(START)+off, mk.idx(END), k, seg_idx))
    out = {}
    for j, (name, a, b) in enumerate(SEGS):
        hours = (b-a)/H
        nets = [r[0][j]/hours*365*100*FEE for r in res]
        utils = [r[1][j]/hours*100 for r in res]
        out[name] = (statistics.fmean(nets), statistics.fmean(utils))
    total_h = (END-START)/H
    tn = [sum(r[0])/total_h*365*100*FEE for r in res]
    out["全期"] = (statistics.fmean(tn), min(tn), max(tn))
    return cfg, out

if __name__ == "__main__":
    cfgs = [(P, W, 5.0) for P in (6, 8, 10, 12, 16, 20, 24, 36, 48) for W in (48, 72, 96, 120, 168, 240)]
    with Pool(8) as pool:
        res = pool.map(one, cfgs, chunksize=1)
    json.dump([(c, o) for c, o in res], open("sweep.json", "w"), ensure_ascii=False)
    print("完成", len(res))
