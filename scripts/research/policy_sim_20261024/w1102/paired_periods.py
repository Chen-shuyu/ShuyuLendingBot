# 成對比較：同一組起跑點，候選天期 vs 現行（天期 2、P12）。動態規則：價高鎖長、價低鎖短。
import sys, json, statistics, time, math
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from multiprocessing import Pool
from sim3 import *
import prices as PR
from run_periods import BAG2, BAG30, SEGS, START, END, seg_ranges
OFFS = list(range(0, 96, 4))
_clean = None
def clean():
    global _clean
    if _clean is None:
        _clean = load_all("clean")
    return _clean

def bags(N):
    cap = N * 24
    return {"短": (BAG2, min(cap, 48)), "中": (BAG2 if N == 2 else BAG30, cap), "長": ([cap], cap)}

def static(cfg):
    N, P, scen = cfg
    t = PR.load_table(N, P, "prod", 5.0)
    ev = evidence(clean(), N)
    bag, cap = bags(N)[scen]
    out = []
    for k, off in enumerate(OFFS):
        res, w, tr = simulate(ev, t, bag, START + off*H, END, seg_ranges + [(START, END)], cap, shift=k)
        out.append([r["net"] if r else None for r in res])
    return cfg, out

def simulate_dyn(c, table, rule, scen, start, end, segs, shift):
    """價格由天期 2 的掛價表決定；天期依價格決定（價高鎖長、價低鎖短）。"""
    interest = [0.0]*len(segs); lent = [0.0]*len(segs)
    t, cyc = start, shift
    evs = {}
    while t < end:
        h = t // H
        r = table.get(h)
        if r is None:
            t = (h+1)*H; continue
        live, cum, cur, filled = r, 0.0, t, None
        N = rule(live)
        ev = evs.setdefault(N, evidence(c, N))
        while cur < end:
            nh = (cur//H+1)*H
            ft, cum = find_fill(ev, live, cur, min(nh, end), CAPITAL, cum, True)
            if ft is not None:
                filled = ft; break
            cur = nh
            if cur >= end: break
            r2 = table.get(cur//H)
            if r2 is not None and abs(r2-live)/r2*100 > 2.0:
                live, cum = r2, 0.0
                N = rule(live); ev = evs.setdefault(N, evidence(c, N))
        if filled is None: break
        bag, cap = bags(N)[scen]
        hold = min(bag[cyc % len(bag)], cap); cyc += 1
        a, b = filled, min(filled+int(hold*H), end)
        for k, (lo, hi) in enumerate(segs):
            x, y = max(a, lo), min(b, hi)
            if y > x:
                interest[k] += live*(y-x)/H; lent[k] += (y-x)/H
        t = filled + int(hold*H)
    out = []
    for k, (lo, hi) in enumerate(segs):
        w = (hi-max(lo, start))/H
        out.append(interest[k]/w*365*100*FEE if w > 0 else None)
    return out

def dyn(cfg):
    name, X, Nhi, scen = cfg
    t = PR.load_table(2, 12, "prod", 5.0)
    rule = (lambda r: Nhi if r*36500 >= X else 2)
    out = []
    for k, off in enumerate(OFFS):
        out.append(simulate_dyn(clean(), t, rule, scen, START+off*H, END, seg_ranges+[(START, END)], k))
    return cfg, out

if __name__ == "__main__":
    cands = [(2,12),(3,12),(3,24),(5,12),(5,24),(7,12),(7,24),(14,12),(30,12),(30,24),(120,12),(120,24)]
    jobs = [(N,P,s) for N,P in cands for s in ("短","中","長")]
    with Pool(6) as pool:
        res = dict(pool.map(static, jobs, chunksize=1))
        djobs = [("dyn",X,Nhi,s) for X in (7,8,9) for Nhi in (7,30,120) for s in ("短","中","長")]
        dres = dict(pool.map(dyn, djobs, chunksize=1))
    base = {s: res[(2,12,s)] for s in ("短","中","長")}
    names = ["A","B","C","D","全期"]
    print("現行（天期 2、P12）全期：", {s: round(statistics.fmean(x[-1] for x in base[s]),2) for s in base})
    print("\n候選 vs 現行（24 個起跑點成對）：全期差、勝率、A/B/C/D 分段差")
    for N,P in cands[1:]:
        for s in ("短","中","長"):
            cur = res[(N,P,s)]
            d = [a[-1]-b[-1] for a,b in zip(cur, base[s])]
            seg = [statistics.fmean(a[j]-b[j] for a,b in zip(cur, base[s])) for j in range(4)]
            print(f" 天期{N:4d} P{P:2d} 持有{s}：全期 {statistics.fmean(x[-1] for x in cur):5.2f}，差 {statistics.fmean(d):+5.2f}pp，贏 {sum(x>0 for x in d):2d}/24，最差 {min(d):+5.2f}，分段 " + " ".join(f"{x:+5.2f}" for x in seg))
    print("\n動態規則（價格照天期 2 的模型；價 ≥ X 就掛長天期，否則天期 2）：")
    for (nm,X,Nhi,s),cur in dres.items():
        d = [a[-1]-b[-1] for a,b in zip(cur, base[s])]
        seg = [statistics.fmean(a[j]-b[j] for a,b in zip(cur, base[s])) for j in range(4)]
        print(f" ≥{X}%→天期{Nhi:3d} 持有{s}：全期 {statistics.fmean(x[-1] for x in cur):5.2f}，差 {statistics.fmean(d):+5.2f}pp，贏 {sum(x>0 for x in d):2d}/24，分段 " + " ".join(f"{x:+5.2f}" for x in seg))
