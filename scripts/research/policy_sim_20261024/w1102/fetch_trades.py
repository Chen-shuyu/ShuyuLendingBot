# 背景抓 fUSD 公開逐筆成交進 SQLite（可續傳）。每 5 秒一頁；遇到限流或錯誤就退避，不硬打——機器人共用這個 IP。
import json, os, sqlite3, subprocess, sys, time
from datetime import datetime, timezone, timedelta
CST = timezone(timedelta(hours=8))
DB = "dl_trades/trades.sqlite3"
TMP = "dl_trades/page.json"
START = int(datetime(2026, 8, 8, tzinfo=CST).timestamp() * 1000)
END = int(datetime(2026, 11, 1, 15, tzinfo=CST).timestamp() * 1000)
con = sqlite3.connect(DB, timeout=120)
con.execute("pragma journal_mode=wal")
con.execute("create table if not exists t (id integer primary key, mts integer, amount real, rate real, period integer)")
con.execute("create index if not exists t_mts on t(mts)")
row = con.execute("select max(mts) from t").fetchone()
cur = row[0] if row and row[0] else START
pages = 0; backoff = 5
while cur < END:
    url = f"https://api-pub.bitfinex.com/v2/trades/fUSD/hist?start={cur}&end={END}&limit=10000&sort=1"
    rc = subprocess.run(["curl", "-s", "--max-time", "40", "-o", TMP, "-w", "%{http_code}", url], capture_output=True, text=True)
    code = rc.stdout.strip()
    try:
        data = json.load(open(TMP))
    except Exception:
        data = None
    if code != "200" or not isinstance(data, list) or (data and not isinstance(data[0], list)):
        print(f"{datetime.now():%H:%M:%S} 非預期回應 http={code} body={str(data)[:120]}，退避 {backoff}s", flush=True)
        time.sleep(backoff); backoff = min(backoff * 2, 300)
        continue
    backoff = 5
    if not data:
        print("空頁，結束", flush=True); break
    with con:
        con.executemany("insert or ignore into t values (?,?,?,?,?)", [(x[0], x[1], x[2], x[3], x[4]) for x in data])
    last = data[-1][1]
    pages += 1
    if pages % 10 == 0:
        n = con.execute("select count(*) from t").fetchone()[0]
        print(f"{datetime.now():%H:%M:%S} 第 {pages} 頁，已到 {datetime.fromtimestamp(last/1000, CST):%m-%d %H:%M}，共 {n} 筆", flush=True)
    if last <= cur and len(data) >= 10000:
        # 同一毫秒超過一頁（幾乎不可能）：往前跳 1ms 免得卡死
        cur += 1
    else:
        cur = last
    if len(data) < 10000:
        print("最後一頁，結束", flush=True); break
    time.sleep(5)
print("完成", con.execute("select count(*), min(mts), max(mts) from t").fetchone(), flush=True)
