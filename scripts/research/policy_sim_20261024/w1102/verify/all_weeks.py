# 驗收：用研究的 425 萬筆跑過去每一週（設定照當時實際），看判準的表現。不碰網路、不寫 DB。
import json, os, sqlite3, sys, time
from datetime import date, datetime, timedelta
S = sys.argv[1]
sys.path.insert(0, "/workspace/projects/LendingBot/ShuyuLendingBot")
sys.path.insert(0, S + "/w1102")
from config import settings
from core import tape as T, weekly as W
from utils import clock
DB = S + "/snap/lending-latest.sqlite3"
TRADES = S + "/dl_trades/trades.sqlite3"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); con.row_factory = sqlite3.Row
earn = [dict(r) for r in con.execute("select date, interest, principal_avg from earnings_daily where currency='USD'")]
pos = [dict(r) for r in con.execute("select * from funding_positions where currency='USD'")]
off = [dict(r) for r in con.execute("select created_at, rate, duration, amount, status from loan_offers where status='submitted' order by created_at")]
frr = T.FrrSeries([(int(datetime.fromisoformat(r[0]).timestamp()*1000), r[1]) for r in con.execute("select captured_at, frr from market_snapshots where frr is not null")])
cfg = settings.load_config("/workspace/projects/LendingBot/ShuyuLendingBot/config.yaml")
tcon = sqlite3.connect(f"file:{TRADES}?mode=ro", uri=True)
now = datetime(2026, 11, 1, 15, 0, tzinfo=clock.get_timezone())
# 當時實際的設定
def setting_of(first):
    if first < date(2026, 8, 30): return W.Setting("當時 p2 P48 f8", 2, 48.0, 0.00021918)
    if first < date(2026, 9, 13): return W.Setting("當時 p2 P12 f8", 2, 12.0, 0.00021918)
    if first < date(2026, 10, 25): return W.Setting("當時 p30 P48 f8", 30, 48.0, 0.00021918)
    return W.Setting("當時 p2 P12 f5", 2, 12.0, 0.00013699)
candle_cache = {}
def candles_for(period):
    # 用逐筆組（驗過與 K 線 243/243 一致）
    if period in candle_cache: return candle_cache[period]
    hi = {}
    for m, r in tcon.execute("select mts, rate from t where period=?", (period,)):
        h = m // T.HOUR_MS
        if r > hi.get(h, 0): hi[h] = r
    candle_cache[period] = [{"mts": h*T.HOUR_MS, "high": v, "close": v} for h, v in sorted(hi.items())]
    return candle_cache[period]
weeks = []
d = date(2026, 8, 23)
while d + timedelta(days=6) <= date(2026, 10, 31):
    weeks.append(d); d += timedelta(days=7)
rows = []
lost = None
for first in weeks:
    last = first + timedelta(days=6)
    s = int(W.midnight(first).timestamp()*1000); e = int((W.midnight(last)+timedelta(days=1)).timestamp()*1000)
    t0 = time.time()
    trades = tcon.execute("select id, mts, amount, rate, period from t where mts>=? and mts<? order by mts,id", (s-6*T.HOUR_MS, e)).fetchall()
    tape = T.build_tape(trades, frr.at)
    st = setting_of(first)
    cdl = {p: candles_for(p) for p in {st.offer_period, 2}}
    r = W.build_report(W.WeeklyInputs(config=cfg, tape=tape, candles=cdl, earning_rows=earn, position_rows=pos, offer_rows=off, frr_at=frr.at, first=first, last=last, now=now, setting=st, backup_last_ok_at=now.isoformat(), lost_last_week=lost))
    lost = r.lost_to_previous
    a = r.actual
    print(f"{first:%m-%d} {st.label:18s} 帳本 {a.earned_pct:5.2f} 部位 {a.position_pct:5.2f}（差 {a.earned_pct-a.position_pct:+.2f}）利用率 {a.utilization_pct:5.1f} 名目 {a.nominal_pct or 0:5.2f} | 重播 {r.replay.net_pct:5.2f}（差 {a.position_pct-r.replay.net_pct:+.2f}，{r.replay.fills}/{r.replay.real_fills} 次）| 現行 {r.current.net_pct:5.2f}（差 {a.earned_pct-r.current.net_pct:+.2f}）| 上一版 {r.previous.net_pct if r.previous else float('nan'):5.2f} | 8%參考 {r.fixed_reference.net_pct:5.2f} | 最佳固定 {r.best_fixed_annual:g}%→{r.best_fixed.net_pct:5.2f} | {r.level} {time.time()-t0:.0f}s", flush=True)
    rows.append(r)
w1 = rows[-1]
print(); print(W.format_report(w1)); print(); print(W.line_headline(w1)); print(json.dumps(W.line_fields(w1), ensure_ascii=False, indent=1))
