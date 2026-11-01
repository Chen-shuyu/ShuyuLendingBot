# -*- coding: utf-8 -*-
"""每小時掛價表（快取成 json）。兩種模式：

prod：「只把 offer_period 改成 N」——正式環境的程式原封不動：K 線高點含 FRR 管道（同天期、最後 240 根存在的 K，
      168 根的窗）、常態成交價含所有成交（金額加權中位數），同天期成交 < 50 筆就不掛（地雷④）。
clean：改良版——高點只看真掃單（跨天期，天期 ≤ N），168 小時的窗；常態價也只看真掃單。
"""
import bisect
import json
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim3 import H, ROOT, S, evidence, load_all, ms  # noqa: E402

PROJECT = "/workspace/projects/LendingBot/ShuyuLendingBot"
sys.path.insert(0, PROJECT)
OUT = os.path.join(ROOT, "w1102", "price_tables")
os.makedirs(OUT, exist_ok=True)
GRID_START = ms(2026, 8, 12)
GRID_END = ms(2026, 11, 1)
TRADE_WINDOW_H = 6
MIN_SAMPLES = 50

_CLEAN = _FRR = _POS = None


def _init():
    global _CLEAN, _FRR, _POS
    if _CLEAN is None:
        _CLEAN = load_all("clean")
        _FRR = load_all("frr")
        _POS = load_all("pos")


def make_strategy(P, window=168):
    from pathlib import Path

    from config import settings
    from strategies.expected_value import ExpectedValueStrategy

    cfg = settings.load_config(str(Path(PROJECT) / "config.yaml")) or {}
    st = ExpectedValueStrategy(cfg)
    st.assumed_hold_hours = float(P)
    st.ev_window_hours = int(window)
    return st


def weighted_median(pairs):
    pairs.sort()
    half = sum(a for _, a in pairs) / 2
    cum = 0.0
    for r, a in pairs:
        cum += a
        if cum >= half:
            return r
    return pairs[-1][0] if pairs else None


def window_rows(series_list, a, b, cap=4000):
    rows = []
    for s in series_list:
        if s is None:
            continue
        i, j = bisect.bisect_left(s.mts, a), bisect.bisect_left(s.mts, b)
        if j <= i:
            continue
        step = max(1, (j - i) // cap)
        rows.extend((s.rate[k], s.amt[k]) for k in range(i, j, step))
    return rows


def table(period, P, mode, floor_pct=5.0, hold_switch=None, window=168):
    """回傳 {小時: 日利率或 None}。"""
    _init()
    st = make_strategy(P, window)
    floor = floor_pct / 36500
    hours = range(GRID_START // H, GRID_END // H)
    out = {}
    if mode == "prod":
        hi = {}
        for d in (_CLEAN, _FRR, _POS):
            s = d.get(period)
            if s:
                for h, v in s.hour_max.items():
                    if v > hi.get(h, 0.0):
                        hi[h] = v
        hs = sorted(hi)
        same = [_CLEAN.get(period), _FRR.get(period), _POS.get(period)]
    else:
        hi = {}
        for s in evidence(_CLEAN, period):
            for h, v in s.hour_max.items():
                if v > hi.get(h, 0.0):
                    hi[h] = v
        hs = None
        same = evidence(_CLEAN, period)
    last_key, base = None, None
    for h in hours:
        if hold_switch:
            for when, p in hold_switch:
                if h * H >= when:
                    st.assumed_hold_hours = float(p)
        if mode == "prod":
            idx = bisect.bisect_left(hs, h)
            sel = hs[max(0, idx - 240):idx]
            key = (sel[-1] if sel else None, st.assumed_hold_hours)
            if key != last_key:
                candles = [{"mts": x * H, "high": hi[x], "close": hi[x]} for x in sel]
                base = st.choose_rate(candles) if len(candles) >= st.ev_min_candles else None
                last_key = key
        else:
            candles = [{"mts": x * H, "high": hi.get(x, 0.0), "close": 0.0} for x in range(h - 240, h)]
            base = st.choose_rate(candles)
        if base is None:
            out[h] = None
            continue
        rows = window_rows(same, (h - TRADE_WINDOW_H) * H, h * H)
        if mode == "prod":
            if len(rows) < MIN_SAMPLES:
                out[h] = None
                continue
            mr = weighted_median(rows)
        else:
            mr = weighted_median(rows) if len(rows) >= 5 else None
        rate = max(base, mr * st.market_floor_pct) if mr else base
        rate = st._quantize(rate)
        out[h] = rate if rate >= floor else None
    return out


def path(period, P, mode, floor_pct, tag=""):
    return os.path.join(OUT, f"{mode}_p{period}_P{P}_f{floor_pct:g}{tag}.json")


def build(args):
    period, P, mode, floor_pct = args
    p = path(period, P, mode, floor_pct)
    if os.path.exists(p):
        return p
    t = table(period, P, mode, floor_pct)
    with open(p, "w") as fh:
        json.dump({str(k): v for k, v in t.items()}, fh)
    return p


def load_table(period, P, mode, floor_pct):
    d = json.load(open(path(period, P, mode, floor_pct)))
    return {int(k): v for k, v in d.items()}


if __name__ == "__main__":
    PER = [2, 3, 4, 5, 7, 10, 14, 20, 30, 60, 90, 120]
    jobs = [(N, P, mode, 5.0) for N in PER for P in (12, 24, 48) for mode in ("prod", "clean")]
    with Pool(6) as pool:
        for i, p in enumerate(pool.imap_unordered(build, jobs, chunksize=1)):
            if i % 10 == 0:
                print(i, "/", len(jobs), os.path.basename(p), flush=True)
    print("完成", flush=True)
