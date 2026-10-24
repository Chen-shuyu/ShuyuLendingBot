# -*- coding: utf-8 -*-
"""兩個多月的政策模擬（2026-10-24，乙）。只讀資料，不碰正式環境。

成交規則與專案的 `core/fill_simulation.py` 相同（D049）：
  掛在 r，從掛出那一小時起，第一根 high >= r 的 K 就是成交，成交時點取該根中點。
已知偏差（全部偏袒高價）：看不到排隊（高價位成交被模擬得太快）、持有時間與利率無關
（實際上越貴越早被還，D062 rho = -0.383）。

時間一律以「小時格」為單位；缺根的小時 = 那一小時沒有成交（high 視為不存在）。
"""
import json
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/workspace/projects/LendingBot/ShuyuLendingBot")

CST = timezone(timedelta(hours=8))
H = 3_600_000
FEE = 0.85
import os
HERE = os.environ.get("POLICY_SIM_WORKDIR", os.getcwd()).rstrip("/") + "/"  # 放 dl2/、snap/、json 的工作目錄


def ms(y, m, d, hh=0):
    return int(datetime(y, m, d, hh, tzinfo=CST).timestamp() * 1000)


class Market:
    """一個天期的小時格。`hours[i]` 是第 i 小時的 K（dict）或 None（缺根＝沒成交）。"""

    def __init__(self, period, t0=None, t1=None):
        raw = json.load(open(HERE + f"dl2/candles_p{period}.json"))
        grid = {m: {"mts": m, "open": o, "close": c, "high": h, "low": l, "volume": v}
                for m, o, c, h, l, v in raw}
        self.period = period
        self.t0 = t0 or min(grid)
        self.t1 = t1 or (max(grid) + H)
        self.hours = [grid.get(t) for t in range(self.t0, self.t1, H)]

    def idx(self, t_ms):
        return (t_ms - self.t0) // H

    def when(self, i):
        return datetime.fromtimestamp((self.t0 + i * H) / 1000, CST)


def quantile(values, q):
    s = sorted(values)
    if not s:
        return None
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


_MR = None


def market_rate(mk, i):
    """成交價下限用的「常態成交價」：08-23 起用市場快照存的同天期金額加權中位數（真值），
    更早沒有快照的時段退回「近 6 小時收盤中位」。近 6 小時同天期完全沒成交就回 None。"""
    global _MR
    if _MR is None:
        _MR = json.load(open(HERE + "market_rate_by_hour.json"))
    if not any(mk.hours[max(0, i - 6):i]):
        return None
    t = mk.t0 + i * H
    table = _MR.get(str(mk.period), {})
    for back in range(0, 3):  # 最近 3 小時內的快照
        v = table.get(str(t - back * H))
        if v:
            return v
    closes = [c["close"] for c in mk.hours[max(0, i - 6):i] if c]
    return statistics.median(closes) if closes else None


# ---------------------------------------------------------------- 定價規則
class Fixed:
    """永遠掛同一個價。"""

    def __init__(self, annual_pct):
        self.r = annual_pct / 36500
        self.name = f"固定 {annual_pct:g}%"

    def price(self, mk, i):
        return self.r


class Follow:
    """跟著市場：掛在「過去 L 小時、每小時最高成交價」的第 q 分位，低於地板就不借。

    q 越高 = 掛越貴（只有少數小時掃得到）、q 越低 = 掛越便宜（多數小時都掃得到）。
    窗是**時間**（L 小時），不是根數——缺根的小時不算進來，但也不會把窗撐長。
    """

    def __init__(self, q, lookback_h=24, floor_pct=0.0, min_n=6):
        self.q, self.L, self.floor = q, lookback_h, floor_pct / 36500
        self.min_n = min_n
        self.name = f"跟市場 q{int(q*100)}/{lookback_h}h" + (f"/地板{floor_pct:g}%" if floor_pct else "")

    def price(self, mk, i):
        vals = [c["high"] for c in mk.hours[max(0, i - self.L):i] if c]
        if len(vals) < self.min_n:
            return None
        r = quantile(vals, self.q)
        if r < self.floor:
            return None
        return r


