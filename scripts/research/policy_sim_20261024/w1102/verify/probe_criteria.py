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
now = datetime(2026, 11, 1, 15, 0, tzinfo=clock.get_timezone())
screen = hold_time.screen_positions(pos)
kept = screen.kept
offers_all = None
cc = {}
def candles_for(period):
    if period in cc: return cc[period]
    hi = {}
    for m, r in tcon.execute("select mts, rate from t where period=?", (period,)):
        h = m // T.HOUR_MS
        if r > hi.get(h, 0): hi[h] = r
    cc[period] = [{"mts": h*T.HOUR_MS, "high": v, "close": v} for h, v in sorted(hi.items())]
    return cc[period]
def load(first, last):
    s = int(W.midnight(first).timestamp()*1000); e = int((W.midnight(last)+timedelta(days=1)).timestamp()*1000)
    trades = tcon.execute("select id, mts, amount, rate, period from t where mts>=? and mts<? order by mts,id", (s-6*T.HOUR_MS, e)).fetchall()
    return s, e, trades

print("=== 一、負控制：判準 1 會不會喊（把規則弄壞，看重播會不會偏）===")
for first in (date(2026,10,11), date(2026,10,18), date(2026,9,13), date(2026,10,25)):
    last = first + timedelta(days=6)
    s, e, trades = load(first, last)
    good = T.build_tape(trades, frr.at)
    noflt = T.build_tape(trades, lambda t: None)   # 不分 FRR 管道（等同 K 線的盲點）
    offers = W.real_offers(off, kept, e, int(now.timestamp()*1000))
    a = W.actual_numbers(earn, kept, first, last, now)
    now_ms = int(now.timestamp()*1000)
    r_good = W.replay_real_offers(good, offers, kept, s, e, a.capital, 49.0, now_ms)
    r_bad = W.replay_real_offers(noflt, offers, kept, s, e, a.capital, 49.0, now_ms)
    # 另一種壞法：把真掃單的量砍掉一半的時間（資料缺一段）— 取前半週的成交就停
    half = T.build_tape([t for t in trades if t[1] < s + (e-s)//2], frr.at)
    r_cut = W.replay_real_offers(half, offers, kept, s, e, a.capital, 49.0, now_ms)
    c_good, c_bad, c_cut = W.check_replay(a, r_good), W.check_replay(a, r_bad), W.check_replay(a, r_cut)
    print(f"{first:%m-%d} 部位 {a.position_pct:5.2f}｜規則正常 {r_good.net_pct:5.2f} {c_good.level:8s} {r_good.fills}/{r_good.real_fills}｜不篩 FRR 管道 {r_bad.net_pct:5.2f} {c_bad.level:8s} {r_bad.fills}/{r_bad.real_fills}｜後半週資料沒了 {r_cut.net_pct:5.2f} {c_cut.level:8s} {r_cut.fills}/{r_cut.real_fills}")

print("\n=== 二、D074 對照組 10-25～10-31：為什麼是 1.12% 不是 0 ===")
first, last = date(2026,10,25), date(2026,10,31)
s, e, trades = load(first, last)
tp = T.build_tape(trades, frr.at)
st8 = W.strategy_for(cfg, W.LEGACY_SETTING)
p8 = W.hourly_prices(st8, tp, candles_for(2), s, e, 348.09, frr.at)
hrs = [(h, v) for h, v in sorted(p8.items()) if v is not None]
print("有計畫的小時數", len(hrs), "／", len(p8))
for h, v in hrs[:12]:
    print(" ", datetime.fromtimestamp(h*3600, clock.get_timezone()).strftime("%m-%d %H時"), round(v*36500, 3))
print("機器人當時的快照（10-30 20 時之後，每 2 小時一列）：")
for r in con.execute("select captured_at, frr*36500 f, trade_rate_weighted_median*36500 m, trade_rate_median*36500 md, trade_sample_size n from market_snapshots where captured_at>='2026-10-31T12' and captured_at<'2026-11-01T01' order by captured_at") if False else []:
    pass
cols = [r[1] for r in con.execute("pragma table_info(market_snapshots)")]
print(" 欄位", [c for c in cols if 'trade' in c])

print("\n=== 三、判準 2 的誤報率：如果模型完全正確，單週只因運氣偏離平均多少？（24 條路徑各當一次「實際」）===")
samples = W.hold_samples(screen, now)
print("樣本袋：", {k: (len(v), round(statistics.fmean(v),1)) for k, v in samples.items()})
weeks = []
d = date(2026,8,23)
while d + timedelta(days=6) <= date(2026,10,31):
    weeks.append(d); d += timedelta(days=7)
for per, setting in ((2, W.PREVIOUS_SETTING), (7, W.Setting("p7", 7, 12.0, 0.00013699))):
    holds, label = W.pick_holds(samples, per)
    out = []
    tot = over = over_and_outside = 0
    for first in weeks:
        last = first + timedelta(days=6)
        s, e, trades = load(first, last)
        tp = T.build_tape(trades, frr.at)
        prices = W.hourly_prices(W.strategy_for(cfg, setting), tp, candles_for(per), s, e, 348.0, frr.at)
        runs = []
        for k, off_h in enumerate(range(0, 24)):
            runs.append(T.simulate_path(tp.evidence(per), prices, holds, s + off_h*T.HOUR_MS, e, 348.0, cap_hours=per*24.0, rotate=k).net_pct)
        mean = statistics.fmean(runs)
        dev = [abs(x-mean) for x in runs]
        tot += len(runs); over += sum(1 for x in dev if x > 1.0)
        out.append(f"{first:%m-%d} 平均 {mean:5.2f} 範圍 {min(runs):5.2f}～{max(runs):5.2f} >1pp {sum(1 for x in dev if x>1.0):2d}/24")
    print(f"天期 {per}（{label}）：純運氣偏離 > 1pp 的比例 {over/tot*100:.0f}%")
    for x in out: print("   ", x)
