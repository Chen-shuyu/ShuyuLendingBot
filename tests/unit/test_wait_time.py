# -*- coding: utf-8 -*-
"""`core/wait_time.py` 的單元測試（見 DECISIONS.md D045）。

這個模組只做一件事：**把「掛出去以為要等多久」對上「實際等了多久」，
而且不許在算不準的時候裝作算得準**。所以測試分成三半：

1. 掛單期間切得對不對（合併規則的兩條、成交配對）
2. 算得對不對（等待時間、高估倍數、總量比）
3. **算不準的時候有沒有說出來**——右設限、沒有預估值、同輪的兄弟單。
   這一半才是重點：D045 的整個結論建立在「五筆全部高估」上，
   而**只要把沒成交的那一段丟掉，這個結論就會被誇大**。

測試資料的量級取自 2026-08-18～08-26 的真實掛單（等待 3.60／3.93／0.70／
3.33／0.77／0.28h，預估 6.10／6.32／6.29／8.69／8.04h，以及那一段 34.20h
沒成交的 9.78%），不用 1／2／3 這種漂亮數字——D027 的教訓。
"""

from datetime import datetime, timedelta, timezone

from core import wait_time

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 26, 22, 0, 0, tzinfo=TZ)


def offer(offer_id="5092133927", rate=0.00024971, created_at="2026-08-26T00:14:13+08:00"):
    """一列 `loan_offers`，欄位形狀照 DB 實際存的樣子。"""
    return {
        "id": 4174,
        "offer_id": offer_id,
        "currency": "USD",
        "amount": 344.72,
        "rate": rate,
        "duration": 2,
        "status": "submitted",
        "detail": "fUSD",
        "created_at": created_at,
    }


def position(
    position_id="464505426", rate=0.00024971, opened_at="2026-08-26T00:30:51+08:00"
):
    """一列 `funding_positions`。"""
    return {
        "position_id": position_id,
        "currency": "USD",
        "amount": 344.72,
        "rate": rate,
        "period": 2,
        "kind": "credit",
        "opened_at": opened_at,
        "first_seen_at": "2026-08-26T00:34:20+08:00",
        "closed_at": None,
    }


def forecast(offer_id="5092133927", mean_hours=8.041666666666666):
    """一列 `offer_wait_forecasts`。"""
    return {
        "offer_id": offer_id,
        "rate": 0.00024971,
        "mean_hours": mean_hours,
        "median_hours": 2.5,
        "p75_hours": 13.5,
        "hits": 66,
        "censored_ratio": 0.0,
        "window_hours": 168,
        "created_at": "2026-08-26T00:14:13+08:00",
    }


# --- 掛單期間切得對不對 ---------------------------------------------------


def test_成交的掛單算出實際等待():
    spells = wait_time.build_spells([offer()], [position()], now=NOW)

    assert len(spells) == 1
    assert spells[0].censored is False
    assert spells[0].position_id == "464505426"
    # 00:14:13 → 00:30:51 = 16 分 38 秒
    assert spells[0].hours == round(998 / 3600, 10) or abs(spells[0].hours - 0.2772) < 1e-3


def test_沒成交就被取代的掛單是右設限():
    spells = wait_time.build_spells(
        [
            offer("5084375241", rate=0.000268, created_at="2026-08-19T05:03:24+08:00"),
            offer("5086244279", rate=0.00026027, created_at="2026-08-20T15:15:21+08:00"),
        ],
        [position("464168644", rate=0.00026027, opened_at="2026-08-20T19:10:59+08:00")],
        now=NOW,
    )

    assert len(spells) == 2
    # 34.2 小時掛著沒成交——D045 唯一的反例，而且它在高價那一端
    assert spells[0].censored is True
    assert abs(spells[0].hours - 34.20) < 0.01
    assert spells[1].censored is False


