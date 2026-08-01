# ARCHITECTURE

## 整體架構

單帳戶、單幣種（USD）的 Bitfinex Funding 放貸機器人。以 `ccxt.bitfinex`（V1/V2 已合併，
見 D009）為交易所適配層，Bitfinex funding 相關操作一律呼叫 ccxt 的 raw/implicit API，
不使用（也不存在）統一方法（見 D010）。策略層以純函式計算掛單利率/金額/天期，
核心迴圈（`while True` + `time.sleep`）
每輪巡檢：取消未成交舊單 → 查詢可用餘額 → 抓 FRR → 產生掛單計畫 → 送出掛單 → 寫入 DB →
LINE 推播摘要 → 休眠。程式以 Podman 容器化常駐部署（見 D007），崩潰由容器 restart 策略頂起。

```
[main.py bootstrap]
        │
        ▼
[core/bot_engine.py]  ──主迴圈狀態機──┐
        │                            │
        ├─ api/bitfinex_client.py ───┤（交易所讀寫、Rate Limit 重試）
        ├─ strategies/frr_plus.py ───┤（純函式：算利率/金額/天期）
        ├─ db/repository.py ─────────┤（SQLite WAL：掛單/收益/狀態）
        └─ notify/line_messaging.py ─┘（LINE Messaging API push）
```

## 現況（尚未重構）

M3 已補齊 `api/`（重試）與 `db/`（資料層）兩個目標目錄，其餘仍是 `config/ modules/ utils/`
三層結構，尚未完成 `strategies/`、`core/`、`notify/` 的搬遷：

```
ShuyuLendingBot/
├── config/settings.py          # YAML + 環境變數 + secrets 載入（已可用）
├── api/rate_limiter.py         # RetrySettings + with_retry 指數退避（M3 新增）
├── db/
│   ├── models.py               # loan_offers / earnings_daily / bot_state 的 DDL（M3 新增）
│   └── repository.py           # SQLite WAL 讀寫封裝（M3 新增）
├── modules/
│   ├── exchange_client.py      # BitfinexClient：連線、餘額、FRR、取消掛單、建立掛單
│   │                            # （皆已修正為呼叫 ccxt raw API，見 D009／D010）
│   ├── lending_strategy.py     # LendingStrategy.build_offer_plan()：門檻/拆單/天期判斷骨架
│   └── line_notifier.py        # LineNotifier：呼叫已停用的 LINE Notify（永遠失敗）
├── utils/logger.py             # BotLogger：RotatingFileHandler（M3 改）
├── tests/                      # 三層測試 227 項（M4 新增，見 DECISIONS.md D015）
│   ├── conftest.py             # 共用 fixture 與測試替身（FakeLogger／FakeNotifier／repository）
│   ├── unit/                   # 純邏輯：策略、重試、資料層、設定、日誌、交易所客戶端
│   ├── functional/             # run_once() 巡檢流程、FailureTracker 告警去重
│   └── integration/            # dry-run 端到端、Bitfinex 公開端點格式守門（live marker）
└── main.py                     # 常駐主迴圈 + run_once + FailureTracker（尚未搬進 core/）
```

測試層與待搬遷的目錄結構是耦合的：`refactor/m4-layering` 做搬遷時，`tests/` 的 import
路徑要一併調整，改完重跑全部測試即可確認搬遷沒有改變行為。

## 目標架構（依 [SHUYU_PROJECT_PLAN.md 附錄 B.9](../archive/SHUYU_PROJECT_PLAN.md)）

```
ShuyuLendingBot/
├── config/            # 設定載入與驗證
│   ├── settings.py            # 現有，補型別驗證
│   └── config.yaml
├── api/               # 交易所適配層
│   ├── base.py                 # ExchangeClient 抽象介面
│   ├── bitfinex_client.py      # 由 modules/exchange_client.py 移入並修正 get_frr
│   └── rate_limiter.py         # with_retry decorator：指數退避
├── strategies/        # 策略層（純函式，易測試）
│   ├── base.py                 # Strategy 抽象基底
│   └── frr_plus.py             # 由 modules/lending_strategy.py 移入並擴充
├── core/
│   └── bot_engine.py           # BotEngine：run_once / run_forever 主迴圈狀態機
├── db/
│   ├── models.py                # loan_offers / earnings_daily / bot_state
│   └── repository.py            # SQLite WAL 讀寫封裝
├── notify/
│   └── line_messaging.py        # 由 modules/line_notifier.py 改寫，走 LINE Messaging API
├── utils/logger.py              # 改用 RotatingFileHandler
├── tests/{unit,functional,integration}/
├── systemd/                      # 保留供本機測試/備援用（部署主線見 D007）
├── main.py                       # 精簡為 bootstrap，主迴圈移入 core/
└── .project-docs/                # 本文件所在
```

