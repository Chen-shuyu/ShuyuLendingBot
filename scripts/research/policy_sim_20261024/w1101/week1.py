# D074 第六節：第一週對帳。賺錢窗 10-25～10-31（7 個整天，部署 10-24 20:10 之後第一個完整週）
import sys
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from datetime import datetime, timedelta
from returns_lib import load, screen_keep_orphans, window as real_window, d as dd, TZ, annual, ledger_sum
from sim import *

SNAP = os.environ.get("POLICY_SIM_SNAPSHOT", "snap/lending.sqlite3")
NOW = datetime(2026, 11, 1, 14, 25, tzinfo=TZ)
ledger, positions = load(SNAP)
ps, orphans = screen_keep_orphans(positions)
print("孤兒 loan：", [(o["position_id"], o["opened_at"][5:16]) for o in orphans])

def show(label, s, e):
    w = real_window(ledger, ps, dd(s), dd(e), NOW, principal_rule="same")
    print(f"{label:26s} {s[5:]}~{e[5:]} {w['days']:2d}天 利用率 {w['util']:5.1f}% 名目 {w['nominal']:6.2f}% ①{w['cur']:5.2f} ②{w['ali']:5.2f} ③{w['pos']:5.2f}  ②淨利 {w['ali_usd']:.4f} ③淨利 {w['pos_usd']:.4f} 本金 {w['cap']:.2f}")
    return w

print("=== 實際（看哪天賺的）===")
W1 = show("第一週（新設定）", "2026-10-25", "2026-10-31")
show("上線以來 76 天", "2026-08-17", "2026-10-31")
show("D074 之前 68 天（對照）", "2026-08-17", "2026-10-23")
show("10-24 當天（換設定）", "2026-10-24", "2026-10-24")

print()
print("=== 模擬：同一週、同一個市場（天期 2，持有樣本袋 D074 凍結版）===")
bags = load_bags()
mk = Market(2)
s, e = ms(2026, 10, 25), ms(2026, 11, 1)
all_offsets = range(0, 24, 2)
rows = {}
for pol in (EV(floor_pct=5, hold_hours=12, label="新設定：P12 地板 5%"),
            EV(floor_pct=8, hold_hours=12, label="對照：舊設定（P12 地板 8%）"),
            EV(floor_pct=8, hold_hours=48, label="參考：P48 地板 8%（天期 2）"),
            Fixed(5), Fixed(5.5), Fixed(6), Fixed(7), Fixed(8)):
    r = across(mk, pol, bags["p2"], s, e, offsets=all_offsets, cap_hours=48)
    rows[pol.name] = r
    print(f"{pol.name:28s} 淨 {r['net']:5.2f}%（{r['lo']:5.2f}～{r['hi']:5.2f}） 利用率 {r['util']:5.1f}% 名目 {r['nominal']:5.2f}% 成交 {r['fills']:.1f} 次", flush=True)
new = rows["新設定：P12 地板 5%"]; old = rows["對照：舊設定（P12 地板 8%）"]
print()
print(f"判準一：實得 ② {W1['ali']:.2f}%／③ {W1['pos']:.2f}% 對 新設定模擬 {new['net']:.2f}% → 差 {W1['ali']-new['net']:+.2f}／{W1['pos']-new['net']:+.2f}pp（> 1pp 先查）")
print(f"判準二：實得 ② {W1['ali']:.2f}%／③ {W1['pos']:.2f}% 對 舊設定模擬 {old['net']:.2f}%（連續兩週輸才檢討）→ {'贏' if W1['ali']>old['net'] else '輸'}")
print(f"第一週預期：利用率 ≥ 80%（實際 {W1['util']:.1f}%）；成交價落在 5%～7%（名目 {W1['nominal']:.2f}%）")