def test_連續同利率的重掛合併成一段():
    """08-15～16 每輪重掛的那一百多列，不該被讀成一百多次「沒成交」。"""
    spells = wait_time.build_spells(
        [
            offer("a", rate=0.000523, created_at="2026-08-15T15:09:00+08:00"),
            offer("b", rate=0.000523, created_at="2026-08-15T15:19:00+08:00"),
            offer("c", rate=0.000523, created_at="2026-08-15T15:29:00+08:00"),
        ],
        [],
        now=NOW,
    )

    assert len(spells) == 1
    assert spells[0].offer_count == 3
    assert spells[0].censored is True


def test_成交會切斷合併即使利率相同():
    """🔴 這一條守的是實跑才發現的那個 bug（見 core/wait_time.py 的合併規則）。

    只比利率的話，兩張各自成交過的同價位單會被併成一段，
    **五個校準樣本靜靜地變成兩個**——報告照樣印得出來，只是少了一半。
    """
    spells = wait_time.build_spells(
        [
            offer("5090003522", created_at="2026-08-23T23:04:47+08:00"),
            offer("5092133927", created_at="2026-08-26T00:14:13+08:00"),
        ],
        [
            position("464372858", opened_at="2026-08-23T23:50:49+08:00"),
            position("464505426", opened_at="2026-08-26T00:30:51+08:00"),
        ],
        now=NOW,
    )

    assert len(spells) == 2, "中間成交過就該切成兩段，不能因為利率相同而合併"
    assert [s.position_id for s in spells] == ["464372858", "464505426"]


def test_利率不同就不合併():
    spells = wait_time.build_spells(
        [
            offer("a", rate=0.00026027, created_at="2026-08-21T16:09:06+08:00"),
            offer("b", rate=0.00024971, created_at="2026-08-23T23:04:47+08:00"),
        ],
        [],
        now=NOW,
    )
    assert len(spells) == 2


# --- 算得對不對 -----------------------------------------------------------


def test_高估倍數是預估除以實際():
    spells = wait_time.build_spells(
        [offer()], [position()], forecasts={"5092133927": forecast()}, now=NOW
    )
    # 預估 8.04h、實際約 0.277h
    assert abs(spells[0].overestimate_factor - 29.0) < 0.5


def test_總量比用總預估除以總實際而不是逐筆倍數的平均():
    """逐筆倍數的平均會被「實際等待很短」那幾筆炸掉，講的不是同一件事。"""
    offers = [
        offer("a", rate=0.00026027, created_at="2026-08-20T15:15:21+08:00"),
        offer("b", rate=0.00024971, created_at="2026-08-23T23:04:47+08:00"),
    ]
    positions = [
        position("464168644", rate=0.00026027, opened_at="2026-08-20T19:10:59+08:00"),
        position("464372858", rate=0.00024971, opened_at="2026-08-23T23:50:49+08:00"),
    ]
    forecasts = {
        "a": {**forecast("a", mean_hours=6.095238095238095), "rate": 0.00026027},
        "b": forecast("b", mean_hours=8.693452380952381),
    }
    summary = wait_time.summarize(offers, positions, forecasts=forecasts, now=NOW)

    # 實際 3.93h 與 0.77h → 總預估 14.79 ÷ 總實際 4.70 ≈ 3.1
    assert abs(summary.overall_factor - 3.1) < 0.2
    # 逐筆是 1.6× 與 11.3×，平均會是 6.4——兩者差這麼多正是不該用單一數字轉述的理由
    assert summary.factor_listing() == "1.6×、11.3×"
    assert summary.overestimated == 2
    assert summary.underestimated == 0


def test_校準樣本的利率範圍會被報出來():
    """D045 最重要的但書：倍數只在有樣本的利率帶成立，帶外不能外推。"""
    summary = wait_time.summarize(
        [offer()], [position()], forecasts={"5092133927": forecast()}, now=NOW
    )
    assert summary.calibration_rate_span == "9.11%～9.11%"


