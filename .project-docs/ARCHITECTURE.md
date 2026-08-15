# ARCHITECTURE

## 整體架構

單帳戶、單幣種（USD）的 Bitfinex Funding 放貸機器人。以 `ccxt.bitfinex`（V1/V2 已合併，
見 D009）為交易所適配層，Bitfinex funding 相關操作一律呼叫 ccxt 的 raw/implicit API，
不使用（也不存在）統一方法（見 D010）。策略層以純函式計算掛單利率/金額/天期，
核心迴圈（`while True` + `time.sleep`）
每輪巡檢：取消未成交舊單 → 查詢可用餘額 → 抓 FRR → 產生掛單計畫 → 送出掛單 → 寫入 DB →
LINE 推播摘要 → 休眠。程式以 Podman 容器化常駐部署（見 D007），容器由 systemd --user
管理生命週期，崩潰後由 systemd 的 restart 策略頂起（見 D017）；健康檢查判定不健康時
由 podman 殺掉容器、同樣交還給 systemd 重啟，重啟次數用盡後停在 `failed` 並送出告警
（見 D020）。

**維運元件與主程式刻意分離**：`scripts/healthcheck.py` 在容器內執行、
`scripts/notify_failure.py` 在容器外（主機端）執行，兩者都只用標準函式庫、
不 import 專案任何模組。理由相同——它們執行的時機正是「東西壞掉」的時候，
不能因為專案程式碼或相依套件有問題而跟著失效，尤其 `notify_failure.py`
要報告的往往就是「容器本身已經不在了」。

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

## 目錄結構

分層搬遷已於 2026-08-15（分支 `refactor/m4-layering`）完成，目錄結構與
[SHUYU_PROJECT_PLAN.md 附錄 B.9](../archive/SHUYU_PROJECT_PLAN.md) 的目標架構一致：

```
ShuyuLendingBot/
├── config/settings.py          # YAML + 環境變數 + secrets 載入
├── api/                        # 交易所適配層
│   ├── base.py                 # ExchangeClient 抽象介面（M4 新增）
│   ├── bitfinex_client.py      # BitfinexClient：連線、餘額、FRR、取消掛單、建立掛單
│   │                            # （皆呼叫 ccxt raw API，見 D009／D010）
│   └── rate_limiter.py         # RetrySettings + with_retry 指數退避（M3 新增）
├── strategies/                 # 策略層（純函式，易測試）
│   ├── base.py                 # Strategy 介面與 OfferPlan 資料結構（M4 新增）
│   └── frr_plus.py             # FrrPlusStrategy.build_offer_plan()：門檻/拆單/天期判斷
├── core/
│   └── bot_engine.py           # BotEngine：run_once / run_forever 主迴圈狀態機、
│                                # FailureTracker、離開碼常數（M4 由 main.py 移入）
├── db/
│   ├── models.py               # loan_offers / earnings_daily / bot_state 的 DDL（M3 新增）
│   └── repository.py           # SQLite WAL 讀寫封裝（M3 新增）
├── notify/
│   └── line_messaging.py       # LineNotifier：**內容仍是已停用的 LINE Notify**，
│                                # 檔名先依目標架構定好，改寫待 LINE 憑證（見 D002、D021）
├── utils/
│   ├── logger.py               # BotLogger：RotatingFileHandler（M3 改）
│   └── exceptions.py           # RetryableError / FatalError / SkipCycleError
├── scripts/                    # 維運腳本，皆不在主程式執行路徑上、皆只用標準函式庫
│   ├── healthcheck.py          # 容器內：唯讀讀 bot_state 心跳（M4 新增，見 D016）
│   └── notify_failure.py       # 主機端：systemd 失效告警（M4 新增，見 D020）
├── systemd/
│   ├── shuyu-lending-bot.container        # 正式部署的 Quadlet 單元（D017、D020）
│   ├── shuyu-lending-bot-alert.service    # OnFailure= 觸發的告警單元（D020）
│   └── bfx-lending-bot.service            # 本機測試用，非正式部署路線
├── tests/                      # 三層測試 283 項（M4 新增，見 DECISIONS.md D015、D016）
│   ├── conftest.py             # 共用 fixture 與測試替身（FakeLogger／FakeNotifier／repository）
│   ├── unit/                   # 純邏輯：策略、重試、資料層、設定、日誌、交易所客戶端、告警腳本
│   ├── functional/             # run_once() 巡檢流程、FailureTracker 告警去重、離開碼與退出路徑
│   └── integration/            # dry-run 端到端、Bitfinex 公開端點格式守門（live marker）
├── config.yaml
├── main.py                     # 只做 bootstrap：組裝各層元件、把離開碼交給作業系統
└── .project-docs/              # 本文件所在
```

