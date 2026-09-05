# -*- coding: utf-8 -*-
"""資料表結構定義（DDL）。

最初三張表對應 archive/SHUYU_PROJECT_PLAN.md 第 4.2 節，之後陸續長到七張：

- `loan_offers`：掛單流水，每一筆掛單嘗試（成功或失敗）都留一列。
- `earnings_daily`：每日收益彙總。目前只建表與介面，尚未接上資料來源
  （需另走 Bitfinex ledger 端點查利息入帳，見 TASKS.md P2-2）。
- `bot_state`：單列狀態表，供崩潰後恢復與外部健康檢查讀取。
- `funding_positions`：已借出部位，成交偵測與持有時間量測的依據。
- `offer_wait_forecasts`：掛單當下對「要等多久」的預估，供事後校準（D038）。
- `market_snapshots`：每輪一列的市場快照（M1）。
- `market_candles`：利率 K 線，一根一列（M1）。
- `pricing_decisions`：策略每評估過一輪就一列的定價決策（M1-b）。
- `repost_comparisons`：場上有掛單的每一輪，「保住 vs 改掛」的並排比較（M1-c）。

時間一律以帶時區偏移的 ISO 8601 字串存放（見 `repository.now_iso()`），
避免容器與主機時區不一致造成誤判；交易所給的毫秒時間戳則原樣留在 `*_mts` 欄位，
**不轉換**——那是對帳時唯一不會因為時區設定而跑掉的欄位。
"""

# 掛單流水。
# 主鍵用自增序號而非 Bitfinex 的掛單 ID：dry-run 與掛單失敗這兩種情形都拿不到
# 交易所 ID，但那些嘗試同樣需要留下紀錄，所以交易所 ID 另存 offer_id 且允許 NULL。
CREATE_LOAN_OFFERS = """
CREATE TABLE IF NOT EXISTS loan_offers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id     TEXT,
    currency     TEXT    NOT NULL,
    amount       REAL    NOT NULL,
    rate         REAL    NOT NULL,
    duration     INTEGER NOT NULL,
    status       TEXT    NOT NULL,
    detail       TEXT,
    created_at   TEXT    NOT NULL
);
"""

CREATE_LOAN_OFFERS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_loan_offers_created_at
    ON loan_offers (created_at);
"""

# 每日收益彙總。同一天同一幣別只有一列，重複寫入以 upsert 累加。
# principal_avg 允許 NULL：`upsert_daily_earning()` 以「傳 None 代表本次不更新平均本金、
# 保留舊值」為介面約定（靠 ON CONFLICT 的 COALESCE 實現）。原本宣告成 NOT NULL 會讓
# NULL 在衝突解析之前就先撞上約束，等於整條 None 路徑無法使用。
CREATE_EARNINGS_DAILY = """
CREATE TABLE IF NOT EXISTS earnings_daily (
    date          TEXT NOT NULL,
    currency      TEXT NOT NULL,
    interest      REAL NOT NULL DEFAULT 0,
    principal_avg REAL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (date, currency)
);
"""

# 已借出部位（Bitfinex 的 funding credits ＋ loans）。
#
# **為什麼一定要落地而不是只放記憶體**：成交偵測靠的是「這個 id 以前沒見過」。
# 狀態只放記憶體的話，每次重啟都會把場上所有部位當成新成交，推一輪假的成交通知
# ——而這個管道只要騙過人一次，之後就不會再被相信（同 D023、D029 的判斷）。
#
# closed_at 為 NULL 代表還在生息中；部位從交易所的清單裡消失時才補上時間，
# 這樣「什麼時候借出、什麼時候還回來」兩個時間點都留得下來，日後算實際年化
# （含閒置時間）才有依據。
CREATE_FUNDING_POSITIONS = """
CREATE TABLE IF NOT EXISTS funding_positions (
    position_id   TEXT PRIMARY KEY,
    currency      TEXT    NOT NULL,
    amount        REAL    NOT NULL,
    rate          REAL    NOT NULL,
    period        INTEGER NOT NULL,
    kind          TEXT    NOT NULL,
    opened_at     TEXT,
    first_seen_at TEXT    NOT NULL,
    closed_at     TEXT
);
"""

CREATE_FUNDING_POSITIONS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_funding_positions_open
    ON funding_positions (closed_at);
"""