class EV:
    """專案的期望值策略本尊（choose_rate），加上正式環境的兩道下限。

    `time_window=False`：照正式環境——抓「最後 240 根真的存在的 K」，策略再取最後 168 根
    （天期 30 缺根時，168 根會橫跨好幾倍的時間，D073）。
    `time_window=True`：把缺根的小時補成 high=0 的空格，168 格＝168 小時（修好之後的樣子）。
    成交價下限：近 6 小時收盤中位 × 0.85（代替正式環境的 `market_rate()`）。
    地板：低於 `floor_pct` 就整輪不借（正式環境的 `minimum_rate` 行為）。
    """

    def __init__(self, floor_pct=8.0, time_window=False, hold_hours=48.0, label=None, hold_switch=None):
        from config import settings
        from strategies.expected_value import ExpectedValueStrategy
        from pathlib import Path
        cfg = settings.load_config(str(settings.resolve_config_path(Path("/workspace/projects/LendingBot/ShuyuLendingBot")))) or {}
        self.s = ExpectedValueStrategy(cfg)
        self.s.assumed_hold_hours = float(hold_hours)
        self.floor = floor_pct / 36500
        self.time_window = time_window
        self.hold_switch = hold_switch  # [(生效時刻 ms, P), ...]：重現 D056 的 48 → 12
        self.name = label or (f"現行模型 地板{floor_pct:g}%" + ("（窗改成小時）" if time_window else ""))

    def price(self, mk, i):
        if self.hold_switch:
            now = mk.t0 + i * H
            for when, P in self.hold_switch:
                if now >= when:
                    self.s.assumed_hold_hours = float(P)
        if self.time_window:
            lo = max(0, i - 240)
            candles = [c if c else {"mts": mk.t0 + j * H, "high": 0.0, "close": 0.0} for j, c in
                       zip(range(lo, i), mk.hours[lo:i])]
        else:
            candles = [c for c in mk.hours[max(0, i - 3000):i] if c][-240:]
        base = self.s.choose_rate(candles)
        if base is None:
            return None
        mr = market_rate(mk, i)
        if mr is None:
            return None  # 地雷④的代理：近 6 小時同天期沒有成交
        floored = max(base, mr * self.s.market_floor_pct)
        if floored < self.floor:
            return None
        return floored


# ---------------------------------------------------------------- 持有時間
def load_bags():
    raw = json.load(open(HERE + "hold_samples.json"))
    p2 = [h for r, h in raw["2"]]
    # 08-28 那三筆是同一張單的拆單（D057 的 split group），只算一段
    dedup, seen = [], set()
    for r, h in raw["2"]:
        key = round(h, 1)
        if key == 11.6 and key in seen:
            continue
        seen.add(key)
        dedup.append(h)
    p30 = [h for r, h in raw["30"]]
    return {"p2": dedup, "p30": p30}


# ---------------------------------------------------------------- 模擬
def run(mk, policy, bag, start_i, end_i, cap_hours=None, bag_shift=0):
    """回傳 (淨實得年化%, 利用率%, 名目%, 成交次數)。`cap_hours`：合約天期上限（天期 2 = 48h）。

    時間是連續的（小時，可帶小數）。錢回來的那一刻就重掛：若當下這一小時的高點 >= 掛價，
    成交時點取「剩下那段」的中點；否則一小時一小時往後找，成交取該根中點（D049 的約定）。
    `bag_shift`：持有樣本從第幾筆開始輪——跨起跑點時一起輪替，把排列順序的運氣平均掉。
    """
    t = float(start_i)
    cyc = bag_shift
    interest = 0.0  # Σ 日利率 × 小時
    lent = 0.0
    fills = 0
    while t < end_i:
        i = int(math.floor(t))
        c = mk.hours[i]
        if c is None:  # 這一小時沒有任何成交，掛什麼價都不會被掃到
            t = i + 1.0
            continue
        r = policy.price(mk, i)
        if r is not None and c["high"] >= r:
            t_fill = (t + (i + 1)) / 2.0
            hold = bag[cyc % len(bag)]
            if cap_hours:
                hold = min(hold, cap_hours)
            cyc += 1
            fills += 1
            dur = min(t_fill + hold, end_i) - t_fill
            interest += r * dur
            lent += dur
            t = t_fill + hold
        else:
            t = i + 1.0
    window = end_i - start_i
    net = interest / window * 365 * 100 * FEE
    util = lent / window * 100
    nominal = interest / lent * 365 * 100 if lent else float("nan")
    return net, util, nominal, fills


def across(mk, policy, bag, s_ms, e_ms, offsets=range(0, 48, 3), cap_hours=None):
    """跨起跑點（D054）：同一個窗，起點往後挪 0、3、6…45 小時各跑一次，回傳平均與範圍。"""
    end_i = mk.idx(e_ms)
    res = [run(mk, policy, bag, mk.idx(s_ms) + o, end_i, cap_hours, bag_shift=k) for k, o in enumerate(offsets)]
    nets = [r[0] for r in res]
    return {
        "net": statistics.fmean(nets), "lo": min(nets), "hi": max(nets),
        "util": statistics.fmean(r[1] for r in res),
        "nominal": statistics.fmean(r[2] for r in res if not math.isnan(r[2])) if any(not math.isnan(r[2]) for r in res) else float("nan"),
        "fills": statistics.fmean(r[3] for r in res),
    }


WINDOWS = {
    "A 短天期實測期 08-17～09-13": (ms(2026, 8, 17), ms(2026, 9, 14)),
    "B 長天期判定窗 09-14～10-13": (ms(2026, 9, 14), ms(2026, 10, 14)),
    "C 延長期 10-14～10-23": (ms(2026, 10, 14), ms(2026, 10, 24)),
    "全期 08-17～10-23": (ms(2026, 8, 17), ms(2026, 10, 24)),
}
ACTUAL = {  # D073：實際拿到的（看哪天賺的）
    "A 短天期實測期 08-17～09-13": 6.46,
    "B 長天期判定窗 09-14～10-13": 6.03,
    "C 延長期 10-14～10-23": 1.95,
    "全期 08-17～10-23": 5.60,
}
