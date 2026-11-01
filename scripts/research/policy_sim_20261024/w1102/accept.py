# 最終驗收：用新引擎從頭跑真實歷史（模型定價＋樣本袋持有），跟實際成績比。
import sys, json, statistics
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from sim3 import *
import prices as PR
ROOTD = ROOT + "/"
raw = json.load(open(ROOTD + "hold_samples.json"))
dedup, seen = [], set()
for r, h in raw["2"]:
    key = round(h, 1)
    if key == 11.6 and key in seen:
        continue
    seen.add(key); dedup.append(h)
BAG2, BAG30 = dedup, [h for r, h in raw["30"]]
clean = load_all("clean"); pos = load_all("pos")
def ev_of(N, use_pos):
    e = evidence(clean, N)
    if use_pos:
        e = e + evidence(pos, N)
    return e
SEG = {"A": (ms(2026,8,17), ms(2026,9,14)), "B": (ms(2026,9,14), ms(2026,10,14)), "C": (ms(2026,10,14), ms(2026,10,24)), "D": (ms(2026,10,25), ms(2026,11,1))}
sw = [(ms(2026,8,1), 48), (ms(2026,8,30,23,30), 12)]
print("算掛價表…", flush=True)
tA = PR.table(2, 48, "prod", 8.0, hold_switch=sw)
tB = PR.table(30, 48, "prod", 8.0)
tD = PR.table(2, 12, "prod", 5.0)
cases = [("窗 A 天期 2（當時設定）", 2, tA, BAG2, "A", 48, 6.46, 86.0, 8.83),
         ("窗 B 天期 30", 30, tB, BAG30, "B", None, 6.03, 67.7, 10.48),
         ("窗 C 天期 30（10-14～10-23）", 30, tB, BAG30, "C", None, 1.95, 21.0, 10.95),
         ("窗 D 天期 2 新設定", 2, tD, BAG2, "D", 48, 4.08, 77.8, 5.98)]
for name, N, t, bag, sk, cap, act, au, an in cases:
    a, b = SEG[sk]
    print(f"\n{name}：實際 {act}%／利用率 {au}%／名目 {an}%")
    for label, strict, up, same in (("嚴格 > ，天期≤N", True, False, False), ("寬鬆 ≥ ，天期≤N", False, False, False), ("嚴格 > ，同天期", True, False, True), ("嚴格 > ，天期≤N＋買方掛單", True, True, False)):
        ev = evidence(clean, N, True) if same else ev_of(N, up)
        r, w = across(ev, t, bag, a, b, [(a, b)], cap_h=cap, strict=strict, offsets=range(0, 48, 3) if sk != "D" else range(0, 24, 2))
        r = r[0]
        print(f"   {label:24s} 模擬 {r['net']:5.2f}%（{r['lo']:5.2f}～{r['hi']:5.2f}） 利用率 {r['util']:5.1f}% 名目 {r['nominal']:5.2f}% 成交 {r['fills']:.1f} 次 → 差 {r['net']-act:+.2f}pp", flush=True)