# 單列狀態表。CHECK (id = 1) 從結構上保證只會有一列，不必靠程式自律。
# consecutive_failures 存進 DB 而非只放記憶體，是為了讓外部健康檢查
# （未來的容器 healthcheck）不必啟動 Python 就能判斷機器人是否已連續失敗。
CREATE_BOT_STATE = """
CREATE TABLE IF NOT EXISTS bot_state (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    last_run_at          TEXT,
    last_frr             REAL,
    last_action          TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0
);
"""

# 先插入唯一那一列，之後一律用 UPDATE，省掉每次寫入都要判斷有沒有列。
INIT_BOT_STATE_ROW = """
INSERT OR IGNORE INTO bot_state (id, consecutive_failures) VALUES (1, 0);
"""

# 掛單當下對「要等多久」的預估。**一張掛單一列，不是每輪一列**。
#
# **為什麼一定要落地**：策略每輪都會重算等待估計，所以記憶體裡永遠只有「現在這一輪
# 怎麼想」，而校準需要的是「掛出去那一刻怎麼想」。少了這張表，事後就只能拿今天的
# 模型去解釋昨天的決定——D036 記的正是這個病：結論寫死進設定檔、原始資料丟掉，
# 於是六個決策兩天內互相推翻，誰也拿不出證據。
#
# 實際等待不存在這裡，因為現有資料已經算得出來：掛單時間在 `loan_offers.created_at`
# （交易所端的權威時間另由 offers 端點的 MTS_CREATE 提供），成交時間在
# `funding_positions.opened_at`。**只有「當初的預估」是不存就永遠消失的那一半。**
CREATE_OFFER_WAIT_FORECASTS = """
CREATE TABLE IF NOT EXISTS offer_wait_forecasts (
    offer_id       TEXT PRIMARY KEY,
    rate           REAL    NOT NULL,
    mean_hours     REAL    NOT NULL,
    median_hours   REAL    NOT NULL,
    p75_hours      REAL    NOT NULL,
    hits           INTEGER NOT NULL,
    censored_ratio REAL    NOT NULL,
    window_hours   INTEGER NOT NULL,
    created_at     TEXT    NOT NULL
);
"""

# 每輪一列的市場快照（M1 市場資料落地）。
#
# **為什麼一定要落地**：在這張表之前，DB 有掛單、部位、收益、狀態、等待預估五張表，
# **沒有任何一張存過市場長什麼樣**。每次分析都得重抓即時資料，用完就丟，
# 而歷史再也回不去——D3（「一根 K 滾出 168 小時窗，價格目標就自己跳一階」）
# 到現在無法證實，正是因為當時的簿子與候選集都沒有存下來。
#
# **這張表只存觀測，不存決策。** 每個欄位都算自本輪剛抓回來的原始資料，
# 不碰策略物件的任何跨輪狀態（理由見 `core/market_snapshot.py` 的模組說明）。
# 本輪選中的價位與候選集在 `pricing_decisions`（M1-b，D043，2026-08-24 落地）
# ——**這條界線沒有因此消失，只是多了另一邊**：那張表寫在策略評估完之後，
# 而這一張寫在所有提早離開的出口之前，兩者連得起來靠的是 `snapshot_id`。
#
# 曲線與天期分佈用 JSON 存在單一欄位：它們是「一起讀才有意義」的一組數字，
# 拆成欄位會變成二十幾個 `curve_05` / `curve_10`，而且點數一改就要動 schema。
#
# **成本是實測的，不是估的**（2026-08-23 拿真實回應量過）：一列約 1.2 KB，
# 加上 K 線每輪 1～2 根，巡檢 600 秒一輪等於一天約 190 KB、一年約 68 MB。
# TASKS.md 原本寫「每輪幾百位元組」，那是還沒把簿子曲線算進去時的估計。
CREATE_MARKET_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS market_snapshots (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at               TEXT    NOT NULL,
    currency                  TEXT    NOT NULL,
    frr                       REAL,
    book_levels               INTEGER,
    book_lowest_rate          REAL,
    book_highest_rate         REAL,
    book_truncated            INTEGER,
    book_total_amount         REAL,
    book_curve_json           TEXT,
    book_period_totals_json   TEXT,
    trade_count               INTEGER,
    trade_span_minutes        REAL,
    trade_latest_mts          INTEGER,
    trade_volume              REAL,
    trade_rate_min            REAL,
    trade_rate_median         REAL,
    trade_rate_weighted_median REAL,
    trade_rate_max            REAL,
    trade_period_rates_json   TEXT,
    trade_period_counts_json  TEXT,
    candle_count              INTEGER,
    candle_latest_mts         INTEGER,
    candle_high_median        REAL,
    candle_high_p75           REAL,
    candle_high_max           REAL,
    candle_close_latest       REAL
);
"""

CREATE_MARKET_SNAPSHOTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_market_snapshots_captured_at
    ON market_snapshots (captured_at);
"""