## 主要模組

- `config/settings.py`：讀取 `config.yaml`，以環境變數與 `BFX_SECRETS_FILE` 覆蓋敏感值。已可用。
- `api/bitfinex_client.py`（現 `modules/exchange_client.py`）：封裝 `ccxt.bitfinex`，提供
  `test_connection`、`get_available_balance`、`get_frr`、`cancel_active_offers`、
  `create_loan_offer`。四者皆已修正為呼叫 ccxt 的 raw/implicit API（`public_get_ticker_symbol`／
  `private_post_auth_r_funding_offers_symbol`／`private_post_auth_w_funding_offer_cancel`／
  `private_post_auth_w_funding_offer_submit`），詳細盤點見
  `.project-docs/CCXT_BITFINEX_API_INVESTIGATION.md`（D009／D010）。讀取類與取消類已包上
  `with_retry`；`create_loan_offer()` 刻意不包（掛單不冪等，見 D013）。
- `api/rate_limiter.py`：`RetrySettings`（讀 `config.yaml` 的 `retry:` 區段）與 `with_retry`
  decorator。攔的是 `exchange_client` 已分類好的 `RetryableError` 而非 ccxt 原始例外——
  例外轉換早在各方法內做完，decorator 只負責重試，因此一行即可套用而不動內部邏輯；
  `FatalError` 直接往外拋（見 D013）。
- `strategies/frr_plus.py`（現 `modules/lending_strategy.py`）：FRR+ 策略純函式，輸入餘額與
  FRR，輸出 `OfferPlan` 清單。已含 `maxtolend` 縮量、spread 百分比遞增階梯、依單筆最小量
  自動降階、逐筆判斷天期（D011）。尚待：`maxtolend` 只管本輪掛出總額，未計入已放貸部位。
- `core/bot_engine.py`（尚未建立，現由 `main.py` 承擔）：`run_once` 單輪巡檢，順序為
  取消舊掛單 → 等待餘額釋放 → 查餘額 → 抓 FRR → 產生掛單計畫 → 逐筆掛單並落帳 →
  寫入 `bot_state` → 通知；主迴圈分類處理 `RetryableError` / `FatalError` / `SkipCycleError`，
  並以 `FailureTracker` 累計連續失敗、跨過門檻時告警一次、恢復時再通知一次（D013）。
- `db/repository.py`：SQLite WAL 模式（搭配 `synchronous=NORMAL`），記錄掛單流水、
  每日收益彙總、`bot_state`。掛單成功走 `record_offer()`、失敗走 `record_offer_failure()`——
  掛單 API 無法 rollback，同一輪前幾筆成功時錢已經出去了，只有逐筆落帳才對得出真實狀態。
  尚待：`earnings_daily` 只有表結構與 `upsert_daily_earning()` 介面，還沒有資料來源（D013）。
- `notify/line_messaging.py`（現 `modules/line_notifier.py`）：目前呼叫已停用的 LINE Notify
  端點（`notify-api.line.me`），需改寫為 LINE Messaging API push
  （`POST https://api.line.me/v2/bot/message/push`）。在那之前，M3 的連續失敗告警實際上
  只會留在日誌裡。
- `utils/logger.py`：`RotatingFileHandler`，固定檔名 + 大小輪替（預設 10MB × 5 份）。

## 刻意排除的部分

為降低複雜度並符合單帳戶單幣種現況，不採用 MikaLendingBot 的：Plugin 生態
（`PluginsManager`/`Plugin` hooks）、多 Worker/`Manager` 多執行緒架構、Web 前端頁面
（先以 CLI/日誌觀測，未來再加）。

## 關鍵技術選型

- 交易所串接：`ccxt.bitfinex`（V1/V2 已合併），取代舊專案的獨立 V1 API —— 見 DECISIONS D001、D009。
- API 呼叫方式：Bitfinex funding 相關操作一律呼叫 ccxt 的 raw/implicit API，不使用（也不存在）
  統一方法 —— 見 DECISIONS D010。
- 併發模型：單執行緒 + `time.sleep` 主迴圈，不引入 `asyncio` —— 見 DECISIONS D003。
- 通知：LINE Messaging API push，取代已停用的 LINE Notify —— 見 DECISIONS D002。
- 持久化：SQLite（WAL 模式），非外部 DB —— 見 DECISIONS D006。SQLite 檔須以 volume 掛出
  容器（`/app/data`），否則重新部署即歸零。
- 部署：Podman 容器化為主線 —— 見 DECISIONS D007。
- 可觀測：固定檔名日誌輪替、指數退避重試、`bot_state` 心跳與連續失敗告警 —— 見 DECISIONS D013。