# --- 算不準的時候有沒有說出來 ---------------------------------------------


def test_右設限的期間算不出高估倍數():
    """它的 `hours` 是下界，拿下界當分母會把倍數算得比實際更大。"""
    spells = wait_time.build_spells(
        [offer()], [], forecasts={"5092133927": forecast()}, now=NOW
    )
    assert spells[0].censored is True
    assert spells[0].overestimate_factor is None


def test_右設限不列入平均但會被單獨報出來():
    summary = wait_time.summarize(
        [
            offer("a", rate=0.000268, created_at="2026-08-19T05:03:24+08:00"),
            offer("b", rate=0.00026027, created_at="2026-08-20T15:15:21+08:00"),
        ],
        [position("464168644", rate=0.00026027, opened_at="2026-08-20T19:10:59+08:00")],
        now=NOW,
    )

    assert summary.filled == 1
    assert summary.censored == 1
    # 平均只用成交的那一段算，34.2h 那段不混進去
    assert abs(summary.mean_hours - 3.93) < 0.01
    # 但它要看得見——這是這份報告最容易騙人的地方
    assert abs(summary.longest_censored_hours - 34.20) < 0.01


def test_沒有預估值的掛單不會被填成零():
    """填 0 會讓它變成「預估 0h、實際 3.6h」的低估樣本，把結論整個翻過去。"""
    spells = wait_time.build_spells([offer()], [position()], forecasts={}, now=NOW)

    assert spells[0].has_forecast is False
    assert spells[0].forecast_mean_hours is None
    assert spells[0].overestimate_factor is None
    assert "沒有留下預估值" in wait_time.describe_spell(spells[0])


def test_同一輪掛出的兄弟單不算一段等待也不計入右設限():
    """`spread_count > 1` 的時期一輪掛好幾張，時間戳相同，長度是零。"""
    same_moment = "2026-08-16T17:45:00+08:00"
    summary = wait_time.summarize(
        [
            offer("a", rate=0.000273, created_at=same_moment),
            offer("b", rate=0.000313, created_at=same_moment),
        ],
        [],
        now=NOW,
    )

    assert summary.total == 2
    assert summary.simultaneous == 1, "前一張的存活區間長度是零，那不是一段等待"
    assert summary.censored == 1
    assert summary.comparable == 1
    assert "分不出誰先誰後" in wait_time.describe_spell(summary.spells[0])


def test_小樣本不報中位數改列原始值():
    """同 D040：n=2 的中位數是插值插出來的，資料裡不存在那個數。"""
    summary = wait_time.summarize(
        [
            offer("a", rate=0.00026027, created_at="2026-08-20T15:15:21+08:00"),
            offer("b", rate=0.00024971, created_at="2026-08-23T23:04:47+08:00"),
        ],
        [
            position("464168644", rate=0.00026027, opened_at="2026-08-20T19:10:59+08:00"),
            position("464372858", rate=0.00024971, opened_at="2026-08-23T23:50:49+08:00"),
        ],
        now=NOW,
    )
    assert summary.filled == 2
    assert summary.enough_for_quantile is False
    assert summary.hours_listing() == "0.77h、3.93h"


def test_倍數樣本不足時不報中位數():
    summary = wait_time.summarize(
        [offer()], [position()], forecasts={"5092133927": forecast()}, now=NOW
    )
    assert len(summary.calibratable) == 1
    assert summary.median_factor is None, "一筆算不出中位數，要說算不出來"


def test_壞掉的時間戳不會被猜成零():
    summary = wait_time.summarize(
        [offer("a", created_at=None), offer("b", created_at="不是時間")], [], now=NOW
    )
    assert summary.total == 0


def test_沒有任何掛單時不會爆掉():
    summary = wait_time.summarize([], [], now=NOW)
    assert summary.total == 0
    assert summary.censored_ratio == 0.0
    assert summary.overall_factor is None
    assert summary.calibration_rate_span is None
