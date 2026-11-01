import sys, sqlite3, bisect, json
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from sim import *
bags = load_bags()
mk2 = Market(2); mk30 = Market(30)
s, e = ms(2026, 10, 25), ms(2026, 11, 1)
off = range(0, 24, 2)

print("=== 如果 10-24 沒改（天期 30、P48、地板 8%）——天期 30 的模擬會高估，只能當上限 ===")
for label, ev_kw in (("照舊（168 根的窗）", {"time_window": False}), ("窗修成 168 小時", {"time_window": True})):
    pol = EV(floor_pct=8, hold_hours=48, label=label, **ev_kw)
    r = across(mk30, pol, bags["p30"], s, e, offsets=off)
    print(f"  {label:18s} 淨 {r['net']:5.2f}%（{r['lo']:5.2f}～{r['hi']:5.2f}） 利用率 {r['util']:5.1f}% 名目 {r['nominal']:.2f}% 成交 {r['fills']:.1f} 次")
pol = EV(floor_pct=5, hold_hours=48, time_window=True, label="天期 30、地板 5%、窗修好")
r = across(mk30, pol, bags["p30"], s, e, offsets=off)
print(f"  {pol.name:18s} 淨 {r['net']:5.2f}%（{r['lo']:5.2f}～{r['hi']:5.2f}） 利用率 {r['util']:5.1f}% 名目 {r['nominal']:.2f}% 成交 {r['fills']:.1f} 次")

print()
print("=== 這週事後看最好的固定價（天期 2，樣本袋）＝M3 的「當時可達到的最佳」===")
for x in (4.5, 5, 5.25, 5.5, 5.75, 6, 6.25, 6.5, 6.75, 7, 7.5, 8, 9):
    r = across(mk2, Fixed(x), bags["p2"], s, e, offsets=off, cap_hours=48)
    print(f"  固定 {x:5.2f}%：淨 {r['net']:5.2f}%（{r['lo']:5.2f}～{r['hi']:5.2f}） 利用率 {r['util']:5.1f}%")

print()
print("=== 持有樣本加入這週的 6 筆（低價區第一批實測）＋ 未結清那筆（假設借滿 48h）===")
new_holds = [1.77, 12.06, 48.26, 48.13, 0.59, 0.49, 48.0]
bag2 = bags["p2"] + new_holds
print(f"  原袋 {len(bags['p2'])} 筆 平均 {statistics.fmean(bags['p2']):.1f}h ／ 新 7 筆 平均 {statistics.fmean(new_holds):.1f}h ／ 合併 {len(bag2)} 筆 平均 {statistics.fmean(bag2):.1f}h")
for floor, P in ((5, 12), (8, 12)):
    pol = EV(floor_pct=floor, hold_hours=P)
    for name, bag in (("原袋", bags["p2"]), ("合併袋", bag2), ("只用新 7 筆", new_holds)):
        r = across(mk2, pol, bag, s, e, offsets=off, cap_hours=48)
        print(f"  地板{floor}% {name:10s} 這週 淨 {r['net']:5.2f}%（{r['lo']:5.2f}～{r['hi']:5.2f}） 利用率 {r['util']:5.1f}%")

print()
print("=== 照實際掛價 ＋ 實際持有序列重播這週（驗成交規則，排除持有的運氣）===")
class Replay:
    def __init__(self):
        con = sqlite3.connect(f"file:{os.environ.get('POLICY_SIM_SNAPSHOT', 'snap/lending.sqlite3')}?mode=ro", uri=True)
        rows = [(int(datetime.fromisoformat(t).timestamp()*1000), float(r)) for t, r, d in con.execute("select created_at, rate, duration from loan_offers order by created_at") if int(d) == 2]
        self.ts = [t for t, _ in rows]; self.rs = [r for _, r in rows]; self.name = "replay"
    def price(self, mk, i):
        k = bisect.bisect_right(self.ts, mk.t0 + i*H) - 1
        return self.rs[k] if k >= 0 else None
r = run(mk2, Replay(), new_holds, mk2.idx(s), mk2.idx(e), cap_hours=48, bag_shift=0)
print(f"  模擬 淨 {r[0]:.2f}% 利用率 {r[1]:.1f}% 名目 {r[2]:.2f}% 成交 {r[3]} 次 ／ 實際 ② 4.08% ③ 3.96% 利用率 77.8% 名目 5.98% 成交 7 次（含 10-25 00:10 那筆）")

print()
print("=== 現在這一刻新設定會掛多少（下一次錢回來時的參考）===")
pol = EV(floor_pct=5, hold_hours=12)
now_i = mk2.idx(ms(2026,11,1,14))
for label, i in (("11-01 14:00", now_i),):
    print(f"  {label}：選價 {pol.price(mk2, i)*36500:.3f}%，常態價 {market_rate(mk2, i)*36500:.3f}%")
s_ = pol.s
candles = [c for c in mk2.hours[max(0, now_i-3000):now_i] if c][-240:]
s_.choose_rate(candles)
ev = sorted(s_.last_evaluation, key=lambda x: -x["effective"])[:6]
print("  前幾名候選：", [(round(x["rate"]*36500,2), round(x["effective"]*36500,2), x["hits"]) for x in ev])
