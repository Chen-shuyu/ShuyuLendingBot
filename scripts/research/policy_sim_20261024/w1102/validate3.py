# 驗收（用快取）：真金掛單逐段重播。規則要同時對得上天期 2 和天期 30。
import sys, time, statistics
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from sim3 import *
from td import real_offers, fmt

t0 = time.time()
clean = load_all("clean")
frrch = load_all("frr")
print(f"載入 {time.time()-t0:.0f}s；天期數 {len(clean)}", flush=True)
# 把 FRR 管道併回去就等於「沒篩」
raw = {}
for p in set(clean) | set(frrch):
    a, b = clean.get(p), frrch.get(p)
    if a and b:
        merged = sorted(list(zip(a.mts, a.rate, a.amt)) + list(zip(b.mts, b.rate, b.amt))) if p != 2 else None
        if merged is not None:
            raw[p] = S(p, array("q", [x[0] for x in merged]), array("d", [x[1] for x in merged]), array("d", [x[2] for x in merged]))
    elif a or b:
        raw[p] = a or b
data_end = max(s.mts[-1] for s in clean.values())
offers = [o for o in real_offers() if o["period"] in (2, 30) and o["posted"] < data_end]

def run(name, ev_of, strict, need=0.01, show=False):
    res = {2: dict(ep=0, act=0.0, sim=0.0, early=0, miss=0), 30: dict(ep=0, act=0.0, sim=0.0, early=0, miss=0)}
    episode, detail = [], []
    for o in offers:
        episode.append(o)
        if not o["filled_at"]:
            continue
        per = o["period"]
        start = episode[0]["posted"]
        fired = None
        for e in episode:
            a, b = e["posted"] + 3000, min(e["end"], data_end)
            if e is o:
                b = min(e["end"] + 300_000, data_end)
            ft, _ = find_fill(ev_of(e["period"]), e["rate"], a, b, need, 0.0, strict)
            if ft is not None:
                fired = ft
                break
        actual = (o["filled_at"] - start) / H
        sim = None if fired is None else (fired - start) / H
        r = res[per]
        r["ep"] += 1; r["act"] += actual
        if sim is None:
            r["miss"] += 1; r["sim"] += actual
        else:
            r["sim"] += sim
            if fired < o["filled_at"] - 600_000:
                r["early"] += 1
        detail.append((per, fmt(start), round(o["rate"]*36500, 3), round(actual, 2), None if sim is None else round(sim, 2), len(episode)))
        episode = []
    print(f"\n【{name}】")
    for per in (2, 30):
        r = res[per]
        if r["ep"]:
            print(f"  天期 {per:2d}：{r['ep']} 段，實際等 {r['act']:7.1f}h、模擬 {r['sim']:7.1f}h → {r['sim']/r['act']:.2f}×；提早 {r['early']} 段、沒抓到 {r['miss']} 段")
    if show:
        for x in detail:
            if x[0] == 30 or x[3] > 2:
                print("    ", x)
    return detail

run("① 未篩 FRR、同天期、≥（等同 K 線）", lambda p: [raw[p]] if p in raw and p != 2 else [clean[p]], False)
run("② 已篩 FRR、同天期、>", lambda p: evidence(clean, p, True), True)
run("③ 已篩 FRR、同天期、≥", lambda p: evidence(clean, p, True), False)
run("④ 已篩 FRR、天期 ≤ N、>", lambda p: evidence(clean, p), True, show=True)
run("⑤ 已篩 FRR、天期 ≤ N、≥", lambda p: evidence(clean, p), False, show=True)
