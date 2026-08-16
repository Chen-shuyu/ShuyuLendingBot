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
        client = FakeClient(balance=100.0, frr=0.0002)
        with pytest.raises(SkipCycleError, match="低於最低門檻"):
            run_once(fake_logger, fake_notifier, strategy, client, repository)

        assert client.offers == []
        state = repository.get_state()
        assert state["last_run_at"] is not None
        assert state["last_frr"] == pytest.approx(0.0002)
        assert "略過本輪" in state["last_action"]

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


def live_offer(offer_id=1, amount=200.0, rate=0.0004, period=2):
    """場上一筆掛單，欄位與 `client.get_active_offers()` 的回傳一致。"""
    return {"id": offer_id, "symbol": "fUSD", "amount": amount, "rate": rate, "period": period}


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
