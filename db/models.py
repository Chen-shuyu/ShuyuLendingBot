# -*- coding: utf-8 -*-
"""資料表結構定義（DDL）。

三張表對應 archive/SHUYU_PROJECT_PLAN.md 第 4.2 節：

- `loan_offers`：掛單流水，每一筆掛單嘗試（成功或失敗）都留一列。
- `earnings_daily`：每日收益彙總。目前只建表與介面，尚未接上資料來源
  （需另走 Bitfinex ledger 端點查利息入帳，見 TASKS.md）。
- `bot_state`：單列狀態表，供崩潰後恢復與外部健康檢查讀取。

時間一律以 UTC 的 ISO 8601 字串存放，避免容器與主機時區不一致造成誤判。
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

ALL_STATEMENTS = (
    CREATE_LOAN_OFFERS,
    CREATE_LOAN_OFFERS_INDEX,
    CREATE_EARNINGS_DAILY,
    CREATE_BOT_STATE,
    INIT_BOT_STATE_ROW,
)
