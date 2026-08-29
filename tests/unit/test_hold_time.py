# -*- coding: utf-8 -*-
"""`core/hold_time.py` 的單元測試（見 DECISIONS.md D040）。

這個模組只做一件事：**把「借出去的錢待了多久」算出來，而且不許在算不準的時候
裝作算得準**。所以測試分成兩半：

1. 算得對不對（持有時間、完成率、借到期 vs 提前還款的分界）
2. **算不準的時候有沒有說出來**——右設限、偵測延遲、近似起算時間、
   小樣本的插值中位數。這一半才是重點，也是 D026 家族反覆現身的那個位置：
   不是沒講，是講了一個聽起來很有把握的數字。

測試資料的量級取自 2026-08-16～08-21 的六筆真實部位（1.84h／45.08h／6.87h／
20.97h／2.33h），不用 1／2／3 這種漂亮數字——D027 的教訓。
"""

from datetime import datetime, timedelta, timezone

import pytest

from core import hold_time

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=TZ)


def position(
    position_id="464242253",
    rate=0.00026027,
    amount=344.41,
    period=2,
    opened_at="2026-08-21T22:31:00+08:00",
    closed_at=None,
    first_seen_at="2026-08-21T22:33:56+08:00",
):
    """一列 `funding_positions`，欄位形狀照 DB 實際存的樣子。"""
    return {
        "position_id": position_id,
        "currency": "USD",
        "amount": amount,
        "rate": rate,
        "period": period,
        "kind": "credit",
        "opened_at": opened_at,
        "first_seen_at": first_seen_at,
        "closed_at": closed_at,
    }


# --- 算得對不對 -----------------------------------------------------------


def test_已結束的部位算出實際持有時間與完成率():
    record = hold_time.build_record(
        position(
            opened_at="2026-08-21T16:51:03+08:00",
            closed_at="2026-08-21T19:11:01+08:00",
        ),
        now=NOW,
    )

    assert record.censored is False
    assert record.hours == pytest.approx(2.332, abs=0.01)
    assert record.completion == pytest.approx(2.332 / 48, abs=0.001)


def test_仍在借出中的部位以現在為止計算且標記為右設限():
    record = hold_time.build_record(
        position(opened_at="2026-08-21T22:31:00+08:00", closed_at=None),
        now=NOW,
    )

    assert record.censored is True
    assert record.hours == pytest.approx(13.483, abs=0.01)


def test_借滿天期與提前還款以完成率門檻分界():
    matured = hold_time.build_record(
        position(
            opened_at="2026-08-16T21:30:43+08:00",
            closed_at="2026-08-18T18:35:22+08:00",
        ),
        now=NOW,
    )
    early = hold_time.build_record(
        position(
            opened_at="2026-08-16T19:31:31+08:00",
            closed_at="2026-08-16T21:21:52+08:00",
        ),
        now=NOW,
    )

    # 45.08h / 48h = 93.9%，過得了 90% 的門檻；1.84h / 48h = 3.8%，過不了。
    assert matured.completion >= hold_time.DEFAULT_MATURED_THRESHOLD
    assert early.completion < hold_time.DEFAULT_MATURED_THRESHOLD


def test_摘要的統計量只用已結束的部位():
    positions = [
        position("a", closed_at="2026-08-21T00:00:00+08:00", opened_at="2026-08-20T20:00:00+08:00"),
        position("b", closed_at="2026-08-21T08:00:00+08:00", opened_at="2026-08-21T00:00:00+08:00"),
        position("c", closed_at="2026-08-21T14:00:00+08:00", opened_at="2026-08-21T12:00:00+08:00"),
        position("d", closed_at=None, opened_at="2026-08-21T22:31:00+08:00"),
    ]

    summary = hold_time.summarize(positions, now=NOW)

    assert summary.total == 4
    assert summary.settled == 3
    assert summary.censored == 1
    # 仍在借出中那筆已經 13.48h，若混進去中位數會從 4.0 被拉到 6.0。
    assert summary.median_hours == pytest.approx(4.0, abs=0.01)
    assert summary.censored_ratio == pytest.approx(0.25)


# --- 算不準的時候有沒有說出來 ---------------------------------------------


def test_右設限的部位在敘述裡改口說至少():
    record = hold_time.build_record(position(closed_at=None), now=NOW)

    text = hold_time.describe_record(record)

    assert "至少" in text
    assert "仍在生息中" in text
    # 反向斷言：下界不可以被講成量測值。
    assert "實際借出" not in text


def test_已結束的部位不可以說至少():
    record = hold_time.build_record(
        position(
            opened_at="2026-08-21T16:51:03+08:00",
            closed_at="2026-08-21T19:11:01+08:00",
        ),
        now=NOW,
    )

    text = hold_time.describe_record(record)

    assert "實際借出" in text
    assert "至少" not in text