# 利率 K 線，**一根一列**，主鍵天然去重。
#
# 為什麼不塞進 `market_snapshots`：K 線每小時才換一根，而巡檢 600 秒一輪。
# 每輪存一份 240 根的窗，等於一天寫三萬多列去講 24 根 K 的事。
#
# **UPSERT 而不是 INSERT OR IGNORE**：最新那一根還在成形中，
# 它的 high／close／volume 每一輪都可能變大。舊的 K 已經定案，重寫是同值覆蓋。
#
# 附帶好處：時間一久，這張表存的 K 線歷史會長得比 API 一次取得到的還長，
# 而那正是 M2 回測工具需要的東西。
CREATE_MARKET_CANDLES = """
CREATE TABLE IF NOT EXISTS market_candles (
    currency   TEXT    NOT NULL,
    period     INTEGER NOT NULL,
    timeframe  TEXT    NOT NULL,
    mts        INTEGER NOT NULL,
    open       REAL    NOT NULL,
    close      REAL    NOT NULL,
    high       REAL    NOT NULL,
    low        REAL    NOT NULL,
    volume     REAL    NOT NULL,
    updated_at TEXT    NOT NULL,
    PRIMARY KEY (currency, period, timeframe, mts)
);
"""

# 每一次「策略真的評估過一輪」留下的決策紀錄（M1-b 決策落地）。
#
# **為什麼跟 `market_snapshots` 分成兩張表**：兩者的寫入時機不同，而且不是每輪都成對。
# 快照在 `build_offer_plan()` **之前**就寫（那是刻意的：底下五條提早 return 的路徑
# 正好是最需要留下市場長相的輪次），決策要等策略評估完才有；資金全部借出的日子裡
# 餘額守門檻會讓 `choose_rate()` 一次都跑不到，那些輪次有市場、沒有決策。
# 併成一張表就得為「有觀測沒決策」留一整排 NULL，而 NULL 太多的表沒有人讀得懂。
#
# **這張表存的是「當時我們怎麼想」，不是「當時市場長怎樣」**（後者在
# `market_snapshots` 與 `market_candles`）。`snapshot_id` 把兩邊接起來，
# 允許 NULL——快照寫失敗不該讓決策跟著消失，那會把一個看得見的缺口變成兩個。
#
# **候選集只存價位與實質年化，不存每一個候選的等待分佈。**
# 成本是實測的：110 個候選的完整評估序列化後 17 KB，只留這兩排是 2.6 KB。
# 選中的那一個候選的完整評估另外有欄位（`chosen_*`），而其餘候選的等待分佈是
# 中間量——**排序依據是 `effective`，留下它就能回答「為什麼是這個價位」**，
# 這正是 D3 要問的。要更細的話 `market_candles` 存著同一批 K 線可以重算。
#
# ⚠ **重算不保證重現**：最新那一根 K 還在成形，事後 UPSERT 過的 high 已經不是
# 當時看到的值。所以「當時算出什麼」只有這張表留得下來，而重算出來的東西
# **是另一個問題的答案**，不可以拿來冒充當時的決策。
#
# **成本是實測的，不是估的**（2026-08-24 拿正式 DB 的 K 線跑出 109 個候選，
# 寫 200 列再 VACUUM 量檔案增長）：**一列 4,137 位元組**，含索引。
# 其中兩排候選集約 2.6 KB，其餘是 20 個 REAL 欄位與頁面開銷。
#
# 只有**評估過的輪次**才寫：資金全部借出時餘額守門檻讓 `choose_rate()` 跑不到，
# 那些輪次一列都不寫（2026-08-24 整天 130 輪就是這種）。以目前資金使用率約
# 四分之三、每天約 35 輪會評估估算，**一年約 50 MB**；
# **最壞情況（每輪都評估）一年 207 MB** ——這個數字要講出來，
# 因為它比 `market_snapshots` 的 68 MB/年 大三倍，而那是「市場一直很好、
# 錢一直掛不出去」的日子，正好也是最想回頭看的日子。
CREATE_PRICING_DECISIONS = """
CREATE TABLE IF NOT EXISTS pricing_decisions (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    decided_at                TEXT    NOT NULL,
    currency                  TEXT    NOT NULL,
    strategy                  TEXT,
    snapshot_id               INTEGER,
    chosen_rate               REAL    NOT NULL,
    chosen_effective          REAL    NOT NULL,
    chosen_mean_hours         REAL,
    chosen_median_hours       REAL,
    chosen_p75_hours          REAL,
    chosen_hits               INTEGER,
    chosen_censored_ratio     REAL,
    fastest_rate              REAL,
    fastest_mean_hours        REAL,
    fastest_effective         REAL,
    candidate_count           INTEGER NOT NULL,
    candidate_rates_json      TEXT,
    candidate_effectives_json TEXT,
    window_hours              INTEGER,
    hold_hours_assumed        REAL,
    candle_count              INTEGER,
    candle_latest_mts         INTEGER,
    pricing_knobs_json        TEXT
);
"""

