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

import pytest

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
    position_id="464505426", rate=0.00024971, opened_at="2026-08-26T00:30:51+08:00",
    closed_at=None,
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
        "closed_at": closed_at,
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


def test_三個統計量各自算得出自己的倍數():
    """同一份預估裡的平均／中位數／四分之三，要能分別對上實際等待。

    **策略只用了平均**（`expected_value.py` 的 `effective` 拿 `mean_hours` 當分母），
    而三個值是同一次 `estimate_wait()` 算出來的。少對照兩個，等於在證據上
    先幫讀的人排除了兩個選項。
    """
    spells = wait_time.build_spells(
        [offer()], [position()], forecasts={"5092133927": forecast()}, now=NOW
    )
    spell = spells[0]

    # 實際約 0.277h；預估 平均 8.04h／中位數 2.5h／四分之三 13.5h
    assert abs(spell.factor_for("mean") - 29.0) < 0.5
    assert abs(spell.factor_for("median") - 9.0) < 0.3
    assert abs(spell.factor_for("p75") - 48.7) < 0.5
    # `overestimate_factor` 維持等於平均那一個，既有呼叫端不受影響
    assert spell.factor_for("mean") == spell.overestimate_factor


def test_p75_有被讀進來而不是留成空值():
    """新加的欄位要真的接到 DB，不能靜默停在 `None`（D026 那一族）。"""
    spells = wait_time.build_spells(
        [offer()], [position()], forecasts={"5092133927": forecast()}, now=NOW
    )
    assert spells[0].forecast_p75_hours == 13.5


def test_三個統計量的總量比與離散度分開報():
    """離散度才是重點：總量比接近 1 但逐筆橫跨兩個數量級，一樣不能拿來算期望值。"""
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

    # 兩段的中位數預估都是 2.5h，實際 3.93h 與 0.77h → 總量比 5.0 ÷ 4.70 ≈ 1.06
    assert abs(summary.overall_factor_for("median") - 1.06) < 0.05
    assert abs(summary.overall_factor_for("mean") - 3.1) < 0.2
    # **總量比接近 1 不代表準**：逐筆是 0.6× 與 3.2×，離散照樣要看得見
    low, high = summary.factor_range_for("median")
    assert abs(low - 0.64) < 0.05 and abs(high - 3.2) < 0.2
    assert summary.calibratable_for("p75") == summary.calibratable_for("mean")


def test_算不出倍數的統計量不會被當成零():
    """某個統計量缺值時要退出可用集合，不能拿 0 去拉低總量比。"""
    missing = {**forecast(), "median_hours": None}
    summary = wait_time.summarize(
        [offer()], [position()], forecasts={"5092133927": missing}, now=NOW
    )
    assert summary.calibratable_for("median") == []
    assert summary.overall_factor_for("median") is None
    # 平均那一個不受影響，兩者是分開算的
    assert summary.overall_factor_for("mean") is not None


def test_實得年化把等待與持有乘起來():
    """🔴 **這一條守的是 08-29 那個最貴卻最差的樣本。**

    名目年化 10.95%（至今最高）等 5.19h、借 1.98h，**實得只有 3.02%**
    （至今最低）。只看名目利率會把最差的決定看成最好的，而在這一條之前
    專案裡沒有任何地方把 `W` 與 `P` 乘起來過。
    """
    spells = wait_time.build_spells(
        [offer("hi", rate=0.0003, created_at="2026-08-29T15:40:56+08:00")],
        [position("464812689", rate=0.0003,
                  opened_at="2026-08-29T20:52:13+08:00",
                  closed_at="2026-08-29T22:50:57+08:00")],
        now=NOW.replace(day=30),
    )
    spell = spells[0]

    assert spell.hours == pytest.approx(5.19, abs=0.01)      # W
    assert spell.hold_hours == pytest.approx(1.98, abs=0.01)  # P
    assert spell.realized_effective == pytest.approx(3.02, abs=0.02)
    # 名目是最高的，實得是最低的——這正是要能同時看到的理由
    assert spell.annual_rate > spell.realized_effective * 3


