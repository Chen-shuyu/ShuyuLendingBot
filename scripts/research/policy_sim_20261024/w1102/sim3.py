# -*- coding: utf-8 -*-
"""跨天期成交模擬器（2026-11-01）。

市場結構（實測，見 PROGRESS 2026-11-01 續）：
- 負號成交＝放款掛單被吃；掃單照價格由低往高吃，**跨天期**。
- 借款方的掛單天期 B 只能吃天期 ≥ B 的放款單（現場：最佳買方 5.84%／天期 120，
  最佳賣方 4.75%／天期 2，兩邊不成交）。
→ 一張 (r, N) 的單，**天期 M ≤ N 的真掃單只要價格高過 r，就一定會先吃到它**。
  天期 M > N 的成交不算證據（那可能是 B > N 的買方，吃不到我們）。

這是假設，要用真實掛單驗收（validate3.py）。
"""
import bisect
import math
import os
import statistics
import sys
from array import array

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from td import CST, H, ROOT, fmt, ms  # noqa: E402

CACHE = os.path.join(ROOT, "w1102", "cache")
FEE = 0.85
CAPITAL = 348.0


class S:
    __slots__ = ("period", "mts", "rate", "amt", "hour_max", "hour_idx")

    def __init__(self, period, mts, rate, amt):
        self.period, self.mts, self.rate, self.amt = period, mts, rate, amt
        hm, hi = {}, {}
        for i, (t, r) in enumerate(zip(mts, rate)):
            h = t // H
            if h not in hi:
                hi[h] = i
                hm[h] = r
            elif r > hm[h]:
                hm[h] = r
        self.hour_max, self.hour_idx = hm, hi


def _load(kind, p):
    base = os.path.join(CACHE, f"{kind}_{p}")
    if not os.path.exists(base + ".mts"):
        return None
    m, r, a = array("q"), array("d"), array("d")
    n = os.path.getsize(base + ".mts") // 8
    with open(base + ".mts", "rb") as fh:
        m.fromfile(fh, n)
    with open(base + ".rate", "rb") as fh:
        r.fromfile(fh, n)
    with open(base + ".amt", "rb") as fh:
        a.fromfile(fh, n)
    return S(p, m, r, a)


def periods_in_cache(kind="clean"):
    out = []
    for f in os.listdir(CACHE):
        if f.startswith(kind + "_") and f.endswith(".mts"):
            out.append(int(f.split("_")[1].split(".")[0]))
    return sorted(out)


def load_all(kind="clean", periods=None):
    res = {}
    for p in (periods or periods_in_cache(kind)):
        s = _load(kind, p)
        if s:
            res[p] = s
    return res


def evidence(all_series, N, same_period_only=False):
    """一張天期 N 的單，哪些成交算證據。"""
    if same_period_only:
        return [all_series[N]] if N in all_series else []
    return [s for p, s in sorted(all_series.items()) if p <= N]


def find_fill(ev, r, a, b, need, cum=0.0, strict=True):
    """[a, b) 內第一個讓累積金額 ≥ need 的時刻（證據可以來自多個天期）。回傳 (時刻或 None, 累積)。"""
    if b <= a or not ev:
        return None, cum
    q = r * (1 + 1e-9) if strict else r * (1 - 1e-9)
    h, hb = a // H, (b - 1) // H
    while h <= hb:
        lo, hi = max(a, h * H), min(b, (h + 1) * H)
        hits = None
        for s in ev:
            hm = s.hour_max.get(h)
            if hm is None or hm < q:
                continue
            i = s.hour_idx[h]
            if lo > h * H:
                i = bisect.bisect_left(s.mts, lo)
            mts, rate, amt, n = s.mts, s.rate, s.amt, len(s.mts)
            while i < n and mts[i] < hi:
                if rate[i] >= q:
                    if hits is None:
                        hits = []
                    hits.append((mts[i], amt[i]))
                i += 1
        if hits:
            hits.sort()
            for t, x in hits:
                cum += x
                if cum >= need:
                    return t, cum
        h += 1
    return None, cum


def simulate(ev, prices, bag, start, end, segs=None, cap_h=None, shift=0, strict=True, tol_pct=2.0, need=CAPITAL, period_of=None):
    """prices：{小時: 日利率或 None}。回傳 (每段結果, 等待清單, 成交清單)。"""
    segs = segs or [(start, end)]
    interest = [0.0] * len(segs)
    lent = [0.0] * len(segs)
    fills = [0] * len(segs)
    waits, trades = [], []
    t, cyc = start, shift
    while t < end:
        h = t // H
        r = prices.get(h)
        if r is None:
            t = (h + 1) * H
            continue
        live, cum, cur, filled = r, 0.0, t, None
        while cur < end:
            nh = (cur // H + 1) * H
            ft, cum = find_fill(ev, live, cur, min(nh, end), need, cum, strict)
            if ft is not None:
                filled = ft
                break
            cur = nh
            if cur >= end:
                break
            r2 = prices.get(cur // H)
            if r2 is not None and abs(r2 - live) / r2 * 100 > tol_pct:
                live, cum = r2, 0.0
        if filled is None:
            break
        waits.append((filled - t) / H)
        hold = bag[cyc % len(bag)]
        cyc += 1
        if cap_h:
            hold = min(hold, cap_h)
        a, b = filled, min(filled + int(hold * H), end)
        trades.append((filled, live, hold))
        for k, (lo, hi) in enumerate(segs):
            x, y = max(a, lo), min(b, hi)
            if y > x:
                hrs = (y - x) / H
                interest[k] += live * hrs
                lent[k] += hrs
            if lo <= a < hi:
                fills[k] += 1
        t = filled + int(hold * H)
    out = []
    for k, (lo, hi) in enumerate(segs):
        w = (hi - max(lo, start)) / H
        if w <= 0:
            out.append(None)
            continue
        out.append({
            "net": interest[k] / w * 365 * 100 * FEE,
            "util": lent[k] / w * 100,
            "nominal": interest[k] / lent[k] * 365 * 100 if lent[k] else float("nan"),
            "fills": fills[k],
        })
    return out, waits, trades


def across(ev, prices, bag, start, end, segs, cap_h=None, strict=True, offsets=range(0, 48, 6), tol_pct=2.0, need=CAPITAL):
    runs, all_waits = [], []
    for k, off in enumerate(offsets):
        out, w, _ = simulate(ev, prices, bag, start + off * H, end, segs, cap_h, shift=k, strict=strict, tol_pct=tol_pct, need=need)
        runs.append(out)
        all_waits.extend(w)
    res = []
    for j in range(len(segs)):
        vals = [r[j] for r in runs if r[j] is not None]
        nets = [v["net"] for v in vals]
        noms = [v["nominal"] for v in vals if not math.isnan(v["nominal"])]
        res.append({
            "net": statistics.fmean(nets), "lo": min(nets), "hi": max(nets),
            "util": statistics.fmean(v["util"] for v in vals),
            "nominal": statistics.fmean(noms) if noms else float("nan"),
            "fills": statistics.fmean(v["fills"] for v in vals),
        })
    return res, all_waits
