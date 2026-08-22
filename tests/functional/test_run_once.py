# -*- coding: utf-8 -*-
"""`BotEngine.run_once()` 的功能測試：一整輪巡檢的流程與落帳。

用真的策略層與真的 SQLite，只把交易所換成替身——要驗證的是「各步驟有沒有
照順序發生、資料有沒有正確落地」，而不是單一函式的計算結果。
"""

import pytest

from core import bot_engine
from core.bot_engine import BotEngine
from strategies.frr_plus import FrrPlusStrategy
from utils.exceptions import FatalError, RetryableError, SkipCycleError


def make_engine(logger, notifier, strategy, client, repository, cancel_settle_seconds=3, **kwargs):
    """組一台引擎並保留參照。

    交易面通知推的是**狀態轉換**，所以驗證它必須在**同一台引擎上跑好幾輪**——
    每輪都新建一台的話，`_offers_live` 永遠是 None，測到的只有「啟動後首輪」那一種。
    """
    return BotEngine(
        logger,
        notifier,
        strategy,
        client,
        repository,
        cancel_settle_seconds=cancel_settle_seconds,
        **kwargs,
    )


def run_once(logger, notifier, strategy, client, repository, cancel_settle_seconds=3):
    """組一台引擎跑單輪，讓下面的測試專注在流程與落帳本身。"""
    make_engine(logger, notifier, strategy, client, repository, cancel_settle_seconds).run_once()


class FakeClient:
    """可設定餘額、FRR、取消結果與掛單行為的交易所替身。

    `active_offers` / `positions` / `book` 預設都是空的，等同「場上沒有我們的單、
    沒有任何已借出部位、拿不到市場深度」——這正是多數既有測試想要的乾淨起點。
    要驗證「條件沒變就不重掛」或成交偵測的測試，各自把它們設起來。
    """

    def __init__(
        self,
        balance=600.0,
        frr=0.0002,
        cancelled=None,
        offer_effects=None,
        active_offers=None,
        positions=None,
        book=None,
        trades=None,
        candles=None,
        cancel_takes_effect=True,
    ):
        self.balance = balance
        self.frr = frr
        self.cancelled = cancelled if cancelled is not None else []
        # offer_effects：每次掛單要拋的例外或回傳值；不設定就一律成功
        self.offer_effects = list(offer_effects) if offer_effects else None
        self.offers = []
        self.cancel_calls = 0
        self.active_offers = list(active_offers) if active_offers else []
        # positions 可以是「每輪一份」的清單，用來模擬第 N 輪才成交
        self.positions = list(positions) if positions else []
        self.position_calls = 0
        self.book = list(book) if book else []
        self.trades = list(trades) if trades else []
        self.candles = list(candles) if candles else []
        # 取消是非同步的：交易所回應成功不代表單子已經離場（D011／D031）。
        # 設 False 就模擬「回應說取消了，但單子還在場上」——2026-08-16 19:31 的真實情況。
        self.cancel_takes_effect = cancel_takes_effect

    def cancel_active_offers(self, currency):
        self.cancel_calls += 1
        # 取消之後場上就沒有我們的單了，而那些錢會回到可用餘額——替身不模擬這件事的話，
        # 「取消後用真實餘額重算」那條路徑永遠會算出 0，測不到真正的行為。
        released = [dict(offer) for offer in self.active_offers]
        if not self.cancel_takes_effect:
            return self.cancelled or released
        self.balance += sum(float(offer["amount"]) for offer in released)
        self.active_offers = []
        # `cancelled` 有設定就用它（既有測試靠它模擬「取消了東西」），否則回報實際釋放的單
        return self.cancelled or released

    def get_active_offers(self, currency=None):
        return list(self.active_offers)

    def get_active_positions(self, currency):
        self.position_calls += 1
        return list(self.positions)

    def get_funding_book(self, currency):
        return list(self.book)

    def get_recent_trades(self, currency, limit=1000):
        return list(self.trades)

    def get_rate_candles(self, currency, period=2, timeframe="1h", limit=240):
        return list(self.candles)

    def get_available_balance(self, currency):
        return self.balance

    def get_frr(self, currency):
        return self.frr

    def create_loan_offer(self, currency, amount, rate, duration):
        self.offers.append((currency, amount, rate, duration))
        if self.offer_effects:
            effect = self.offer_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            if effect is not None:
                return effect
        return {
            "status": "submitted",
            "id": 1000 + len(self.offers),
            "symbol": f"f{currency}",
            "amount": amount,
            "rate": rate,
            "period": duration,
        }


@pytest.fixture
def strategy():
    return FrrPlusStrategy(
        {
            "strategy": {
                "min_required_usd": 150,
                "min_loan_size_usd": 150,
                "spread_count": 3,
                "spread_step_pct": 0.15,
                "premium_rate": 0.0002,
                "minimum_rate": 0.0001,
                "long_duration_threshold": 0.00082,
                "short_duration": 2,
                "long_duration": 30,
            }
        }
    )


@pytest.fixture
def no_sleep(monkeypatch):
    """攔下等待餘額釋放的 sleep，記錄秒數。"""
    calls = []
    monkeypatch.setattr(bot_engine.time, "sleep", lambda seconds: calls.append(seconds))
    return calls


def offers_in_db(repository):
    return [dict(row) for row in repository.connection.execute("SELECT * FROM loan_offers ORDER BY id")]