搬遷本身不改行為（見 D021），迴歸保護來自既有的 283 項測試。
結構上還沒補齊的只剩 `notify/line_messaging.py` 的內容改寫，卡在 LINE Channel 憑證。

## 主要模組

- `config/settings.py`：讀取 `config.yaml`，以環境變數與 `BFX_SECRETS_FILE` 覆蓋敏感值。已可用。
- `api/base.py`：`ExchangeClient` 抽象介面。重點不在方法簽章而在**例外契約**——實作必須
  把底層套件的例外轉成 `RetryableError` / `FatalError` 再往外拋，主迴圈才分得出「下一輪
  重試」與「直接停止」；漏一個 ccxt 例外出去就會被最外層當成未預期例外，離開碼與重啟
  決策全錯（見 D021）。
- `api/bitfinex_client.py`：封裝 `ccxt.bitfinex`，實作上述介面，提供
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
- `strategies/base.py`：`Strategy` 介面與 `OfferPlan` 資料結構——策略層與迴圈層之間的契約。
  `OfferPlan` 是**計畫值不是成交值**，落帳一律以交易所回報為準。
- `strategies/frr_plus.py`：`FrrPlusStrategy`，FRR+ 策略純函式，輸入餘額與
  FRR，輸出 `OfferPlan` 清單。已含 `maxtolend` 縮量、spread 百分比遞增階梯、依單筆最小量
  自動降階、逐筆判斷天期（D011）。尚待：`maxtolend` 只管本輪掛出總額，未計入已放貸部位。
- `core/bot_engine.py`：`BotEngine.run_once()` 單輪巡檢，順序為
  取消舊掛單 → 等待餘額釋放 → 查餘額 → 抓 FRR → 產生掛單計畫 → 逐筆掛單並落帳 →
  寫入 `bot_state` → 通知；主迴圈分類處理 `RetryableError` / `FatalError` / `SkipCycleError`，
  並以 `FailureTracker` 累計連續失敗、跨過門檻時告警一次、恢復時再通知一次（D013）。
  `run_forever()` 包住啟動檢查、主迴圈與三條退出路徑，回傳離開碼（`EXIT_OK` / 
  `EXIT_UNEXPECTED` / `EXIT_FATAL` 也定義在這裡，見 D016、D017、D019）。
- `db/repository.py`：SQLite WAL 模式（搭配 `synchronous=NORMAL`），記錄掛單流水、
  每日收益彙總、`bot_state`。掛單成功走 `record_offer()`、失敗走 `record_offer_failure()`——
  掛單 API 無法 rollback，同一輪前幾筆成功時錢已經出去了，只有逐筆落帳才對得出真實狀態。
  檔案位置由 `resolve_db_path()` 決定：`BFX_DB_PATH` 優先，相對路徑一律相對於專案根目錄
  ——**必須與 `scripts/healthcheck.py` 的同名函式算出相同結果**，兩邊分家的症狀是健康檢查
  永遠回報「尚未寫入任何心跳」而機器人其實是好的（D019）。
  尚待：`earnings_daily` 只有表結構與 `upsert_daily_earning()` 介面，還沒有資料來源（D013）。
