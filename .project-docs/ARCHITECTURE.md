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

目前程式碼仍是 `config/ modules/ utils/` 三層的 dry-run 雛型，尚未拆成下方目標架構：

```
ShuyuLendingBot/
├── config/settings.py          # YAML + 環境變數 + secrets 載入（已可用）
├── modules/
│   ├── exchange_client.py      # BitfinexClient：連線、餘額、FRR、取消掛單、建立掛單
│   │                            # （皆已修正為呼叫 ccxt raw API，見 D009／D010）
│   ├── lending_strategy.py     # LendingStrategy.build_offer_plan()：門檻/拆單/天期判斷骨架
│   └── line_notifier.py        # LineNotifier：呼叫已停用的 LINE Notify（永遠失敗）
├── utils/logger.py             # BotLogger：FileHandler，無 rotation
└── main.py                     # 單次執行流程，無主迴圈
```

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
  `.project-docs/CCXT_BITFINEX_API_INVESTIGATION.md`（D009／D010）。尚待：`cancel_active_offers`
  目前未被主迴圈呼叫，`create_loan_offer` 尚無「只補掛差額」判斷（見 TASKS.md M2）。
- `api/rate_limiter.py`（尚未建立）：`with_retry` decorator，包住所有實盤 API 呼叫，捕捉
  `ccxt.RateLimitExceeded` / `ccxt.NetworkError`，指數退避重試。
- `strategies/frr_plus.py`（現 `modules/lending_strategy.py`）：FRR+ 雙發彈夾策略純函式，
  輸入餘額與 FRR，輸出 `OfferPlan` 清單。目前僅有門檻判斷 + 拆單 + 天期判斷，尚缺「只補掛差額」、
  spread 多階梯、`maxtolend` 風控。
- `core/bot_engine.py`（尚未建立，現由 `main.py` 承擔單次流程）：`run_once` 單輪巡檢、
  `run_forever` 主迴圈；分類處理 `RetryableError` / `FatalError` / `SkipCycleError`。
- `db/repository.py`（尚未建立）：SQLite WAL 模式，記錄掛單流水、每日收益彙總、`bot_state`。
- `notify/line_messaging.py`（現 `modules/line_notifier.py`）：目前呼叫已停用的 LINE Notify
  端點（`notify-api.line.me`），需改寫為 LINE Messaging API push
  （`POST https://api.line.me/v2/bot/message/push`）。
- `utils/logger.py`：目前用 `logging.FileHandler`，24 小時常駐後單檔會無限增大，需改
  `RotatingFileHandler`。

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
- 持久化：SQLite（WAL 模式），非外部 DB —— 見 DECISIONS D006。
- 部署：Podman 容器化為主線 —— 見 DECISIONS D007。