def test_仍在生息中的部位算不出實得年化():
    """`P` 還會繼續長，乘進去等於宣告一個還沒發生的結果（同右設限的處理）。"""
    spells = wait_time.build_spells(
        [offer()], [position()], now=NOW
    )
    assert spells[0].censored is False       # 等到成交了
    assert spells[0].hold_ongoing is True    # 但還沒還回來
    assert spells[0].hold_hours is None
    assert spells[0].realized_effective is None


def test_沒等到成交的期間也算不出實得年化():
    """右設限的期間根本沒有 `P`。"""
    offers = [
        offer("a", created_at="2026-08-26T00:14:13+08:00"),
        offer("b", rate=0.0002729, created_at="2026-08-26T06:00:00+08:00"),
    ]
    spells = wait_time.build_spells(offers, [], now=NOW)

    assert all(s.censored for s in spells)
    assert all(s.realized_effective is None for s in spells)


def test_彙總的實得年化以時間加權而不是逐筆平均():
    """一筆等很久又借很短的單，佔掉的時間遠多於它在逐筆平均裡的一票。"""
    offers = [
        offer("a", rate=0.00024971, created_at="2026-08-26T00:14:13+08:00"),
        offer("b", rate=0.0003, created_at="2026-08-29T15:40:56+08:00"),
    ]
    positions = [
        # 好的那一筆：幾乎沒等、借滿
        position("good", rate=0.00024971,
                 opened_at="2026-08-26T00:30:51+08:00", closed_at="2026-08-28T00:46:00+08:00"),
        # 差的那一筆：等 5.19h、只借 1.98h
        position("bad", rate=0.0003,
                 opened_at="2026-08-29T20:52:13+08:00", closed_at="2026-08-29T22:50:57+08:00"),
    ]
    summary = wait_time.summarize(offers, positions, now=NOW.replace(day=30))

    assert len(summary.realized) == 2
    per_item = sum(s.realized_effective for s in summary.realized) / 2
    weighted = summary.realized_effective
    # 逐筆平均約 6.0%，時間加權約 8.9%——**兩者差很多，而加權才是實際拿到的**
    assert weighted > per_item + 1.0
    assert summary.realized_worst.position_id == "bad"


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


def test_還在計時的那一段不會被說成被取代():
    """🔴 這一條是正式環境誤述抓出來的（2026-08-29）。

    當時場上躺著一張年化 10.95%、才掛了 1.85 小時的單，而報告印的是
    「至少掛了 1.69 小時**沒有成交**，**被下一張單取代**」——沒有任何一張單
    取代它，它還在等。偏偏那是 D045 缺了兩週的高價端樣本，把「還在計時」
    講成「已經結束」，等於把一個會繼續長的下界固定成量測值。
    """
    spells = wait_time.build_spells(
        [offer("5096173429", rate=0.0003, created_at="2026-08-29T15:51:01+08:00")],
        [],
        now=datetime(2026, 8, 29, 17, 31, 56, tzinfo=TZ),
    )

    assert len(spells) == 1
    assert spells[0].censored is True
    assert spells[0].replaced is False
    text = wait_time.describe_spell(spells[0])
    assert "還在計時" in text
    assert "被下一張單取代" not in text


def test_真的被下一張單取代時照樣這樣講():
    """反向那半：分得出來才算修好，不然只是把一句錯話換成另一句。"""
    spells = wait_time.build_spells(
        [
            offer("5084375241", rate=0.000268, created_at="2026-08-19T05:03:24+08:00"),
            offer("5086244279", rate=0.00026027, created_at="2026-08-20T15:15:21+08:00"),
        ],
        [],
        now=NOW,
    )

    assert spells[0].replaced is True
    assert "被下一張單取代" in wait_time.describe_spell(spells[0])
    # 最後一段永遠沒有下一張單接手
    assert spells[1].replaced is False


def test_還在計時的段數會被單獨報出來():
    """`longest_censored_hours` 是下界，而讀的人要知道它還會不會長。"""
    summary = wait_time.summarize(
        [
            offer("5084375241", rate=0.000268, created_at="2026-08-19T05:03:24+08:00"),
            offer("5096173429", rate=0.0003, created_at="2026-08-29T15:51:01+08:00"),
        ],
        [],
        now=datetime(2026, 8, 29, 17, 31, 56, tzinfo=TZ),
    )

    assert summary.censored == 2
    # 兩段都沒等到，但只有最後那一段還在長
    assert summary.ongoing == 1


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
