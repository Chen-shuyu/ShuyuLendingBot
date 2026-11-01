import json, sys
from datetime import datetime, timezone, timedelta
PROJECT = "/workspace/projects/LendingBot/ShuyuLendingBot"
sys.path.insert(0, PROJECT)
from config import settings
from strategies.expected_value import ExpectedValueStrategy
CST = timezone(timedelta(hours=8))
d = sys.argv[1]
def candles(path):
    rows = sorted(json.load(open(path)), key=lambda r: r[0])
    return [{"mts": int(r[0]), "open": float(r[1]), "close": float(r[2]), "high": float(r[3]), "low": float(r[4]), "volume": abs(float(r[5]))} for r in rows if float(r[3]) > 0]
raw = json.load(open(f"{d}/t.json"))
trades = sorted([{"mts": int(r[1]), "amount": abs(float(r[2])), "rate": float(r[3]), "period": int(r[4])} for r in raw if float(r[3]) > 0], key=lambda x: x["mts"])
span = (trades[-1]["mts"] - trades[0]["mts"]) / 3600000
frr = float(json.load(open(f"{d}/tk.json"))[0])
print(f"FRR {frr*36500:.3f}%，最近一萬筆涵蓋 {span:.2f} 小時，最新成交 {datetime.fromtimestamp(trades[-1]['mts']/1000,CST):%m-%d %H:%M}")
cfg = settings.load_config(f"{PROJECT}/config.yaml") or {}
for period, f in ((2, "c2.json"), (7, "c7.json")):
    cfg2 = json.loads(json.dumps(cfg))
    cfg2["strategy"]["offer_period"] = period
    st = ExpectedValueStrategy(cfg2)
    cs = candles(f"{d}/{f}")
    print(f"\n=== 天期 {period}：K 線 {len(cs)} 根，{datetime.fromtimestamp(cs[0]['mts']/1000,CST):%Y-%m-%d %H時} ～ {datetime.fromtimestamp(cs[-1]['mts']/1000,CST):%Y-%m-%d %H時}")
    plans = st.build_offer_plan(348.11, frr, [], trades, cs)
    win = cs[-st.ev_window_hours:]
    print(f"  選價窗 {st.ev_window_hours} 根，{datetime.fromtimestamp(win[0]['mts']/1000,CST):%m-%d %H時} 起；窗內高點前五 {[round(x, 2) for x in sorted((c['high']*36500 for c in win), reverse=True)[:5]]}")
    same = [t for t in trades if t["period"] == period]
    print(f"  同天期成交 {len(same)} 筆（門檻 50）")
    mr = st.market_rate(trades)
    base = st.choose_rate(cs)
    print(f"  常態成交價 {mr*36500 if mr else None}；× {st.market_floor_pct} = {mr*st.market_floor_pct*36500 if mr else None}；模型選價 {base*36500 if base else None}；地板 {st.minimum_rate*36500:.2f}")
    print("  第一輪計畫：", [(round(p.amount,2), round(p.rate*36500,3), p.duration) for p in plans], "略過原因：", st.last_skip_reason)
    print("  選中：", st.last_chosen if not hasattr(st.last_chosen, "__dict__") else vars(st.last_chosen))
