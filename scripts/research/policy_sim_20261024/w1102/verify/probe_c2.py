import json, sqlite3, statistics, sys, time
from datetime import date, datetime, timedelta
S = sys.argv[1]
sys.path.insert(0, "/workspace/projects/LendingBot/ShuyuLendingBot")
from config import settings
from core import tape as T, weekly as W, hold_time
from utils import clock
DB = S + "/snap/lending-latest.sqlite3"; TRADES = S + "/dl_trades/trades.sqlite3"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = sqlite3.Row
earn = [dict(r) for r in con.execute("select date, interest, principal_avg from earnings_daily where currency='USD'")]
pos = [dict(r) for r in con.execute("select * from funding_positions where currency='USD'")]
off = [dict(r) for r in con.execute("select created_at, rate, duration, amount, status from loan_offers where status='submitted' order by created_at")]
frr = T.FrrSeries([(int(datetime.fromisoformat(r[0]).timestamp()*1000), r[1]) for r in con.execute("select captured_at, frr from market_snapshots where frr is not null")])
cfg = settings.load_config("/workspace/projects/LendingBot/ShuyuLendingBot/config.yaml")
tcon = sqlite3.connect(f"file:{TRADES}?mode=ro", uri=True)
now = datetime(2026, 11, 1, 15, 0, tzinfo=clock.get_timezone()); now_ms = int(now.timestamp()*1000)
screen = hold_time.screen_positions(pos); kept = screen.kept
print("=== 快照：10-28 那三小時市場真的到 ~10%？===")
for r in con.execute("select captured_at, frr*36500 f, trade_rate_median*36500 md, trade_rate_weighted_median*36500 w, trade_rate_max*36500 mx, trade_period_rates_json j, trade_period_counts_json c from market_snapshots where captured_at>='2026-10-28T03:20' and captured_at<'2026-10-28T07:10' order by captured_at"):
    j = json.loads(r["j"] or "{}"); c = json.loads(r["c"] or "{}")
    print(" ", r["captured_at"][5:16], "FRR", round(r["f"],2), "中位", round(r["md"],2), "加權中位(全天期)", round(r["w"],2), "天期2常態", round(j.get("2",0)*36500,2), "筆數", c.get("2"), "×0.85=", round(j.get("2",0)*36500*0.85,2))
cc = {}
def candles_for(period):
    if period in cc: return cc[period]
    hi = {}
    for m, r in tcon.execute("select mts, rate from t where period=?", (period,)):
        h = m // T.HOUR_MS
        if r > hi.get(h, 0): hi[h] = r
    cc[period] = [{"mts": h*T.HOUR_MS, "high": v, "close": v} for h, v in sorted(hi.items())]
    return cc[period]
def setting_of(first):
    if first < date(2026, 8, 30): return W.Setting("p2 P48 f8", 2, 48.0, 0.00021918)
    if first < date(2026, 9, 13): return W.Setting("p2 P12 f8", 2, 12.0, 0.00021918)
    if first < date(2026, 10, 25): return W.Setting("p30 P48 f8", 30, 48.0, 0.00021918)
    return W.Setting("p2 P12 f5", 2, 12.0, 0.00013699)
print("\n=== 判準 2：週初帶進來的部位算進去、再加上實際持有（差＝實得−模擬，門檻 1pp）===")
d = date(2026,8,23)
while d + timedelta(days=6) <= date(2026,10,31):
    first, last = d, d + timedelta(days=6); d += timedelta(days=7)
    s = int(W.midnight(first).timestamp()*1000); e = int((W.midnight(last)+timedelta(days=1)).timestamp()*1000)
    trades = tcon.execute("select id, mts, amount, rate, period from t where mts>=? and mts<? order by mts,id", (s-6*T.HOUR_MS, e)).fetchall()
    tp = T.build_tape(trades, frr.at)
    st = setting_of(first)
    a = W.actual_numbers(earn, kept, first, last, now)
    samples = W.hold_samples(screen, W.midnight(last)+timedelta(days=1))
    bag, label = W.pick_holds(samples, st.offer_period)
    prices = W.hourly_prices(W.strategy_for(cfg, st), tp, candles_for(st.offer_period), s, e, a.capital, frr.at)
    ev = tp.evidence(st.offer_period); cap = st.offer_period*24.0
    plain = T.across_starts(ev, prices, bag, s, e, a.capital, cap_hours=cap)
    # 週初帶進來的
    rows = []
    for p in kept:
        sp = W._position_span_ms(p, now_ms)
        if sp and sp[0] < s < sp[1]: rows.append((p, sp))
    carried = None
    if rows:
        carried = T.Carried(rate=sum(float(p["amount"])*float(p["rate"]) for p,_ in rows)/a.capital, share=sum(float(p["amount"]) for p,_ in rows)/a.capital, until_ms=max(sp[1] for _,sp in rows))
    cond = T.across_starts(ev, prices, bag, s, e, a.capital, cap_hours=cap, carried=carried)
    offers = W.real_offers(off, kept, e, now_ms)
    real_holds = [o.hold_hours for o in offers if o.filled_at_ms is not None and s <= o.filled_at_ms < e]
    seq = real_holds + bag
    act = T.across_starts(ev, prices, seq, s, e, a.capital, cap_hours=None, carried=carried, rotate_holds=False)
    fl = lambda x: "✗" if abs(x) > 1 else "✓"
    g1, g2, g3 = a.earned_pct-plain.net_pct, a.earned_pct-cond.net_pct, a.earned_pct-act.net_pct
    print(f"{first:%m-%d} {st.label:11s} 實得 {a.earned_pct:5.2f} ｜原本 {plain.net_pct:5.2f} 差 {g1:+5.2f}{fl(g1)} ｜算進帶入部位 {cond.net_pct:5.2f} 差 {g2:+5.2f}{fl(g2)}（{cond.low_pct:.2f}～{cond.high_pct:.2f}）｜再用實際持有 {act.net_pct:5.2f} 差 {g3:+5.2f}{fl(g3)} ｜帶入 {len(rows)} 筆、實際成交 {len(real_holds)} 筆 持有 {[round(x,1) for x in real_holds]}", flush=True)
