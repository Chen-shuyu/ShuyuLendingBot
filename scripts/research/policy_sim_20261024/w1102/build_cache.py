# -*- coding: utf-8 -*-
"""把逐筆成交分類後存成二進位快取，讓模擬不必每次掃 SQLite。

分類（FRR 管道判準，用真實掛單的違規成交校準，見 violators2.py）：
  利率 x ≥ FRR − BAND 的負號成交，若前 WINDOW 內（同天期）沒有**真掃單**落在 [x − GAP, x]
  ——也就是沒有一路連續爬上來的階梯——就視為 FRR 管道，不算掃過簿子。
  真的掃單是照價格由低往高吃。階梯只看同天期：第一版看任何天期，10-14 23:57 那批 FRR 大單就被別的天期碰巧的成交放行了。

輸出 cache/：每個天期 clean_{p}.{mts,rate,amt}.bin（真掃單）、frr_{p}.*（FRR 管道）、pos_{p}.*（正號＝吃買方掛單）。
"""
import os
import sqlite3
import sys
from array import array
from bisect import bisect_left

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from td import FRR, H, ROOT, TRADES_DB, fmt

BAND = 0.30   # pp：FRR 下方多少以內算「可能是 FRR 管道」
GAP = 0.30    # pp：階梯允許的最大落差（真實成交掛價正下方 0.01～0.05pp 就有成交；10-14 那批 FRR 大單差 0.44～0.87pp）
WINDOW = 30_000  # ms（真掃單幾秒內一路往上吃；10-14 那批 FRR 大單離前一波掃單 39 秒）
OUT = os.path.join(ROOT, "w1102", "cache")
os.makedirs(OUT, exist_ok=True)


def main():
    frr = FRR()
    con = sqlite3.connect(f"file:{TRADES_DB}?mode=ro", uri=True)
    series = {}

    def put(kind, p, t, r, a):
        k = (kind, p)
        if k not in series:
            series[k] = (array("q"), array("d"), array("d"))
        s = series[k]
        s[0].append(t); s[1].append(r); s[2].append(a)

    band_pp = BAND / 36500
    gap_pp = GAP / 36500
    # 高價成交的滑動視窗（同天期各一份），只存 FRR − 2.5pp 以上的，冷市場時很少，查階梯才快
    hi = {}
    last_h, f = None, 0.0
    n = kept = dropped = pos = 0
    for t, a, r, p in con.execute("select mts, amount, rate, period from t order by mts, id"):
        n += 1
        h = t // H
        if h != last_h:
            f, last_h = frr.at(t), h
        if a > 0:
            put("pos", p, t, r, a)
            pos += 1
            continue
        amt = -a
        lo = f - band_pp
        hi_t, hi_r = hi.setdefault(p, (array("q"), array("d")))
        is_clean = True
        if r >= lo:
            # 階梯要連續：前 WINDOW 內要有同天期的真掃單落在 [r − GAP, r]（FRR 管道不算，所以它們接不起來）
            i = bisect_left(hi_t, t - WINDOW)
            floor = r - gap_pp
            is_clean = False
            while i < len(hi_t):
                if floor <= hi_r[i] <= r:
                    is_clean = True
                    break
                i += 1
        if is_clean:
            put("clean", p, t, r, amt); kept += 1
            if r >= lo - gap_pp:
                hi_t.append(t); hi_r.append(r)
                if len(hi_t) > 50_000:
                    cut = bisect_left(hi_t, t - WINDOW)
                    del hi_t[:cut]; del hi_r[:cut]
        else:
            put("frr", p, t, r, amt); dropped += 1
    con.close()
    for (kind, p), (m, rr, am) in series.items():
        base = os.path.join(OUT, f"{kind}_{p}")
        with open(base + ".mts", "wb") as fh:
            m.tofile(fh)
        with open(base + ".rate", "wb") as fh:
            rr.tofile(fh)
        with open(base + ".amt", "wb") as fh:
            am.tofile(fh)
    print(f"總 {n} 筆；負號真掃單 {kept}、FRR 管道 {dropped}、正號 {pos}；天期種類 {len({k[1] for k in series})}", flush=True)


if __name__ == "__main__":
    main()
