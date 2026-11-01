# 驗收：core/tape.py 對研究版（w1102）——同一批 425 萬筆，分類與成交、路徑都要一模一樣。
import os, sys, time, sqlite3, random, json
S = sys.argv[1]
sys.path.insert(0, S + "/w1102")
sys.path.insert(0, "/workspace/projects/LendingBot/ShuyuLendingBot")
from td import FRR, TRADES_DB, H, ms
import sim3
from core import tape as T
t0 = time.time()
frr = FRR()
con = sqlite3.connect(f"file:{TRADES_DB}?mode=ro", uri=True)
rows = con.execute("select id, mts, amount, rate, period from t order by mts, id").fetchall()
con.close()
print(f"讀 {len(rows)} 筆 {time.time()-t0:.0f}s", flush=True)
t0 = time.time()
new = T.build_tape(rows, frr.at)
print(f"分類 {time.time()-t0:.0f}s；零利率略過 {len(rows)-len(new)} 筆", flush=True)
old = {k: sim3.load_all(k) for k in ("clean", "frr", "pos")}
mp = {"clean": new.clean, "frr": new.frr_channel, "pos": new.positive}
bad = 0
for kind, o in old.items():
    n = mp[kind]
    tot_o = sum(len(s.mts) for s in o.values()); tot_n = sum(len(s) for s in n.values())
    diff_series = 0
    for p, so in o.items():
        sn = n.get(p)
        # 研究版沒濾零利率；比對時濾掉同樣的列
        o_rows = [(a, b, c) for a, b, c in zip(so.mts, so.rate, so.amt) if b > 0]
        n_rows = list(zip(sn.mts, sn.rate, sn.amount)) if sn else []
        if o_rows != n_rows:
            diff_series += 1
            print("  不同", kind, p, len(o_rows), len(n_rows))
    bad += diff_series
    print(f"{kind}: 舊 {tot_o} 新 {tot_n} 不同的天期數 {diff_series}", flush=True)
# find_fill 隨機比對（各天期、各價位、各時段）
random.seed(7)
A, B = ms(2026, 8, 10), ms(2026, 11, 1)
mism = 0
for i in range(4000):
    N = random.choice([2, 3, 5, 7, 10, 14, 30, 60, 120])
    r = random.uniform(4, 13) / 36500
    a = random.randint(A, B); b = a + random.randint(1, 200) * H // 2
    need = random.choice([0.01, 150.0, 348.0, 5000.0])
    fo = sim3.find_fill(sim3.evidence(old["clean"], N), r, a, b, need)
    fn = T.find_fill(new.evidence(N), r, a, b, need)
    if fo[0] != fn[0] or abs(fo[1] - fn[1]) > 1e-6:
        mism += 1
print("find_fill 4000 次隨機比對，不同：", mism, flush=True)
# simulate：拿研究版的掛價表
import prices as PR
pt = lambda name: {int(k): v for k, v in json.load(open(f"{S}/w1102/price_tables/{name}.json")).items()}
raw = json.load(open(S + "/hold_samples.json"))
bag2 = [h for r, h in raw["2"]]; bag30 = [h for r, h in raw["30"]]
for name, N, bag, cap, a, b in (("prod_p2_P12_f5", 2, bag2, 48, ms(2026, 10, 25), ms(2026, 11, 1)), ("prod_p7_P12_f5", 7, bag30, 168, ms(2026, 8, 17), ms(2026, 10, 31)), ("prod_p30_P12_f5", 30, bag30, None, ms(2026, 8, 17), ms(2026, 10, 31))):
    tb = pt(name)
    worst = 0.0
    for shift, off in enumerate(range(0, 48, 6)):
        out, w, tr = sim3.simulate(sim3.evidence(old["clean"], N), tb, bag, a + off * H, b, [(a + off * H, b)], cap_h=cap, shift=shift, need=348.0)
        pn = T.simulate_path(new.evidence(N), tb, bag, a + off * H, b, 348.0, cap_hours=cap, rotate=shift)
        worst = max(worst, abs(out[0]["net"] - pn.net_pct), abs(out[0]["util"] - pn.utilization_pct))
        if len(tr) != pn.fills:
            print("  成交次數不同", name, off, len(tr), pn.fills)
    print(f"{name}: 8 個起跑點，net／util 最大差 {worst:.2e}", flush=True)
print("分類不同的天期數合計", bad)
