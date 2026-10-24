# 驗收：拿每一筆真實成交回頭跑成交規則，比「模擬等多久」與「實際等多久」（同 D049 的做法）
import sys, sqlite3
sys.path.insert(0, ".")
from datetime import datetime
from sim import Market, H, CST
from returns_lib import load, screen_keep_orphans
from core import hold_time

ledger, positions = load()
kept, _ = screen_keep_orphans(positions)
con = sqlite3.connect("file:snap/lending-20261024.sqlite3?mode=ro", uri=True)
offers = [(datetime.fromisoformat(t), float(r), int(dur)) for t, r, dur in con.execute(
    "select created_at, rate, duration from loan_offers where currency='USD' order by created_at")]
markets = {2: Market(2), 30: Market(30)}
for per in (2, 30):
    mk = markets[per]
    rows = []
    seen_open = set()
    for p in sorted(kept, key=lambda p: p["opened_at"]):
        if int(p["period"]) != per:
            continue
        opened = hold_time.parse_moment(p["opened_at"])
        if p["opened_at"][:16] in seen_open:   # 拆單只算一段
            continue
        seen_open.add(p["opened_at"][:16])
        rate = float(p["rate"])
        cands = [t for t, r, dur in offers if t <= opened and abs(r - rate) < 1e-10 and dur == per]
        if not cands:
            continue
        posted = cands[-1]
        actual = (opened - posted).total_seconds() / 3600
        i0 = mk.idx(int(posted.timestamp() * 1000))
        sim = None
        for i in range(i0, len(mk.hours)):
            c = mk.hours[i]
            if c and c["high"] >= rate:
                sim = i - i0 + 0.5
                break
        rows.append((posted, rate, actual, sim))
    tot_a = sum(a for _, _, a, s in rows if s is not None)
    tot_s = sum(s for _, _, a, s in rows if s is not None)
    print(f"天期 {per}：{len(rows)} 筆，實際等待合計 {tot_a:.1f}h、模擬 {tot_s:.1f}h → 總量比 {tot_s/tot_a:.2f}×")
    for posted, rate, a, s in rows:
        print(f"   {posted:%m-%d %H:%M}  {rate*36500:6.2f}%  實際 {a:7.2f}h  模擬 {s if s is None else round(s,1)}h")
