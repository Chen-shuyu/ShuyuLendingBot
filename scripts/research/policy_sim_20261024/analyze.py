import sys
sys.path.insert(0, ".")
from datetime import datetime, timedelta
from returns_lib import *

ledger, positions = load()
NOW = datetime(2026, 10, 24, 18, 25, tzinfo=TZ)   # 快照時刻
ps, orphans = screen_keep_orphans(positions)
print("孤兒 loan（留下，帳本有入帳佐證）:", [(o["position_id"], o["opened_at"][5:16], o["closed_at"][5:16]) for o in orphans])
print("帳本最後同步:", "10-24 14:17；最後一列入帳日", max(ledger))
print()

def show(label, s, e):
    w = window(ledger, ps, d(s), d(e), NOW, principal_rule="same")
    print(f"{label:28s} {s[5:]}~{e[5:]} {w['days']:2d}天  利用率 {w['util']:5.1f}%  名目 {w['nominal']:6.2f}%  "
          f"①{w['cur']:5.2f}  ②{w['ali']:5.2f}  ③{w['pos']:5.2f}   ②淨利 {w['ali_usd']:.4f} USD  本金 {w['cap']:.2f}")
    return w

print("=== 判定窗與延長期 ===")
J = show("判定窗（長天期 30 天）", "2026-09-14", "2026-10-13")
show("對手：短天期整月", "2026-08-17", "2026-09-13")
X = show("延長期（到 10-23 整天）", "2026-10-14", "2026-10-23")
show("長天期全程 41 天", "2026-09-14", "2026-10-24")
show("長天期全程到 10-23", "2026-09-14", "2026-10-23")
show("上線以來（08-17 起）", "2026-08-17", "2026-10-23")
print()
print("=== 逐週（看哪天賺的）===")
show("第一週", "2026-09-14", "2026-09-20")
show("第二週", "2026-09-21", "2026-09-27")
show("第三週", "2026-09-28", "2026-10-04")
show("第四週", "2026-10-05", "2026-10-11")
show("第五週", "2026-10-12", "2026-10-18")
show("第六週（到 10-23）", "2026-10-19", "2026-10-23")
print()
print("=== 判定需要的錢 ===")
need = 0.0646 * J["cap"] * 30 / 365
print(f"🟢 門檻 6.46% 需要 {need:.4f} USD；實得（②）{J['ali_usd']:.4f} USD；差 {need - J['ali_usd']:.4f} USD")
print(f"利用率整月 {J['util']:.1f}%（🔴 線 55%）")
