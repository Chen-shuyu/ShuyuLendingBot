import sys, time, sqlite3, bisect
sys.path.insert(0, ".")
from sim import *

class Replay:
    """照實際掛過的價：每小時用「這一刻之前最後一張實際掛單」的利率。"""
    def __init__(self, period):
        con = sqlite3.connect("file:snap/lending-20261024.sqlite3?mode=ro", uri=True)
        rows = [(int(datetime.fromisoformat(t).timestamp() * 1000), float(r)) for t, r, d in
                con.execute("select created_at, rate, duration from loan_offers where currency='USD' order by created_at") if int(d) == period]
        self.ts = [t for t, _ in rows]; self.rs = [r for _, r in rows]
        self.name = f"照實際掛價重播（天期 {period}）"
    def price(self, mk, i):
        k = bisect.bisect_right(self.ts, mk.t0 + i * H) - 1
        return self.rs[k] if k >= 0 else None

bags = load_bags()
mk2 = Market(2)
s, e = WINDOWS["A 短天期實測期 08-17～09-13"]
switch = [(ms(2026, 8, 17), 48), (ms(2026, 8, 30, 23) + 30 * 60 * 1000, 12)]
for pol in (Replay(2), EV(floor_pct=8.0, hold_switch=switch, label="現行模型（照當時設定時間表）")):
    t = time.time()
    r = across(mk2, pol, bags["p2"], s, e, offsets=range(0, 48, 3), cap_hours=48)
    print(f"窗A 天期2 {pol.name}：淨 {r['net']:.2f}%（{r['lo']:.2f}～{r['hi']:.2f}）利用率 {r['util']:.1f}% 名目 {r['nominal']:.2f}%  成交 {r['fills']:.1f} 次 [{time.time()-t:.0f}s]")
print("實際：6.46%（利用率 86.0%、名目 8.83%）")

mk30 = Market(30)
for wname in ("B 長天期判定窗 09-14～10-13", "C 延長期 10-14～10-23"):
    s, e = WINDOWS[wname]
    for pol in (Replay(30), EV(floor_pct=8.0, hold_hours=48, label="現行模型（天期30、P48）")):
        r = across(mk30, pol, bags["p30"], s, e, offsets=range(0, 48, 3))
        print(f"{wname} 天期30 {pol.name}：淨 {r['net']:.2f}%（{r['lo']:.2f}～{r['hi']:.2f}）利用率 {r['util']:.1f}% 名目 {r['nominal']:.2f}%  成交 {r['fills']:.1f} 次")
    print("   實際：", ACTUAL[wname], "%")