def test_沒有交易所端起算時間時退用第一次看到並標記為近似():
    summary = hold_time.summarize(
        [
            position(
                opened_at=None,
                first_seen_at="2026-08-21T22:33:56+08:00",
                closed_at="2026-08-22T00:00:00+08:00",
            )
        ],
        now=NOW,
    )

    assert summary.approximate_opened == 1
    assert summary.settled == 1


def test_起算時間完全壞掉的列被排除且計入不可用():
    summary = hold_time.summarize(
        [
            position("good", closed_at="2026-08-22T00:00:00+08:00"),
            position("bad", opened_at=None, first_seen_at=None),
            position("garbage", opened_at="not-a-date", first_seen_at=None),
        ],
        now=NOW,
    )

    # 靜靜少算兩筆是 D026 那個家族的病：樣本不完整卻不說。
    assert summary.total == 1
    assert summary.unusable == 2


def test_持有時間為負的列被排除():
    summary = hold_time.summarize(
        [
            position(
                opened_at="2026-08-22T00:00:00+08:00",
                closed_at="2026-08-21T00:00:00+08:00",
            )
        ],
        now=NOW,
    )

    assert summary.total == 0
    assert summary.unusable == 1


def test_偵測延遲跟著摘要走以便報告講出高估上界():
    summary = hold_time.summarize(
        [position(closed_at="2026-08-22T00:00:00+08:00")],
        now=NOW,
        detection_lag_hours=600 / 3600,
    )

    assert summary.detection_lag_hours == pytest.approx(600 / 3600)


# --- 小樣本：不許用插值出來的中位數冒充統計量 -----------------------------


def test_樣本少於門檻時不報四分位():
    summary = hold_time.summarize(
        [
            position("a", closed_at="2026-08-21T00:00:00+08:00", opened_at="2026-08-20T22:00:00+08:00"),
            position("b", closed_at="2026-08-21T08:00:00+08:00", opened_at="2026-08-21T00:00:00+08:00"),
        ],
        now=NOW,
    )

    assert summary.settled == 2
    assert summary.enough_for_quantile is False
    # 原始值仍然拿得到——攤開來看比一個虛構的中位數有用。
    assert summary.hours_listing() == "2.00h、8.00h"


def test_兩組樣本不足時差距回不知道而不是插值出來的數():
    """真實案例：便宜組只有 1.84h 與 45.08h 兩筆，差 25 倍。

    `statistics.median` 會給出 23.46h——一個沒有對應任何一筆真實借貸的數字，
    而 `gap_hours` 若拿它去相減，會得出「差距 16.59h，方向符合越貴借越短」
    這個看起來很有根據的結論。**這正是要擋掉的東西。**
    """
    positions = [
        # 便宜組兩筆，形狀取自真實資料。
        position("cheap1", rate=0.00025, opened_at="2026-08-16T19:31:31+08:00", closed_at="2026-08-16T21:21:52+08:00"),
        position("cheap2", rate=0.00015, opened_at="2026-08-16T21:30:43+08:00", closed_at="2026-08-18T18:35:22+08:00"),
        # 昂貴組三筆。
        position("rich1", rate=0.0002729, opened_at="2026-08-18T22:11:22+08:00", closed_at="2026-08-19T05:03:19+08:00"),
        position("rich2", rate=0.00026027, opened_at="2026-08-20T19:10:59+08:00", closed_at="2026-08-21T16:09:01+08:00"),
        position("rich3", rate=0.00026027, opened_at="2026-08-21T16:51:03+08:00", closed_at="2026-08-21T19:11:01+08:00"),
    ]

    split = hold_time.split_by_rate(hold_time.summarize(positions, now=NOW))

    assert split is not None
    assert split.cheaper.settled == 2
    assert split.pricier.settled == 3
    assert split.comparable is False
    assert split.gap_hours is None


def test_兩組樣本都足夠時才比得出差距():
    positions = [
        position("cheap1", rate=0.00015, opened_at="2026-08-20T00:00:00+08:00", closed_at="2026-08-21T00:00:00+08:00"),
        position("cheap2", rate=0.00015, opened_at="2026-08-20T00:00:00+08:00", closed_at="2026-08-21T04:00:00+08:00"),
        position("cheap3", rate=0.00016, opened_at="2026-08-20T00:00:00+08:00", closed_at="2026-08-21T08:00:00+08:00"),
        position("rich1", rate=0.00026027, opened_at="2026-08-21T00:00:00+08:00", closed_at="2026-08-21T02:00:00+08:00"),
        position("rich2", rate=0.00026027, opened_at="2026-08-21T00:00:00+08:00", closed_at="2026-08-21T04:00:00+08:00"),
        position("rich3", rate=0.0002729, opened_at="2026-08-21T00:00:00+08:00", closed_at="2026-08-21T06:00:00+08:00"),
    ]

    split = hold_time.split_by_rate(hold_time.summarize(positions, now=NOW))

    assert split.comparable is True
    # 便宜組中位數 28h、昂貴組 4h，方向符合「越貴借越短」。
    assert split.gap_hours == pytest.approx(24.0, abs=0.01)


