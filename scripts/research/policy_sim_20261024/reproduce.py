# 重現 D072 第二節／第五節已記錄的數字（還原到 10-10 23:47 的資料狀態）
import sys
sys.path.insert(0, ".")
from datetime import datetime, timedelta
from returns_lib import *

ledger, positions = load()
T = datetime(2026, 10, 10, 23, 47, tzinfo=TZ)
# 還原資料狀態：之後才開的拿掉、之後才結清的改回未結清；帳本只留到 10-10
pos_then = []
for p in positions:
    o = hold_time.parse_moment(p["opened_at"]) or hold_time.parse_moment(p["first_seen_at"])
    if o > T:
        continue
    q = dict(p)
    c = hold_time.parse_moment(q["closed_at"])
    if c and c > T:
        q["closed_at"] = None
    pos_then.append(q)
led_then = {k: v for k, v in ledger.items() if k <= d("2026-10-10")}

doc = {  # (util, nominal, cur, ali, pos)
    ("2026-09-14", "2026-09-19"): (56.5, 10.86, 5.13, 5.39, 5.22),
    ("2026-09-20", "2026-09-27"): (81.6, 10.44, 7.42, 7.35, 7.24),
    ("2026-09-28", "2026-10-04"): (90.9, 10.26, 7.92, 7.92, 7.93),
    ("2026-10-05", "2026-10-10"): (65.7, 10.58, 7.04, 5.59, 5.91),
    ("2026-10-05", "2026-10-08"): (98.4, 10.58, 9.00, 8.39, 8.85),
    ("2026-09-14", "2026-10-10"): (74.9, 10.48, 6.96, 6.67, 6.68),
}
for rule in ("aligned", "same"):
    print(f"--- principal rule = {rule} ---")
    for (s, e), want in doc.items():
        for name, ps in (("project", screen_project(pos_then)), ("orphans", screen_keep_orphans(pos_then)[0])):
            w = window(led_then, ps, d(s), d(e), T, principal_rule=rule)
            got = (w["util"], w["nominal"], w["cur"], w["ali"], w["pos"])
            diff = max(abs(a - b) for a, b in zip(got, want))
            print(f"{s}~{e} {name:8s} util {w['util']:5.1f} nom {w['nominal']:6.2f} cur {w['cur']:5.2f} ali {w['ali']:5.2f} pos {w['pos']:5.2f}  doc {want}  maxdiff {diff:.3f}")

# 短天期整月 08-17～09-13：① 6.21 ／ ② 6.46 ／ ③ 6.45
print("--- short term month ---")
for rule in ("aligned", "same"):
    for name, ps in (("project", screen_project(pos_then)), ("orphans", screen_keep_orphans(pos_then)[0])):
        w = window(led_then, ps, d("2026-08-17"), d("2026-09-13"), T, principal_rule=rule)
        print(rule, name, f"util {w['util']:.1f} nom {w['nominal']:.2f} cur {w['cur']:.2f} ali {w['ali']:.2f} pos {w['pos']:.2f} cap {w['cap']:.2f}")
