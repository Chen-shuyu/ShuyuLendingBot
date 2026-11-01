# 各天期比較（新引擎）。持有時間是最大的未知數，所以每個天期跑三種假設：
#   中：天然持有用天期 30 的真實樣本袋（11 筆，平均 49h），超過 N 天就截斷；天期 2 用天期 2 的真實樣本袋
#   短：借款人不會因為天期長就借比較久（所有天期都用天期 2 的樣本袋，最長 48h）
#   長：每筆都借滿 N 天（上限；也最能看出「鎖在低價」的風險）
import sys, json, statistics, time
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from multiprocessing import Pool
from sim3 import *
import prices as PR
raw = json.load(open(ROOT + "/hold_samples.json"))
dedup, seen = [], set()
for r, h in raw["2"]:
    key = round(h, 1)
    if key == 11.6 and key in seen:
        continue
    seen.add(key); dedup.append(h)
NEW2 = [1.77, 12.06, 48.26, 48.13, 0.59, 0.49, 48.0]
BAG2 = dedup + NEW2
BAG30 = [h for r, h in raw["30"]]
START, END = ms(2026,8,17), ms(2026,11,1)
SEGS = [("A 08-17～09-13", ms(2026,8,17), ms(2026,9,14)), ("B 09-14～10-13", ms(2026,9,14), ms(2026,10,14)),
        ("C 10-14～10-24", ms(2026,10,14), ms(2026,10,25)), ("D 10-25～10-31", ms(2026,10,25), ms(2026,11,1))]
seg_ranges = [(a, b) for _, a, b in SEGS]
PER = [2, 3, 4, 5, 7, 10, 14, 20, 30, 60, 90, 120]
_clean = None

def bags(N):
    cap = N * 24
    return {"中": (BAG2 if N == 2 else BAG30, cap), "短": (BAG2, min(cap, 48)), "長": ([cap], cap)}

def run_cfg(cfg):
    global _clean
    if _clean is None:
        _clean = load_all("clean")
    N, P, mode = cfg
    t = PR.load_table(N, P, mode, 5.0)
    ev = evidence(_clean, N)
    out = {}
    for name, (bag, cap) in bags(N).items():
        runs = []
        fills = []
        for k, off in enumerate(range(0, 48, 6)):
            res, w, tr = simulate(ev, t, bag, START + off * H, END, seg_ranges + [(START, END)], cap, shift=k)
            runs.append(res)
            fills.extend(w)
        rec = {}
        for j, key in enumerate([s[0] for s in SEGS] + ["全期"]):
            vals = [r[j] for r in runs if r[j]]
            noms = [v["nominal"] for v in vals if v["nominal"] == v["nominal"]]
            rec[key] = dict(net=statistics.fmean(v["net"] for v in vals), lo=min(v["net"] for v in vals), hi=max(v["net"] for v in vals),
                            util=statistics.fmean(v["util"] for v in vals), nom=statistics.fmean(noms) if noms else 0.0,
                            fills=statistics.fmean(v["fills"] for v in vals))
        rec["wait_mean"] = statistics.fmean(fills) if fills else None
        rec["wait_med"] = statistics.median(fills) if fills else None
        out[name] = rec
    return cfg, out

if __name__ == "__main__":
    jobs = [(N, P, mode) for N in PER for P in (12, 24, 48) for mode in ("prod", "clean")]
    t0 = time.time()
    with Pool(5) as pool:
        res = pool.map(run_cfg, jobs, chunksize=1)
    json.dump([[list(c), o] for c, o in res], open(ROOT + "/w1102/periods.json", "w"), ensure_ascii=False)
    print("完成", len(res), f"{time.time()-t0:.0f}s", flush=True)