class TestHappyPath:
    def test_places_every_planned_offer(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        client = FakeClient(balance=600.0, frr=0.0002)
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert len(client.offers) == 3
        assert [amount for _, amount, _, _ in client.offers] == [200.0, 200.0, 200.0]

    def test_records_every_offer_in_db(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        client = FakeClient(balance=600.0, frr=0.0002)
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        rows = offers_in_db(repository)
        assert len(rows) == 3
        assert {row["status"] for row in rows} == {"submitted"}
        assert [row["offer_id"] for row in rows] == ["1001", "1002", "1003"]

    def test_writes_state_with_frr_and_summary(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        client = FakeClient(balance=600.0, frr=0.0002)
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        state = repository.get_state()
        assert state["last_frr"] == pytest.approx(0.0002)
        assert state["last_run_at"] is not None
        assert "掛出 3 筆掛單" in state["last_action"]
        assert "600.0 USD" in state["last_action"]

    def test_routine_cycle_does_not_push_to_line(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """例行巡檢只寫日誌，不推 LINE（見 DECISIONS.md D024）。

        LINE 免費方案每月 200 則，巡檢間隔 600 秒等於一天 144 輪——每輪推一則
        不到兩天就把額度用光，之後真正的故障告警一則都送不出去。
        這條測試就是釘住「不要再把例行事件接回通知管道」。

        2026-08-16 起交易面通知上線（P2-4），但推的是**狀態轉換**：第一輪掛上去
        會推一則，之後每輪原價重掛屬於無事發生。所以這裡從第二輪開始數——
        **只要有人把它改回「每輪都推」，這條就會紅燈。**
        """
        engine = make_engine(fake_logger, fake_notifier, strategy, FakeClient(), repository)
        engine.run_once()
        pushed_after_first_cycle = len(fake_notifier.sent)

        engine.run_once()
        engine.run_once()

        assert len(fake_notifier.sent) == pushed_after_first_cycle
        assert any("本輪巡檢完成" in text for text in fake_logger.messages["info"])

    def test_logs_balance_and_frr(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        run_once(fake_logger, fake_notifier, strategy, FakeClient(), repository)
        joined = "\n".join(fake_logger.messages["info"])
        assert "可用 USD 餘額" in joined
        assert "目前 FRR" in joined


class TestCancelBeforeReoffer:
    """每輪全取消重掛（DECISIONS.md D011）：取消後必須等餘額釋放再查餘額。"""

    def test_always_cancels_first(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        client = FakeClient()
        run_once(fake_logger, fake_notifier, strategy, client, repository)
        assert client.cancel_calls == 1

    def test_waits_for_settlement_when_something_was_cancelled(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(cancelled=[{"id": 1}])
        run_once(fake_logger, fake_notifier, strategy, client, repository, cancel_settle_seconds=5)
        assert no_sleep == [5]

    def test_no_wait_when_nothing_was_cancelled(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """沒有舊掛單就不必空等，否則每輪都白白多花幾秒。"""
        run_once(fake_logger, fake_notifier, strategy, FakeClient(cancelled=[]), repository)
        assert no_sleep == []


class TestSkipPaths:
    """略過本輪的兩條路徑：心跳仍要更新，因為機器人是活著且判斷正確的。"""

    @pytest.mark.parametrize("frr", [None, 0.0, -0.0001])
    def test_invalid_frr_skips_cycle(
        self, frr, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(frr=frr)
        with pytest.raises(SkipCycleError, match="FRR 無效"):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.offers == []
        state = repository.get_state()
        assert state["last_run_at"] is not None
        assert state["last_action"] == "FRR 無效，略過本輪"

    def test_insufficient_balance_skips_cycle(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """餘額不足時，訊息要講得出**具體是多少對多少**（TASKS.md A1）。

        舊版寫死一句「可放貸金額低於最低門檻或單筆最小量」——那句話在策略的
        六個出口裡有五個是錯的，而且沒有任何數字可以核對。
        """
        client = FakeClient(balance=100.0, frr=0.0002)
        with pytest.raises(SkipCycleError, match="可用餘額 100.00 USD 低於下限 150.00 USD"):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.offers == []
        state = repository.get_state()
        assert state["last_run_at"] is not None
        assert state["last_frr"] == pytest.approx(0.0002)
        # 落帳的理由要跟丟出來的例外講同一件事，否則事後對不起來
        assert "可用餘額 100.00 USD" in state["last_action"]

    def test_skip_writes_no_offers(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        client = FakeClient(balance=100.0)
        with pytest.raises(SkipCycleError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)
        assert offers_in_db(repository) == []

    def test_skip_sends_no_notification(self, fake_logger, fake_notifier, strategy, repository, no_sleep):
        with pytest.raises(SkipCycleError):
            run_once(fake_logger, fake_notifier, strategy, FakeClient(frr=None), repository)
        assert fake_notifier.sent == []


class TestOfferFailure:
    """掛單 API 無法 rollback：同一輪前幾筆若已成功，錢就已經出去了。"""

    @pytest.mark.parametrize("error", [RetryableError("逾時"), FatalError("金鑰無效")])
    def test_failure_is_recorded_then_raised(
        self, error, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(balance=600.0, offer_effects=[None, error])
        with pytest.raises(type(error)):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        rows = offers_in_db(repository)
        assert [row["status"] for row in rows] == ["submitted", "failed"]
        assert rows[1]["offer_id"] is None
        assert str(error) in rows[1]["detail"]

    def test_remaining_offers_are_not_attempted(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(balance=600.0, offer_effects=[None, RetryableError("逾時")])
        with pytest.raises(RetryableError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)
        assert len(client.offers) == 2  # 第三筆不再嘗試

    def test_failed_round_does_not_write_success_state(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(balance=600.0, offer_effects=[RetryableError("逾時")])
        with pytest.raises(RetryableError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        state = repository.get_state()
        assert state["last_action"] is None
        assert state["last_frr"] is None

    def test_failed_round_pushes_the_rejection_not_a_success(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """拒單要推，但推的必須是「被拒絕」，不能推成「掛單已上線」。"""
        client = FakeClient(offer_effects=[RetryableError("逾時")])
        with pytest.raises(RetryableError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert len(fake_notifier.sent) == 1
        assert "掛單被交易所拒絕" in fake_notifier.sent[0]
        assert "上線" not in fake_notifier.sent[0]

    def test_first_offer_failure_records_only_one_row(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(offer_effects=[FatalError("拒單")])
        with pytest.raises(FatalError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)
        assert len(offers_in_db(repository)) == 1


class TestExchangeReportedValues:
    def test_db_uses_exchange_values_not_plan(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """部分成交時交易所回報的金額會與計畫不同，落帳要以交易所為準。"""
        client = FakeClient(
            balance=600.0,
            offer_effects=[
                {"status": "submitted", "id": 9, "symbol": "fUSD", "amount": 150.0,
                 "rate": 0.00051, "period": 30},
                None,
                None,
            ],
        )
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        first = offers_in_db(repository)[0]
        assert (first["amount"], first["rate"], first["duration"]) == (150.0, 0.00051, 30)


class TestConsecutiveRounds:
    def test_offers_accumulate_across_rounds(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(balance=600.0)
        for _ in range(3):
            run_once(fake_logger, fake_notifier, strategy, client, repository)
        assert len(offers_in_db(repository)) == 9

    def test_state_reflects_the_latest_round(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        client = FakeClient(balance=600.0)
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        client.balance = 300.0
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert "掛出 2 筆掛單" in repository.get_state()["last_action"]


class TestTradeEventNotifications:
    """交易面通知（TASKS.md P2-4）推的是**狀態轉換**，不是每輪的結果。

    這一整組測試的存在理由是額度：LINE 免費方案每月 200 則 ≈ 每天 6.6 則，
    而巡檢間隔 600 秒等於一天 144 輪。**「每輪推一則」1.4 天就把整月燒光**，
    之後真正的故障告警一則都送不出去。所以下面每一條都在釘同一件事：
    只有「場上有沒有我們的單」這個值變了才推。
    """

    def test_first_successful_cycle_announces_itself(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """剛啟動時我們沒看過「有單」的狀態，第一次掛上去算轉換。

        部署完最想確認的就是機器人回來了、而且真的把單掛上去了。
        """
        engine = make_engine(fake_logger, fake_notifier, strategy, FakeClient(), repository)
        engine.run_once()

        assert len(fake_notifier.sent) == 1
        assert "啟動後首輪" in fake_notifier.sent[0]

    def test_offers_disappearing_is_pushed_once(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """有單 → 沒單。這是目前唯一能察覺「錢可能借出去了」的訊號。"""
        client = FakeClient(balance=600.0)
        engine = make_engine(fake_logger, fake_notifier, strategy, client, repository)
        engine.run_once()

        client.balance = 0.0
        for _ in range(3):
            with pytest.raises(SkipCycleError):
                engine.run_once()

        assert len(fake_notifier.sent) == 2, "連續三輪沒單只該推一則，不是三則"
        assert "掛單已不在場上" in fake_notifier.sent[1]

    def test_never_claims_the_money_was_lent_out(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """餘額歸零也可能是資金被搬到別的錢包（P2-1 之前分不出來）。"""
        client = FakeClient(balance=600.0)
        engine = make_engine(fake_logger, fake_notifier, strategy, client, repository)
        engine.run_once()

        client.balance = 0.0
        with pytest.raises(SkipCycleError):
            engine.run_once()

        assert "成交了" not in fake_notifier.sent[1].splitlines()[0]

    def test_coming_back_online_is_pushed(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """沒單 → 有單也是轉換：錢回來了、單重新掛上去了，值得一則。"""
        client = FakeClient(balance=600.0)
        engine = make_engine(fake_logger, fake_notifier, strategy, client, repository)
        engine.run_once()

        client.balance = 0.0
        with pytest.raises(SkipCycleError):
            engine.run_once()

        client.balance = 600.0
        engine.run_once()

        assert len(fake_notifier.sent) == 3
        assert "掛單已重新上線" in fake_notifier.sent[2]

    def test_starting_with_no_money_is_silent(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """剛啟動就沒錢不是轉換——我們沒看過「有單」，沒有東西消失。"""
        engine = make_engine(
            fake_logger, fake_notifier, strategy, FakeClient(balance=0.0), repository
        )
        with pytest.raises(SkipCycleError):
            engine.run_once()

        assert fake_notifier.sent == []

    def test_invalid_frr_also_counts_as_offers_gone(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """FRR 抓不到同樣代表這一輪場上沒有我們的單——單已經在流程開頭被取消了。"""
        client = FakeClient(balance=600.0)
        engine = make_engine(fake_logger, fake_notifier, strategy, client, repository)
        engine.run_once()

        client.frr = None
        with pytest.raises(SkipCycleError):
            engine.run_once()

        assert "掛單已不在場上" in fake_notifier.sent[1]
        assert "FRR 無效" in fake_notifier.sent[1]

    def test_rejection_lets_the_next_success_be_announced(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """拒單那一輪的掛單已全被取消，場上是空的；下一輪掛回去要說一聲。"""
        client = FakeClient(balance=600.0, offer_effects=[RetryableError("逾時")])
        engine = make_engine(fake_logger, fake_notifier, strategy, client, repository)
        with pytest.raises(RetryableError):
            engine.run_once()

        engine.run_once()

        assert "掛單被交易所拒絕" in fake_notifier.sent[0]
        assert "掛單已重新上線" in fake_notifier.sent[1]

    def test_switch_off_stops_pushing_but_keeps_logging(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """額度的安全閥：關掉的是通知，不是紀錄。"""
        engine = make_engine(
            fake_logger, fake_notifier, strategy, FakeClient(), repository, push_trade_events=False
        )
        engine.run_once()

        assert fake_notifier.sent == []
        assert any("交易面事件" in text for text in fake_logger.messages["info"])

    def test_dry_run_offers_are_marked_as_such(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """dry-run 沒有真的送到交易所，不標的話會讓人以為錢已經在市場上了。"""
        client = FakeClient(
            offer_effects=[{"status": "dry_run", "amount": 200.0, "rate": 0.0002, "duration": 2}] * 3
        )
        engine = make_engine(fake_logger, fake_notifier, strategy, client, repository)
        engine.run_once()

        assert "dry-run" in fake_notifier.sent[0]


# 2026-08-19 05:03:24 +0800，取自那天場上唯一一張單的真實回應（見 D038）。
OFFER_CREATED_MS = 1_787_087_004_000


def live_offer(offer_id=1, amount=200.0, rate=0.0004, period=2, created_at_ms=OFFER_CREATED_MS):
    """場上一筆掛單，欄位與 `client.get_active_offers()` 的回傳一致。

    `created_at_ms` 預設帶真實值而不是 `None`：真實 API 一定給這個欄位，
    替身比真的乾淨正是 D026 那個 bug 溜過去的原因。
    """
    return {
        "id": offer_id,
        "symbol": "fUSD",
        "created_at_ms": created_at_ms,
        "amount": amount,
        "rate": rate,
        "period": period,
    }


class TestKeepsQueuePosition:
    """條件沒變就不重掛——這一條保護的是**排隊位置**（見 DECISIONS.md D030）。

    同利率下是時間優先（先掛先成交）。每輪無條件取消重掛，等於以 600 秒為週期
    把自己送回隊伍末端，一天 144 次；而這個價位的成交本來就是陣發的，
    每次歸零都可能正好錯過那一波。
    """

    def test_identical_offer_is_left_untouched(self, fake_logger, fake_notifier, strategy,
                                               repository, no_sleep):
        # 錢全掛在場上，可用餘額因此是 0——這正是真實運作時的樣子
        client = FakeClient(balance=0.0, frr=0.0002, active_offers=[live_offer()])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.cancel_calls == 0
        assert client.offers == []

    def test_committed_money_counts_as_disposable(self, fake_logger, fake_notifier, strategy,
                                                  repository, no_sleep):
        """掛在場上的錢也是我們的錢。

        只看可用餘額的話，單子一掛出去餘額就變 0，策略會以為沒錢可放而回傳空計畫，
        於是每輪都得「先取消才有錢算」——等於強迫自己每輪重掛。
        """
        client = FakeClient(balance=0.0, frr=0.0002, active_offers=[live_offer()])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        # 有算出計畫（而且判定與場上一致），不是走「餘額不足」那條路
        assert any("維持場上" in message or "維持不動" in message
                   for message in fake_logger.messages["info"])

    def test_drift_within_tolerance_does_not_requote(self, fake_logger, fake_notifier, strategy,
                                                     repository, no_sleep):
        """市場價位每輪都有小數點後幾位的漂移。

        沒有容差的話這條保護形同虛設——每輪都會判定「不一樣」而重掛，
        跟改之前一模一樣（P2-4 已經在通知額度上踩過同一個坑，見 D029）。
        """
        client = FakeClient(balance=0.0, frr=0.0002,
                            active_offers=[live_offer(rate=0.0004 * 1.015)])  # 差 1.5%
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.cancel_calls == 0

    def test_drift_beyond_tolerance_requotes(self, fake_logger, fake_notifier, strategy,
                                             repository, no_sleep):
        client = FakeClient(balance=0.0, frr=0.0002,
                            active_offers=[live_offer(rate=0.0004 * 1.05)])  # 差 5%
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.cancel_calls == 1
        assert len(client.offers) == 1

    def test_different_period_requotes(self, fake_logger, fake_notifier, strategy, repository,
                                       no_sleep):
        client = FakeClient(balance=0.0, frr=0.0002, active_offers=[live_offer(period=30)])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.cancel_calls == 1

    def test_different_amount_requotes(self, fake_logger, fake_notifier, strategy, repository,
                                       no_sleep):
        # 場上掛著 200，但錢包裡又多了 50 可以放——可支配變成 250，
        # 計畫金額因此與場上那筆不同，這時就該重掛把多的錢也掛出去
        client = FakeClient(balance=50.0, frr=0.0002, active_offers=[live_offer(amount=200.0)])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.cancel_calls == 1
        assert [amount for _, amount, _, _ in client.offers] == [250.0]

    def test_different_offer_count_requotes(self, fake_logger, fake_notifier, strategy,
                                            repository, no_sleep):
        client = FakeClient(balance=0.0, frr=0.0002,
                            active_offers=[live_offer(offer_id=1), live_offer(offer_id=2)])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.cancel_calls == 1

    def test_empty_plan_never_withdraws_a_live_offer(self, fake_logger, fake_notifier,
                                                     repository, no_sleep):
        """策略說「這個市場不值得掛」時，**已經在場上的單不要撤**。

        那張單是用更早、也就是更好的市場條件掛出去的；撤掉只會把排隊位置還給市場，
        換來一輪空手。
        """
        from strategies.orderbook_depth import OrderBookDepthStrategy

        # minimum_rate 高到整個市場都不值得掛 → 計畫為空
        strategy = OrderBookDepthStrategy(
            {"strategy": {"minimum_rate": 0.9, "spread_count": 1, "target_queue_usd": 1000}}
        )
        client = FakeClient(balance=0.0, frr=0.0002, active_offers=[live_offer()],
                            book=[{"rate": 0.00025, "period": 2, "amount": 500.0}])

        with pytest.raises(SkipCycleError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.cancel_calls == 0


def market_trades(rate=0.00025, count=60, period=2):
    """同天期等額成交，金額加權中位數就是 `rate`。

    筆數要過 `min_trade_samples`，否則測到的是「樣本不足所以不掛」那條出口。
    """
    base = 1_786_879_800_000
    offsets = (-0.000002, 0.0, 0.000002)
    return [
        {
            "mts": base + index * 15_000,
            "amount": 25_000.0,
            "rate": rate + offsets[index % 3],
            "period": period,
        }
        for index in range(count)
    ]


class TestCheaperRepostMustPayForItself:
    """**把價格往下調**的重掛要先證明划得來（DECISIONS.md D034，源自 D031）。

    2026-08-16 19:31 機器人送出取消，25 秒後那張單就成交了：**是市場先一步吃單，
    才沒有把上線以來的第一筆成交親手砍掉。** 那一輪低價牆把候選價位往下拖 15%，
    而隊伍只縮短 2.7%——用確定的利息換一點點速度。

    只管往下這一個方向，因為兩邊的不確定性擺放方式相反：往下調時放棄的利息是確定的、
    換來的速度是估的；往上調時剛好相反。只在「估的那半邊是行動的理由」時才要求它過關。

    與 `TestKeepsQueuePosition` 的分工：那邊擋的是「條件其實沒變」，
    這邊擋的是「條件真的變了，但這個方向的變動不值得動手」。
    """

    @staticmethod
    def make_strategy(**overrides):
        from strategies.orderbook_depth import OrderBookDepthStrategy

        config = {"spread_count": 1, "target_queue_usd": 1_000_000}
        config.update(overrides)
        return OrderBookDepthStrategy({"strategy": config})

    # 19:31 的形狀：底端一道低價牆把候選價位往下拖，但牆就排在我們前面，
    # 所以隊伍幾乎沒有縮短——利率掉很多、速度沒換到。
    WALLED = [
        {"rate": 0.00021, "period": 2, "amount": 1_820_000.0},
        {"rate": 0.00025, "period": 2, "amount": 50_000.0},
        {"rate": 0.00035, "period": 2, "amount": 5_000_000.0},
    ]
    # 對照組：只降 4% 就跳過 200 萬 USD 的隊伍——這種降價換得回來。
    # 兩組的差別正是這條判準在量的東西：降 15% 跳過 182 萬不划算，
    # 降 4% 跳過 200 萬划算。差在**放棄的利息**，不在跳過多少錢。
    WORTH_IT = [
        {"rate": 0.00024, "period": 2, "amount": 1_000.0},
        {"rate": 0.00025, "period": 2, "amount": 2_000_000.0},
        {"rate": 0.00035, "period": 2, "amount": 5_000_000.0},
    ]

    def test_cheaper_and_barely_faster_is_refused(self, fake_logger, fake_notifier,
                                                  repository, no_sleep):
        client = FakeClient(balance=0.0, frr=0.0002,
                            active_offers=[live_offer(rate=0.00025)],
                            book=self.WALLED, trades=market_trades(rate=0.00025))
        run_once(fake_logger, fake_notifier, self.make_strategy(), client, repository)

        assert client.cancel_calls == 0
        assert client.offers == []

    def test_it_is_the_repost_path_that_gets_blocked(self, fake_logger, fake_notifier,
                                                     repository, no_sleep):
        """擋下來的必須是「條件真的變了」那條路。

        沒有這一條，上面那個測試可能只是 `_plans_match()` 判定相同、或策略整輪不掛，
        什麼都沒驗證到。
        """
        strategy = self.make_strategy()
        plans = strategy.build_offer_plan(200.0, 0.0002, self.WALLED,
                                          market_trades(rate=0.00025))

        assert plans, "策略本輪確實有算出計畫"
        assert plans[0].rate < 0.00025, "而且比場上那張便宜"
        engine = make_engine(fake_logger, fake_notifier, strategy, FakeClient(), repository)
        assert not engine._plans_match([live_offer(rate=0.00025)], plans), "2% 容差擋不住"

    def test_cheaper_but_much_faster_is_allowed(self, fake_logger, fake_notifier,
                                                repository, no_sleep):
        """速度真的換到了就該重掛——這條保護不是「一律不准降價」。"""
        client = FakeClient(balance=0.0, frr=0.0002,
                            active_offers=[live_offer(rate=0.00025)],
                            book=self.WORTH_IT, trades=market_trades(rate=0.00025))
        run_once(fake_logger, fake_notifier, self.make_strategy(), client, repository)

        assert client.cancel_calls == 1
        assert len(client.offers) == 1

    def test_repricing_upward_is_never_blocked(self, fake_logger, fake_notifier,
                                               repository, no_sleep):
        """往上調不套用這條判準：多賺的利息是確定的，讓它說了算。

        實測支持這個方向——2026-08-16 深夜的簿子上，2% 容差擋不住的 64 個往上調
        價位，重掛的期望值全部為正，連前方只剩 411 USD 的那一檔都是（D034）。
        """
        book = [
            {"rate": 0.00025, "period": 2, "amount": 50_000.0},
            {"rate": 0.00028, "period": 2, "amount": 100_000.0},
            {"rate": 0.00035, "period": 2, "amount": 5_000_000.0},
        ]
        client = FakeClient(balance=0.0, frr=0.0002,
                            active_offers=[live_offer(rate=0.00025)],
                            book=book, trades=market_trades())
        run_once(fake_logger, fake_notifier, self.make_strategy(), client, repository)

        assert client.cancel_calls == 1

    def test_new_money_is_always_put_to_work(self, fake_logger, fake_notifier,
                                             repository, no_sleep):
        """錢包裡多了錢就一定重掛：`spread_count=1` 時那是唯一的投入手段，
        少賺的價差遠小於讓那筆錢繼續空轉。"""
        client = FakeClient(balance=500.0, frr=0.0002,
                            active_offers=[live_offer(rate=0.00025, amount=200.0)],
                            book=self.WALLED, trades=market_trades(rate=0.00025))
        run_once(fake_logger, fake_notifier, self.make_strategy(), client, repository)

        assert client.cancel_calls == 1

    def test_lowest_rate_offer_decides(self, fake_logger, fake_notifier, repository, no_sleep):
        """場上有好幾筆時看**利率最低**的那筆：先成交的一定是它。"""
        client = FakeClient(
            balance=0.0, frr=0.0002,
            active_offers=[live_offer(offer_id=1, rate=0.00025, amount=100.0),
                           live_offer(offer_id=2, rate=0.00033, amount=100.0)],
            book=self.WALLED, trades=market_trades(rate=0.00025),
        )
        run_once(fake_logger, fake_notifier, self.make_strategy(), client, repository)

        assert client.cancel_calls == 0

    def test_live_offer_queue_is_logged_with_a_clear_subject(self, fake_logger, fake_notifier,
                                                             repository, no_sleep):
        """日誌要分得出「候選價位排在哪」與「場上那張單排在哪」。

        19:31 的誤讀就是這麼來的：日誌只有前者，卻被當成後者。
        """
        client = FakeClient(balance=0.0, frr=0.0002,
                            active_offers=[live_offer(rate=0.00025)],
                            book=self.WALLED, trades=market_trades(rate=0.00025))
        run_once(fake_logger, fake_notifier, self.make_strategy(), client, repository)

        assert any("場上掛單排隊位置" in line for line in fake_logger.messages["info"])
        assert any("掛單排隊位置估計" in line for line in fake_logger.messages["info"])

    def test_strategy_without_queue_information_still_requotes(self, fake_logger, fake_notifier,
                                                               strategy, repository, no_sleep):
        """`FrrPlusStrategy` 沒有 `describe_queue()`——沒有這個數字就不能否決，
        但也不能因此炸掉或整輪卡住。"""
        client = FakeClient(balance=0.0, frr=0.0002,
                            active_offers=[live_offer(rate=0.0004 * 1.05)])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.cancel_calls == 1

    def test_no_abstention_noise_from_a_strategy_without_queues(self, fake_logger, fake_notifier,
                                                                strategy, repository, no_sleep):
        """沒有 `describe_queue()` 不是資料缺口，是模型裡本來就沒有隊伍。

        每輪印一句「無法判斷」只會變成噪音——棄權的日誌只在**有這個概念但答不出來**
        時才有意義。
        """
        client = FakeClient(balance=0.0, frr=0.0002,
                            active_offers=[live_offer(rate=0.0004 * 1.05)])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert not any("棄權" in line for line in fake_logger.messages["info"])


class TestGateAbstainsWhenItCannotSee:
    """越界時棄權，不是偷偷否決（TASKS.md A2-a、DECISIONS.md D037）。

    2026-08-20 的實測形狀：候選價位與場上那張單**雙雙高過可見簿子**，於是
    `describe_queue()` 對兩者回同一個截斷值，`利息 ÷ (等待 + 借出期間)` 的分母約掉，
    判準退化成純比利率——而前置條件已經保證候選比較便宜，**答案因此恆定為「划不來」**。
    當天 30 輪的日誌全是 `前方 3,535,093 → 3,535,093 USD`，兩個數字一樣就是自白。

    **一個永遠給同一個答案的判斷式，等於沒有判斷式**——差別只在它看起來像有。
    """

    # **一定要用 `ExpectedValueStrategy`**：候選價位取自 K 線的 high，
    # 所以它算得出「簿子上根本看不到」的價位——而 `OrderBookDepthStrategy` 的候選
    # 永遠是簿子上存在的某一檔，越界在它身上不可能發生。這個 bug 只存在於現行策略。
    @staticmethod
    def make_strategy(strategy_config, **overrides):
        from strategies.expected_value import ExpectedValueStrategy

        config = dict(spread_count=1, minimum_rate=0.0001, market_floor_pct=0.85,
                      ev_min_hits=5, ev_min_candles=48)
        config.update(overrides)
        return ExpectedValueStrategy(strategy_config(**config))

    # 整本簿子都在我們兩個價位之下——這正是 08-19／08-20 的真實形狀：
    # 可見最高只有年化 9.04%（這裡 0.00022 ≈ 年化 8.03%），
    # 而場上那張單掛 0.000268（年化 9.78%）、候選價位 0.00026（年化 9.49%）。
    BELOW_US = [
        {"rate": 0.00020, "period": 2, "amount": 1_500_000.0},
        {"rate": 0.00022, "period": 2, "amount": 2_000_000.0},
    ]
    # 可見範圍蓋得住兩個價位的對照組。
    COVERS_US = [
        {"rate": 0.00020, "period": 2, "amount": 1_500_000.0},
        {"rate": 0.00030, "period": 2, "amount": 2_000_000.0},
    ]

    @staticmethod
    def candles(high=0.00026, spike=0.00027, count=60):
        """多數小時掃到 `high`、每 10 根一次掃到 `spike`。

        期望值因此選中 `high`（年化 9.49%）：`spike` 雖然更高，但平均要多等 5 小時，
        在 48 小時的天期面前換不回來。選出來的價位比場上那張 0.000268 低 3.08%
        ——**剛好越過 2% 容差**，於是這一輪真的會走到守門檻那段程式碼。
        這組數字取自 2026-08-20：場上 9.78%、候選 9.50%、可見簿子最高 9.04%。
        """
        return [
            {
                "mts": 1_786_968_000_000 + index * 3_600_000,
                "open": high,
                "close": high,
                "high": spike if index % 10 == 0 else high,
                "low": 0.0001,
                "volume": 4_000_000.0,
            }
            for index in range(count)
        ]

    def make_client(self, **overrides):
        settings = dict(balance=0.0, frr=0.0002,
                        active_offers=[live_offer(rate=0.000268)],
                        book=self.BELOW_US, trades=market_trades(rate=0.00022))
        settings.update(overrides)
        client = FakeClient(**settings)
        client.candles = self.candles()
        return client

    def test_out_of_range_does_not_veto_the_repost(self, fake_logger, fake_notifier,
                                                   repository, no_sleep, strategy_config):
        """比不出來就不擋——重掛照常發生。

        **這一條會鬆開目前唯一擋著往下調價的東西**（D037 自己記過這個風險）：
        修好之後，這段期間的行為由 `_plans_match()` 的 2% 容差與策略自己決定，
        真正的重掛政策是 A2-b，要等 M1／M2 的回測工具。
        """
        client = self.make_client()
        run_once(fake_logger, fake_notifier, self.make_strategy(strategy_config), client,
                 repository)

        assert client.cancel_calls == 1
        assert len(client.offers) == 1

    def test_the_candidate_really_is_cheaper(self, fake_logger, fake_notifier,
                                             repository, no_sleep, strategy_config):
        """先證明測到的是**往下調價**那條路，不是「條件沒變」或「整輪不掛」。

        少了這一條，上面那個測試可能什麼都沒驗證到。
        """
        strategy = self.make_strategy(strategy_config)
        plans = strategy.build_offer_plan(200.0, 0.0002, self.BELOW_US,
                                          market_trades(rate=0.00022), self.candles())

        assert plans, "策略本輪確實有算出計畫"
        assert plans[0].rate < 0.000268, "而且比場上那張便宜"
        engine = make_engine(fake_logger, fake_notifier, strategy, FakeClient(), repository)
        assert not engine._plans_match([live_offer(rate=0.000268)], plans), "2% 容差擋不住"

    def test_abstention_is_logged(self, fake_logger, fake_notifier, repository, no_sleep,
                                  strategy_config):
        """棄權也要出聲，否則只是把「偷偷否決」換成「偷偷放行」（D026）。"""
        run_once(fake_logger, fake_notifier, self.make_strategy(strategy_config),
                 self.make_client(), repository)

        assert any("棄權" in line for line in fake_logger.messages["info"])
        assert not any("補不回" in line for line in fake_logger.messages["info"])

    def abstain_line(self, fake_logger):
        return next(line for line in fake_logger.messages["info"] if "棄權" in line)

    def test_it_says_both_when_both_are_out_of_range(self, fake_logger, fake_notifier,
                                                     repository, no_sleep, strategy_config):
        """兩個都越界（08-19／08-20 的常態）就兩個都點名。"""
        run_once(fake_logger, fake_notifier, self.make_strategy(strategy_config),
                 self.make_client(), repository)

        line = self.abstain_line(fake_logger)
        assert "場上那張單（年化 9.78%）" in line
        assert "候選價位（年化 9.49%）" in line

    def test_it_blames_the_live_offer_when_only_the_live_offer_is_out_of_range(
        self, fake_logger, fake_notifier, repository, no_sleep, strategy_config
    ):
        """**這一條就是 D4 那個 bug 的形狀。**

        可見上限落在舊價與新價之間——場上那張 9.78% 越界、候選 9.49% 看得清清楚楚。
        舊版會寫「候選價位年化 9.49% 已超出可見簿子（可見最高年化 9.67%）」，
        **那句話裡的兩個數字自己就矛盾**（9.49 < 9.67）。

        市場走弱時這是最常見的形狀，不是角落案例。
        """
        between = [
            {"rate": 0.00020, "period": 2, "amount": 1_000_000.0},
            {"rate": 0.000265, "period": 2, "amount": 500_000.0},  # 9.67%，夾在兩個價位中間
        ]
        run_once(fake_logger, fake_notifier, self.make_strategy(strategy_config),
                 self.make_client(book=between), repository)

        line = self.abstain_line(fake_logger)
        assert "場上那張單（年化 9.78%）超出可見簿子" in line
        assert "候選價位" not in line, "候選價位看得到，不可以被點名"

    def test_it_names_the_setting_when_the_conversion_is_disabled(
        self, fake_logger, fake_notifier, repository, no_sleep, strategy_config
    ):
        """第三個成因：兩個價位都看得到，是換算速率被關掉了。

        舊版連這種情況都寫「候選價位已超出可見簿子」——而當下根本沒有任何東西越界。
        """
        engine = make_engine(fake_logger, fake_notifier, self.make_strategy(strategy_config),
                             self.make_client(book=self.COVERS_US), repository,
                             queue_clear_usd_per_hour=0)
        engine.run_once()

        line = self.abstain_line(fake_logger)
        assert "queue_clear_usd_per_hour 設為 0" in line
        assert "超出可見簿子" not in line, "沒有任何東西越界，不可以這樣寫"

    def test_it_says_it_cannot_see_the_book_at_all(self, fake_logger, fake_notifier,
                                                   repository, no_sleep, strategy_config):
        """拿不到簿子就說拿不到——不要編一個「可見最高年化」出來。"""
        engine = make_engine(fake_logger, fake_notifier, self.make_strategy(strategy_config),
                             self.make_client(book=[]), repository)
        engine.run_once()

        line = self.abstain_line(fake_logger)
        assert "拿不到訂單簿" in line
        assert "可見最高年化" not in line

    def test_queue_logs_say_at_least_when_out_of_range(self, fake_logger, fake_notifier,
                                                       repository, no_sleep, strategy_config):
        """A3：兩行排隊位置日誌都要改口說「至少」，並點出超出可見簿子。"""
        run_once(fake_logger, fake_notifier, self.make_strategy(strategy_config),
                 self.make_client(), repository)

        live_line = next(line for line in fake_logger.messages["info"]
                         if "場上掛單排隊位置" in line)
        candidate_line = next(line for line in fake_logger.messages["info"]
                              if "掛單排隊位置估計" in line)

        assert "至少" in live_line and "超出可見簿子" in live_line
        assert "至少" in candidate_line and "超出可見簿子" in candidate_line

    def test_in_range_numbers_are_still_reported_as_measurements(self, fake_logger, fake_notifier,
                                                                 repository, no_sleep,
                                                                 strategy_config):
        """**對照組：只有簿子的可見範圍不同，兩個價位一模一樣。**

        場上仍是 0.000268、候選仍是 0.00026，改的只有簿子蓋不蓋得住它們。
        蓋得住的時候排隊金額是真的量測值，守門檻**照樣否決**——
        A2-a 修的是「算不出來時偷偷否決」，不是把這條判準拿掉。
        """
        client = self.make_client(book=self.COVERS_US)
        run_once(fake_logger, fake_notifier, self.make_strategy(strategy_config), client,
                 repository)

        assert client.cancel_calls == 0, "比得出來，而且這個方向不划算 → 維持不動"
        assert any("補不回" in line for line in fake_logger.messages["info"])
        assert not any("至少" in line for line in fake_logger.messages["info"])
        assert not any("棄權" in line for line in fake_logger.messages["info"])


class TestCancelActuallyTookEffect:
    """取消送出之後，要問「單子真的離場了嗎」，不能用餘額回推（D031）。

    這兩件事會分岔：19:31 取消送出後餘額確實沒回來，但原因不是「還沒生效」，
    而是那張單根本沒被取消掉、25 秒後成交了。只看餘額的話兩種情況長得一模一樣，
    處置卻完全相反——單子還在場上時再掛一筆就是雙倍曝險。
    """

    def test_offers_still_live_means_no_new_offer(self, fake_logger, fake_notifier, strategy,
                                                  repository, no_sleep):
        client = FakeClient(balance=0.0, frr=0.0002,
                            active_offers=[live_offer(rate=0.0004 * 1.05)],
                            cancel_takes_effect=False)

        with pytest.raises(SkipCycleError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.cancel_calls == 1
        assert client.offers == []  # **沒有再掛一筆**

    def test_it_is_reported_as_a_warning_not_as_offers_gone(self, fake_logger, fake_notifier,
                                                            strategy, repository, no_sleep):
        """場上明明還有單，不能推「掛單已不在場上」——那是猜錯方向的訊息。"""
        client = FakeClient(balance=0.0, frr=0.0002,
                            active_offers=[live_offer(rate=0.0004 * 1.05)],
                            cancel_takes_effect=False)

        with pytest.raises(SkipCycleError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert any("仍有" in line for line in fake_logger.messages["warning"])
        assert not any("不在場上" in message for message in fake_notifier.sent)

    def test_state_records_why_the_round_did_nothing(self, fake_logger, fake_notifier, strategy,
                                                     repository, no_sleep):
        client = FakeClient(balance=0.0, frr=0.0002,
                            active_offers=[live_offer(rate=0.0004 * 1.05)],
                            cancel_takes_effect=False)

        with pytest.raises(SkipCycleError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert "取消未生效" in repository.get_state()["last_action"]

    def test_normal_cancel_is_unaffected(self, fake_logger, fake_notifier, strategy,
                                         repository, no_sleep):
        client = FakeClient(balance=0.0, frr=0.0002,
                            active_offers=[live_offer(rate=0.0004 * 1.05)])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.cancel_calls == 1
        assert len(client.offers) == 1


class TestFillDetection:
    """成交偵測（TASKS.md P2-1）。

    在它之前，錢借出去之後餘額歸零，機器人只會寫一句「可放貸金額不足，略過本輪」
    ——**跟錢包本來就是空的一模一樣**，沒有通知、DB 也沒有任何一筆記錄。
    """

    @staticmethod
    def position(position_id="1", amount=160.0, rate=0.00025, period=2):
        return {"id": position_id, "amount": amount, "rate": rate, "period": period,
                "kind": "credit", "opened_at": 1786872920000}

    def test_new_position_is_announced(self, fake_logger, fake_notifier, strategy, repository,
                                       no_sleep):
        client = FakeClient(balance=600.0, frr=0.0002, positions=[self.position()])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert any("資金已借出" in message for message in fake_notifier.sent)

    def test_new_position_is_recorded(self, fake_logger, fake_notifier, strategy, repository,
                                      no_sleep):
        client = FakeClient(balance=600.0, frr=0.0002, positions=[self.position()])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        rows = list(repository.connection.execute("SELECT * FROM funding_positions"))
        assert len(rows) == 1
        assert rows[0]["position_id"] == "1"

    def test_same_position_is_announced_only_once(self, fake_logger, fake_notifier, strategy,
                                                  repository, no_sleep):
        client = FakeClient(balance=600.0, frr=0.0002, positions=[self.position()])
        engine = make_engine(fake_logger, fake_notifier, strategy, client, repository)
        engine.run_once()
        engine.run_once()

        assert sum("資金已借出" in message for message in fake_notifier.sent) == 1

    def test_closed_position_is_announced(self, fake_logger, fake_notifier, strategy, repository,
                                          no_sleep):
        client = FakeClient(balance=600.0, frr=0.0002, positions=[self.position()])
        engine = make_engine(fake_logger, fake_notifier, strategy, client, repository)
        engine.run_once()
        client.positions = []
        engine.run_once()

        assert any("資金已收回" in message for message in fake_notifier.sent)

    def test_fill_suppresses_the_vaguer_offers_gone_message(self, fake_logger, fake_notifier,
                                                            strategy, repository, no_sleep):
        """成交已經解釋了掛單為什麼不見，就不必再推一則「掛單已不在場上」。

        同一件事講兩遍只是白燒額度——每月只有 200 則（D024）。
        """
        client = FakeClient(balance=600.0, frr=0.0002)
        engine = make_engine(fake_logger, fake_notifier, strategy, client, repository)
        engine.run_once()  # 先掛出去，讓 _offers_live 變成 True

        # 下一輪：錢被借走（餘額歸零 + 出現部位）
        client.balance = 0.0
        client.positions = [self.position()]
        with pytest.raises(SkipCycleError):
            engine.run_once()

        assert any("資金已借出" in message for message in fake_notifier.sent)
        assert not any("掛單已不在場上" in message for message in fake_notifier.sent)

    def test_offers_gone_without_a_fill_still_warns(self, fake_logger, fake_notifier, strategy,
                                                   repository, no_sleep):
        """沒有成交卻掛單消失＝錢可能被搬走，這種才要推「掛單已不在場上」。"""
        client = FakeClient(balance=600.0, frr=0.0002)
        engine = make_engine(fake_logger, fake_notifier, strategy, client, repository)
        engine.run_once()

        client.balance = 0.0  # 餘額沒了，但也沒有任何已借出部位
        with pytest.raises(SkipCycleError):
            engine.run_once()

        assert any("掛單已不在場上" in message for message in fake_notifier.sent)

    def test_positions_are_checked_before_anything_is_cancelled(self, fake_logger, fake_notifier,
                                                                strategy, repository, no_sleep):
        """對帳要在動手之前。

        取消掛單會改變場上狀態，先動手再對帳的話，「這一輪成交了嗎」就永遠答不出來。
        """
        client = FakeClient(balance=600.0, frr=0.0002, active_offers=[live_offer(rate=0.001)])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.position_calls == 1
        assert client.cancel_calls == 1


class TestMarketDataReachesTheStrategy:
    """成交資料要真的送到策略手上，而且要在日誌留下對照（D033）。

    2026-08-16 夜間那次事故在日誌上完全看不出異常：機器人只寫了
    「掛出 344.30 USD，利率 0.000150」，而當時借款人實際付的是 0.00026。
    日誌裡沒有任何一個數字能讓人看出那是半價。
    """

    @staticmethod
    def market_trades(rate=0.00025, count=60):
        """同天期等額成交，金額加權中位數就是 `rate`。

        筆數要過 `min_trade_samples`，否則測到的是「樣本不足所以不掛」那條出口。
        """
        base = 1_786_879_800_000
        offsets = (-0.000002, 0.0, 0.000002)
        return [
            {
                "mts": base + index * 15_000,
                "amount": 25_000.0,
                "rate": rate + offsets[index % 3],
                "period": 2,
            }
            for index in range(count)
        ]

    def test_trades_are_fetched_and_handed_to_the_strategy(self, fake_logger, fake_notifier,
                                                           repository, no_sleep):
        from strategies.orderbook_depth import OrderBookDepthStrategy

        strategy = OrderBookDepthStrategy(
            {"strategy": {"spread_count": 1, "target_queue_usd": 1_000_000}}
        )
        client = FakeClient(
            balance=344.30,
            frr=0.0002,
            book=[{"rate": 0.00025, "period": 2, "amount": 500_000.0}],
            trades=self.market_trades(),
        )
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert len(client.offers) == 1
        _, _, rate, _ = client.offers[0]
        assert rate == 0.00025

    def test_market_rate_is_written_to_the_log(self, fake_logger, fake_notifier,
                                               repository, no_sleep):
        from strategies.orderbook_depth import OrderBookDepthStrategy

        strategy = OrderBookDepthStrategy(
            {"strategy": {"spread_count": 1, "target_queue_usd": 1_000_000}}
        )
        client = FakeClient(
            balance=344.30,
            frr=0.0002,
            book=[{"rate": 0.00025, "period": 2, "amount": 500_000.0}],
            trades=self.market_trades(),
        )
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert any("市場常態成交價" in line for line in fake_logger.messages["info"])

    def test_no_trades_means_no_offer_even_with_a_healthy_book(self, fake_logger, fake_notifier,
                                                               repository, no_sleep):
        """看不見成交價就不掛——那正是這次事故發生時唯一擋得住它的條件。"""
        from strategies.orderbook_depth import OrderBookDepthStrategy

        strategy = OrderBookDepthStrategy(
            {"strategy": {"spread_count": 1, "target_queue_usd": 1_000_000}}
        )
        client = FakeClient(
            balance=344.30,
            frr=0.0002,
            book=[{"rate": 0.00025, "period": 2, "amount": 500_000.0}],
            trades=[],
        )

        with pytest.raises(SkipCycleError):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.offers == []

    def test_a_cheap_wall_no_longer_halves_the_offer_rate(self, fake_logger, fake_notifier,
                                                          repository, no_sleep):
        """端到端重現 2026-08-16 21:21：簿子底端一道 182 萬的低價牆。

        修好之前，這一輪會掛出 0.00015（年化 5.47%）並且真的成交。
        """
        from strategies.orderbook_depth import OrderBookDepthStrategy

        strategy = OrderBookDepthStrategy(
            {"strategy": {"spread_count": 1, "target_queue_usd": 1_000_000}}
        )
        client = FakeClient(
            balance=344.30,
            frr=0.0002,
            book=[
                {"rate": 0.00015, "period": 2, "amount": 1_821_212.68},
                {"rate": 0.00025, "period": 2, "amount": 500_000.0},
            ],
            trades=self.market_trades(),
        )
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        _, _, rate, _ = client.offers[0]
        assert rate == pytest.approx(0.0002125, rel=1e-6)


class TestIdleTimeMeasurement:
    """閒置時間量測（D038）。

    **這一組測的是「看得見」，不是「做決定」。** 2026-08-19 那張單掛了 18 小時
    沒成交，而每一輪的日誌都只寫「維持不動以保住排隊位置」——閒置資金的年化是
    0%，卻是整個系統裡唯一沒有任何一行日誌在計時的東西（D037 預警、隔天成真）。

    要不要因為等太久而降價是策略問題，得先有這些數字才談得上（D036 的順序）。
    """

    @pytest.fixture
    def frozen_now(self, monkeypatch):
        """把時鐘釘在掛單後 18.1 小時，重現 2026-08-19 23:09 的現場。"""
        from datetime import datetime, timedelta, timezone

        moment = datetime(2026, 8, 19, 23, 9, 42, tzinfo=timezone(timedelta(hours=8)))
        monkeypatch.setattr(bot_engine.clock, "now", lambda: moment)
        return moment

    def test_閒置時數與機會成本都寫進日誌(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep, frozen_now
    ):
        client = FakeClient(balance=0.0, active_offers=[live_offer(rate=0.000268, amount=344.36)])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        idle_lines = [m for m in fake_logger.messages["info"] if "已閒置" in m]
        assert len(idle_lines) == 1
        # 05:03:24 → 23:09:42 是 18.1 小時
        assert "18.1 小時" in idle_lines[0]
        # 機會成本 = 344.36 × 0.000268 × 18.1 / 24 ≈ 0.0696 USD
        assert "0.069" in idle_lines[0] or "0.070" in idle_lines[0]

    def test_有當初的預估就拿來對照(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep, frozen_now
    ):
        """18.1 小時遠超過當初估的 6 小時——**日誌要講出這件事**，不能只報時數。"""
        repository.record_wait_forecast(
            1,
            {
                "rate": 0.000268,
                "mean_hours": 6.0,
                "median_hours": 3.5,
                "p75_hours": 12.0,
                "hits": 54,
                "censored_ratio": 0.0,
                "window_hours": 168,
            },
        )
        client = FakeClient(balance=0.0, active_offers=[live_offer(rate=0.000268, amount=344.36)])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        line = next(m for m in fake_logger.messages["info"] if "已閒置" in m)
        assert "中位數 3.5h" in line
        assert "四分之三在 12.0h 內" in line
        assert "等待估計偏樂觀" in line

    def test_還在預估之內就不要說偏樂觀(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep, frozen_now
    ):
        """**「偏樂觀」這句話要留給真的偏樂觀的時候**，否則它會變成雜訊而被忽略。"""
        repository.record_wait_forecast(
            1,
            {
                "rate": 0.000268,
                "mean_hours": 30.0,
                "median_hours": 24.0,
                "p75_hours": 40.0,
                "hits": 20,
                "censored_ratio": 0.1,
                "window_hours": 168,
            },
        )
        client = FakeClient(balance=0.0, active_offers=[live_offer(rate=0.000268)])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        line = next(m for m in fake_logger.messages["info"] if "已閒置" in m)
        assert "仍在當初預估的中位數之內" in line
        assert "偏樂觀" not in line

    def test_沒有預估時明說沒有而不是留白(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep, frozen_now
    ):
        """這張表 2026-08-19 才加，在它之前掛出去的單本來就沒有預估。"""
        client = FakeClient(balance=0.0, active_offers=[live_offer()])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        line = next(m for m in fake_logger.messages["info"] if "已閒置" in m)
        assert "沒有留下當初的等待預估" in line

    def test_拿不到建立時間就說不知道(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep, frozen_now
    ):
        """**不要用本輪時間硬湊一個看起來很小的閒置時數**——那會謊報成「剛掛上去」。"""
        client = FakeClient(balance=0.0, active_offers=[live_offer(created_at_ms=None)])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert any(
            "沒有建立時間，無法計算已閒置多久" in m for m in fake_logger.messages["info"]
        )
        assert not any("已閒置" in m and "小時" in m for m in fake_logger.messages["info"])

    def test_維持不動的那條路徑也要量到(
        self, fake_logger, fake_notifier, repository, no_sleep, frozen_now, strategy_config
    ):
        """**這是最重要的一條**：單子閒置最久的輪次，走的正是「維持不動」這條提早
        return 的路徑。量測放在它後面的話，就永遠只在重掛那一輪才量得到。
        """
        from strategies.frr_plus import FrrPlusStrategy

        strategy = FrrPlusStrategy(strategy_config(spread_count=1, premium_rate=0.0002))
        # 場上那張單與策略算出來的一致 → 走 `_plans_match` 的維持不動路徑
        client = FakeClient(balance=0.0, active_offers=[live_offer(rate=0.0004, amount=200.0)])
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert any("維持不動" in m for m in fake_logger.messages["info"])
        assert any("已閒置" in m for m in fake_logger.messages["info"])


class TestWaitForecastIsPersisted:
    """掛單當下的等待預估要落 DB（D038）。

    **這是唯一「不存就永遠消失」的那一半資料**：實際等了多久事後算得出來，
    但「掛出去那一刻我們以為要等多久」只存在於那一輪的記憶體。少了它，
    事後只能拿今天的模型解釋昨天的決定——D036 記的正是這個病。
    """

    def forecasts_in_db(self, repository):
        return [
            dict(row)
            for row in repository.connection.execute("SELECT * FROM offer_wait_forecasts")
        ]

    def test_期望值策略掛單後留下預估(
        self, fake_logger, fake_notifier, repository, no_sleep, strategy_config
    ):
        from strategies.expected_value import ExpectedValueStrategy

        strategy = ExpectedValueStrategy(
            strategy_config(
                spread_count=1,
                minimum_rate=0.0001,
                market_floor_pct=0.85,
                ev_min_hits=5,
                ev_min_candles=48,
            )
        )
        highs = [0.00025 if i % 5 else 0.00030 for i in range(60)]
        candles = [
            {
                "mts": 1_786_968_000_000 + i * 3_600_000,
                "open": high,
                "close": high,
                "high": high,
                "low": 0.0001,
                "volume": 4_000_000.0,
            }
            for i, high in enumerate(highs)
        ]
        client = FakeClient(
            balance=400.0,
            book=[{"rate": 0.0002, "period": 2, "amount": 500_000.0}],
            trades=market_trades(rate=0.00025),
        )
        client.candles = candles
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        saved = self.forecasts_in_db(repository)
        assert len(saved) == 1
        assert saved[0]["window_hours"] == 168
        assert saved[0]["hits"] >= 5
        # 三個統計量都要存下來，只留平均就等於把重尾那件事再丟一次
        assert saved[0]["median_hours"] > 0
        assert saved[0]["p75_hours"] >= saved[0]["median_hours"]

    def test_沒有期望值能力的策略不會爆(
        self, fake_logger, fake_notifier, strategy, repository, no_sleep
    ):
        """`frr_plus` 不做期望值評估，硬要它回答只會多一個會爆的地方。"""
        client = FakeClient(balance=400.0)
        run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert self.forecasts_in_db(repository) == []
        assert offers_in_db(repository)  # 掛單本身照常完成


class TestHoldTimeIsLogged:
    """部位收回時，日誌要講出「實際借了多久」（見 DECISIONS.md D040）。

    `strategies/expected_value.py` 假設每筆都借滿天期（`hold_hours = period × 24`），
    而實測多數部位被提前還款。這一行是把那個落差變成「每次還款都看得見」的東西
    ——不必等有人想到去翻資料庫，才發現模型跟現實對不上。
    """

    @staticmethod
    def position(position_id="1", amount=344.41, rate=0.00026027, period=2,
                 opened_at=1_787_063_460_000):
        return {"id": position_id, "amount": amount, "rate": rate, "period": period,
                "kind": "credit", "opened_at": opened_at}

    def _close_one(self, fake_logger, fake_notifier, strategy, repository, **kwargs):
        client = FakeClient(balance=600.0, frr=0.0002, positions=[self.position(**kwargs)])
        engine = make_engine(fake_logger, fake_notifier, strategy, client, repository)
        engine.run_once()
        client.positions = []
        engine.run_once()
        return fake_logger.messages["info"]

    def test_收回時講出實際持有時間(self, fake_logger, fake_notifier, strategy, repository,
                                    no_sleep):
        messages = self._close_one(fake_logger, fake_notifier, strategy, repository)

        assert any("實際借出" in message and "小時" in message for message in messages)

    def test_收回時講出佔預定天期多少(self, fake_logger, fake_notifier, strategy, repository,
                                      no_sleep):
        """完成率才是對照模型假設的那個數字——48 小時的預定實際上用掉幾成。"""
        messages = self._close_one(fake_logger, fake_notifier, strategy, repository)

        assert any("佔預定 48 小時的" in message for message in messages)

    def test_剛收回的部位不可以被講成仍在生息中(self, fake_logger, fake_notifier, strategy,
                                                repository, no_sleep):
        """反向斷言，釘住 `sync_positions()` 回傳值要帶著 `closed_at`。

        回傳的 dict 是 UPDATE 之前查出來的，少補那一行的話「剛收回」與「還開著」
        長得一模一樣，於是還款的當下會被講成「至少借了 N 小時（仍在生息中）」。
        """
        messages = self._close_one(fake_logger, fake_notifier, strategy, repository)
        hold_lines = [message for message in messages if "佔預定" in message]

        assert hold_lines
        assert not any("仍在生息中" in message for message in hold_lines)
        assert not any("至少" in message for message in hold_lines)

    def test_起算時間壞掉時安靜跳過不影響巡檢(self, fake_logger, fake_notifier, strategy,
                                                repository, no_sleep):
        """量測是輔助資訊，不能因為它算不出來就讓一輪巡檢失敗。"""
        messages = self._close_one(fake_logger, fake_notifier, strategy, repository,
                                   opened_at=None)

        # 收回本身照講，只是少了持有時間那一行。
        assert any("資金已回到融資錢包" in message for message in messages)

    def test_沒有部位收回時不會憑空多出持有時間那一行(self, fake_logger, fake_notifier,
                                                      strategy, repository, no_sleep):
        client = FakeClient(balance=600.0, frr=0.0002, positions=[self.position()])
        engine = make_engine(fake_logger, fake_notifier, strategy, client, repository)
        engine.run_once()

        assert not any("佔預定" in message for message in fake_logger.messages["info"])