- `notify/line_messaging.py`：**檔名已是目標名稱，內容還沒改寫**——目前呼叫已停用的 LINE Notify
  端點（`notify-api.line.me`），需改寫為 LINE Messaging API push
  （`POST https://api.line.me/v2/bot/message/push`）。在那之前，M3 的連續失敗告警實際上
  只會留在日誌裡。
- `main.py`：只做 bootstrap——載入 secrets 與 `config.yaml`、建好 logger／notifier／策略／
  交易所客戶端／`Repository`，組成 `BotEngine` 後把它回傳的離開碼交給作業系統。
  這裡不該再出現任何巡檢邏輯。
- `utils/logger.py`：`RotatingFileHandler`，固定檔名 + 大小輪替（預設 10MB × 5 份）。
- `scripts/healthcheck.py`：容器 healthcheck 的執行檔，唯讀開啟 SQLite 讀 `bot_state.last_run_at`，
  心跳超過「巡檢間隔 × 3 + 60 秒」（可由 `engine.health_max_silence_seconds` 覆寫）就以
  離開碼 1 回報 unhealthy。刻意不看 `consecutive_failures`（那是交易所端問題，重啟無益），
  也刻意不建立任何檔案或資料表——健康檢查有副作用會把「DB 掛載掉了」這個真正的問題蓋掉
  （D016）。判定 unhealthy 之後由 `HealthOnFailure=kill` 殺掉容器，重啟交還 systemd（D020）。
- `scripts/notify_failure.py`：**在容器外（主機端）執行**的失效告警，由
  `shuyu-lending-bot-alert.service` 執行，而該單元由主單元的 `OnFailure=` 觸發。
  `OnFailure=` 是每次失敗都觸發（不是只在最後放棄時），所以腳本自己查單元狀態分辨
  「systemd 正在重試」（ERROR）與「已放棄、需人工介入」（CRITICAL），查不到狀態時
  一律當成已放棄。寫入機器人日誌檔與 `bot_state.last_action`，**絕不寫 `last_run_at`**
  ——那是心跳，機器人已經死了還更新它等於偽造它還活著。DB 以 `mode=rw` 開啟，
  檔案不存在就失敗、不建立（與 healthcheck 同一原則）。LINE 推播位置已留好，
  待 Channel 憑證到位（D020）。

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
- 部署：Podman 容器化為主線 —— 見 DECISIONS D007。容器**由 systemd --user 的 Quadlet 單元
  `systemd/shuyu-lending-bot.container` 啟動**，不由 CI job 直接 `podman run`（否則 job
  收尾會殺掉 conmon，日誌與重啟都形同虛設）—— 見 DECISIONS D017。重啟節流以
  `Restart=on-failure` + `StartLimitBurst` 表達、`RestartPreventExitStatus=2` 讓
  `EXIT_FATAL` 不重啟；`--log-driver=k8s-file` 讓日誌取得回來、`--health-cmd` 掛上
  心跳檢查 —— 見 DECISIONS D016。
- 失效處理只有一個權威：**systemd**。健康檢查不健康時用 `HealthOnFailure=kill`
  （不是 `restart`）——podman 只負責殺掉容器、產生一個非 0 離開碼，重啟一律由
  `Restart=on-failure` 接手，因此節流與告警自動涵蓋這條路徑，不會出現 podman 與
  systemd 兩套機制各自計數互相打架 —— 見 DECISIONS D020。
- 告警管道：機器人自己的連續失敗告警走 `FailureTracker`（D013，容器內）；
  「機器人整個不在了」則走 systemd 的 `OnFailure=` + `scripts/notify_failure.py`
  （D020，容器外）。兩者分工的界線是「還有沒有東西活著可以報告」。
- 可觀測：固定檔名日誌輪替、指數退避重試、`bot_state` 心跳與連續失敗告警 —— 見 DECISIONS D013。