CREATE_PRICING_DECISIONS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_pricing_decisions_decided_at
    ON pricing_decisions (decided_at);
"""

# 場上有掛單的每一輪，「保住它 vs 改掛本輪候選」的並排比較（M1-c，D046）。
#
# **這張表只落反事實，不改任何行為。** 它存在的理由是 D046 查出來的缺口：
# 往上調價**從頭到尾沒有判準**——`_cheaper_repost_is_not_worth_it()` 第一行就
# `if candidate.rate >= live_rate: return None`，只管往下；往上的實際規則是
# 「比場上那張高過 2% 就直接砍掉重掛，不問划不划算」。而機會成本每輪都在算，
# 算完就丟（`_log_idle_time()` 原本回傳 `None`，沒有任何判斷式讀得到）。
#
# 要補判準就得先知道「如果當時調高了會怎樣」，而那個問題**只有這張表答得出來**：
# 事後重算不行，因為最新那根 K 還在成形、事後 UPSERT 過的 `high` 已經不是當時
# 看到的值（同 `pricing_decisions` 的註解）。**沒有這批資料，A2-b 就只能拍門檻，
# 而那是 `target_queue_usd` 的死法（D032／D036）。**
#
# **一列 = 一輪，不是一筆掛單。** `live_*` 取場上利率最低的那張——與
# `_cheaper_repost_is_not_worth_it()` 和 `_log_live_queue_position()` 用同一張，
# 否則落下來的比較跟實際判斷的不是同一個對象。多筆時由 `live_offer_count` 看得出來。
#
# ## 三個已知錯的東西，寫在旁邊而不是藏起來
#
# 1. **`live_wait_hours` 不是「還要等多久」**，是「現在重新評估這個利率的等待分佈」。
#    場上那張已經等了 `live_idle_hours`，拿無記憶分佈去估剩餘等待是高估
#    ——D045 已量出等待估計整體高估 3.9 倍（五筆全部高估，1.6×～28.7×）。
#    條件機率是 M2 的題目，不是這裡。
# 2. **`hold_hours_assumed` 是已知錯的**（D040：實測完成率 51.8%，模型假設 100%）。
#    存的是**當時假設了什麼**，不是事實；兩邊都用同一個，所以並排比較仍然公平。
# 3. **`*_queue_ahead` 越界時是下界**，由 `*_queue_truncated` 標著。簿子固定截斷
#    250 檔，而 325 輪裡有 26 輪（8.0%）可見總額超過 1 億 USD——可見範圍會隨底下
#    供給的厚薄呼吸，所以那個旗標不是角落情況（TASKS.md A2）。
#
# **`live_effective` 可以是 NULL 而那一列照樣要寫**：窗內命中不足 `ev_min_hits`
# 時算不出實質年化，而 `live_hits` 會告訴你是「一次都沒掃到」還是「掃到但不夠」。
# 08-19 那張掛了 34.2 小時沒成交的單落下來就長這樣——**那正是最想留住的一列**。
#
# ## 成本是量出來的，不是估的
#
# 寫 500 列再 VACUUM 量檔案增長：**一列 418 位元組**（含索引），其中最長的
# `action_reason` 佔 126 B。比 `pricing_decisions` 的 4,137 B 小一個數量級
# ——那張表的兩排候選集就佔了 2.6 KB，而這張表沒有陣列欄位。
#
# **最壞情況（每輪都有場上掛單）一年 21 MB。** 但實際會比這稀疏得多：
# 這張表只在場上有單時寫，而成交的單在場中位數只有 2.05 小時 ≈ 12 輪
# （`scripts/wait_report.py` 的實測），其餘時間資金鎖在部位裡。
#
# ⚠ **所以別指望靠它累積樣本**：它跟 `pricing_decisions` 一樣長得極慢
# （後者 60 小時只寫了 2 列）。**這個機制的價值集中在尾端**——08-19 那種
# 掛了 34.2 小時（205 輪）沒成交的長尾，一次就會落下兩百列。
# 設計時要拿長尾當主場景，不要拿中位數（D046）。
CREATE_REPOST_COMPARISONS = """
CREATE TABLE IF NOT EXISTS repost_comparisons (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    compared_at                TEXT    NOT NULL,
    currency                   TEXT    NOT NULL,
    strategy                   TEXT,
    snapshot_id                INTEGER,
    live_offer_id              TEXT,
    live_offer_count           INTEGER NOT NULL,
    live_rate                  REAL    NOT NULL,
    live_amount                REAL,
    live_period                INTEGER,
    live_idle_hours            REAL,
    live_forgone_usd           REAL,
    live_forecast_mean_hours   REAL,
    live_forecast_median_hours REAL,
    live_forecast_p75_hours    REAL,
    live_wait_hours            REAL,
    live_hits                  INTEGER,
    live_censored_ratio        REAL,
    live_effective             REAL,
    candidate_rate             REAL    NOT NULL,
    candidate_amount           REAL,
    candidate_period           INTEGER,
    candidate_wait_hours       REAL,
    candidate_hits             INTEGER,
    candidate_censored_ratio   REAL,
    candidate_effective        REAL,
    live_queue_ahead           REAL,
    live_queue_truncated       INTEGER,
    candidate_queue_ahead      REAL,
    candidate_queue_truncated  INTEGER,
    action                     TEXT    NOT NULL,
    action_reason              TEXT,
    hold_hours_assumed         REAL,
    window_hours               INTEGER
);
"""

CREATE_REPOST_COMPARISONS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_repost_comparisons_compared_at
    ON repost_comparisons (compared_at);
"""

