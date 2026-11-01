# 探針：拿我們自己的真實成交對公開逐筆成交，看我們的單在公開資料裡長什麼樣（正負號、利率、拆幾筆）
import json, sqlite3, time, subprocess, sys
from datetime import datetime, timezone, timedelta
CST = timezone(timedelta(hours=8))
OUT = "dl_trades_probe/"
def fetch(start, end, limit=10000):
    url = f"https://api-pub.bitfinex.com/v2/trades/fUSD/hist?start={start}&end={end}&limit={limit}&sort=1"
    path = f"{OUT}{start}.json"
    subprocess.run(["curl", "-s", "--max-time", "30", url, "-o", path], check=True)
    return json.load(open(path))
c = sqlite3.connect("file:snap/lending-latest.sqlite3?mode=ro", uri=True)
rows = c.execute("select position_id, kind, amount, rate, period, opened_at from funding_positions where kind='credit' and opened_at >= '2026-09-14' order by opened_at").fetchall()
for pid, kind, amt, rate, per, op in rows:
    t = int(datetime.fromisoformat(op).timestamp()*1000)
    trades = fetch(t-90_000, t+90_000)
    time.sleep(4)
    same_p = [x for x in trades if x[4] == per]
    match = [x for x in trades if x[4] == per and abs(x[3]-rate) < 1e-9]
    print(f"{op[5:16]} {pid} {amt:.2f} @ {rate*36500:.3f}% p{per}：窗內 {len(trades)} 筆、同天期 {len(same_p)} 筆、同價同天期 {len(match)} 筆")
    for x in match[:8]:
        print(f"     {datetime.fromtimestamp(x[1]/1000, CST):%H:%M:%S} 金額 {x[2]:>10.2f} 利率 {x[3]*36500:.3f}%")
    near = [x for x in same_p if abs(x[1]-t) < 30000 and x not in match][:4]
    for x in near:
        print(f"     (同天期其他) {datetime.fromtimestamp(x[1]/1000, CST):%H:%M:%S} 金額 {x[2]:>10.2f} 利率 {x[3]*36500:.3f}%")
    sys.stdout.flush()