def test_中位數同時是眾數時分界被標成退化():
    """真實案例：16 筆已結束裡有 10 筆同為年化 9.11%（2026-08-29）。

    中位數也是 9.11%，`<` 把整叢掃進昂貴組，得到便宜組 1 筆／昂貴組 15 筆。
    **關鍵不是「樣本還不夠」，是「這樣分下去永遠不夠」**——模型每選一次
    同樣的價位，就同時把中位數釘在原地、又往昂貴組加一筆。
    """
    positions = [
        position("cheap1", rate=0.00015, opened_at="2026-08-16T21:30:43+08:00", closed_at="2026-08-18T18:35:22+08:00"),
    ] + [
        position(f"same{i}", rate=0.00024971,
                 opened_at="2026-08-20T00:00:00+08:00", closed_at="2026-08-20T12:00:00+08:00")
        for i in range(5)
    ]

    split = hold_time.split_by_rate(hold_time.summarize(positions, now=NOW))

    assert split.pivot_rate == 0.00024971
    assert split.cheaper.settled == 1 and split.pricier.settled == 5
    assert split.at_pivot == 5
    assert split.degenerate is True
    # 退化與「比不出來」是兩件事：後者只說現在不夠，前者說再等也不會夠
    assert split.comparable is False


def test_樣本分散時分界不算退化():
    """便宜組餵得飽的時候，不該再喊「這個分界不會自己好」。"""
    positions = [
        position("cheap1", rate=0.00015, opened_at="2026-08-20T00:00:00+08:00", closed_at="2026-08-21T00:00:00+08:00"),
        position("cheap2", rate=0.00016, opened_at="2026-08-20T00:00:00+08:00", closed_at="2026-08-21T04:00:00+08:00"),
        position("cheap3", rate=0.00017, opened_at="2026-08-20T00:00:00+08:00", closed_at="2026-08-21T08:00:00+08:00"),
        position("rich1", rate=0.00026027, opened_at="2026-08-21T00:00:00+08:00", closed_at="2026-08-21T02:00:00+08:00"),
        position("rich2", rate=0.00027, opened_at="2026-08-21T00:00:00+08:00", closed_at="2026-08-21T04:00:00+08:00"),
        position("rich3", rate=0.0002729, opened_at="2026-08-21T00:00:00+08:00", closed_at="2026-08-21T06:00:00+08:00"),
    ]

    split = hold_time.split_by_rate(hold_time.summarize(positions, now=NOW))

    assert split.degenerate is False


def test_年化印起來相同但日利率不同的那一筆要分開數():
    """**兩個「相同」不能混講。**

    0.00024972 與 0.00024971 的年化都印成 9.11%，但 `<` 只看日利率。
    報告若只講「完全相等」那個數字，讀的人會照逐筆那一段數出多一筆，
    然後以為報告算錯了——所以兩個數字都要拿得到。
    """
    positions = [
        position("cheap1", rate=0.00015, opened_at="2026-08-16T21:30:43+08:00", closed_at="2026-08-18T18:35:22+08:00"),
    ] + [
        position(f"same{i}", rate=0.00024971,
                 opened_at="2026-08-20T00:00:00+08:00", closed_at="2026-08-20T12:00:00+08:00")
        for i in range(5)
    ] + [
        position("almost", rate=0.00024972,
                 opened_at="2026-08-20T00:00:00+08:00", closed_at="2026-08-20T12:00:00+08:00"),
    ]

    split = hold_time.split_by_rate(hold_time.summarize(positions, now=NOW))

    assert split.at_pivot == 5            # 日利率完全相等
    assert split.displayed_at_pivot == 6  # 年化印出來相同
    assert split.degenerate is True


def test_已結束不足兩筆時分不出組():
    summary = hold_time.summarize([position(closed_at=None)], now=NOW)

    # 回 None 而不是回兩組都是零的空殼，上層才會說「還分不出來」。
    assert hold_time.split_by_rate(summary) is None


def test_空清單不會爆炸():
    summary = hold_time.summarize([], now=NOW)

    assert summary.total == 0
    assert summary.mean_hours is None
    assert summary.median_hours is None
    assert summary.mean_completion is None
    assert summary.censored_ratio == 0.0