# 一張通用的小鍵值表，給「機器人記得自己做過什麼」這類狀態用。
#
# **為什麼是新表而不是往 `bot_state` 加欄位**：這個專案沒有 migration 機制，
# `_create_schema()` 跑的是 `CREATE TABLE IF NOT EXISTS`——**對已經存在的表，
# 在 CREATE 語句裡新增欄位是完全沒有效果的**，正式環境那顆 DB 不會長出新欄位，
# 而且不會有任何錯誤訊息（D026 那一族）。新表則天然安全。
#
# 目前唯一的用途：記住日結摘要最後推播到哪一天（D053）。
# **不要把它當成什麼都能塞的抽屜**——會被查詢、會被統計的東西應該有自己的表和欄位。
CREATE_BOT_KV = """
CREATE TABLE IF NOT EXISTS bot_kv (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);
"""

# 既有資料庫要補的欄位。**只加欄位，不改也不刪**（見 `Repository._ensure_columns()`）。
#
# 🔴 **為什麼需要這個東西**：2026-09-05 查出 `--verify` 在 D056 改設定的當下
# 就靜默失效了——40 列裡 34 列不一致，因為重播用**現在的**設定去重跑當初的決策。
# D043 存 `hold_hours_assumed` 時已經寫過理由：「**當初的預估是不存就永遠消失的
# 那一半**」。那句話當時只套用在一個旋鈕上，**而它對每一個會改變答案的旋鈕都成立**。
#
# `pricing_knobs_json` 是那句話的推廣：**存的是「當時那一輪，策略讀了哪些值」**，
# 而不是某幾個被挑出來的欄位。這樣下一次加旋鈕不必再動 schema，
# 也不會再出現「加了旋鈕、驗收工具隔天就開始說謊」。
ADD_COLUMNS = (
    ("pricing_decisions", "pricing_knobs_json", "TEXT"),
)

ALL_STATEMENTS = (
    CREATE_LOAN_OFFERS,
    CREATE_LOAN_OFFERS_INDEX,
    CREATE_EARNINGS_DAILY,
    CREATE_FUNDING_POSITIONS,
    CREATE_FUNDING_POSITIONS_INDEX,
    CREATE_BOT_STATE,
    CREATE_OFFER_WAIT_FORECASTS,
    CREATE_MARKET_SNAPSHOTS,
    CREATE_MARKET_SNAPSHOTS_INDEX,
    CREATE_MARKET_CANDLES,
    CREATE_PRICING_DECISIONS,
    CREATE_PRICING_DECISIONS_INDEX,
    CREATE_REPOST_COMPARISONS,
    CREATE_REPOST_COMPARISONS_INDEX,
    CREATE_BOT_KV,
    INIT_BOT_STATE_ROW,
)
