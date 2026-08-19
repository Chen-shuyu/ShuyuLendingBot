# ARCHITECTURE

## 整體架構

單帳戶、單幣種（USD）的 Bitfinex Funding 放貸機器人。以 `ccxt.bitfinex`（V1/V2 已合併，
見 D009）為交易所適配層，Bitfinex funding 相關操作一律呼叫 ccxt 的 raw/implicit API，
不使用（也不存在）統一方法（見 D010）。策略層以純函式計算掛單利率/金額/天期，
核心迴圈（`while True` + `time.sleep`）
每輪巡檢：取消未成交舊單 → 查詢可用餘額 → 抓 FRR → 產生掛單計畫 → 送出掛單 → 寫入 DB →
寫入日誌 → 休眠。**例行巡檢不推 LINE**，通知管道只送事件（連續失敗、恢復、致命錯誤、
systemd 放棄重啟）——免費方案每月 200 則，每輪推一則兩天就會用光（見 D024）。
程式以 Podman 容器化常駐部署（見 D007），容器由 systemd --user
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
        ├─ strategies/expected_value.py ─┤（純函式：以單位時間報酬期望值算利率/金額/天期）
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
│   ├── bitfinex_client.py      # BitfinexClient：連線、餘額、FRR、市場深度、近期成交、
│   │                            # 場上掛單、已借出部位、取消掛單、建立掛單
│   │                            # （皆呼叫 ccxt raw API，見 D009／D010／D030／D033）
│   └── rate_limiter.py         # RetrySettings + with_retry 指數退避（M3 新增）
├── strategies/                 # 策略層（純函式，易測試）
│   ├── base.py                 # Strategy 介面與 OfferPlan 資料結構（M4 新增）
│   ├── expected_value.py       # ExpectedValueStrategy：以單位時間報酬的期望值選價，
│   │                            # 等待時間每輪從 1 小時 K 線重估
│   │                            # （2026-08-17 起的預設策略，見 D035／D038）
│   ├── orderbook_depth.py      # OrderBookDepthStrategy：依訂單簿排隊位置定價，
│   │                            # 已被 D035 取代，仍是 expected_value 的父類別
│   │                            # （金額拆分、風控上限、成交價下限、利率量化共用）
│   └── frr_plus.py             # FrrPlusStrategy：舊的 FRR 加減碼，保留供對照
├── core/
│   └── bot_engine.py           # BotEngine：run_once / run_forever 主迴圈狀態機、
│                                # FailureTracker、離開碼常數（M4 由 main.py 移入）
├── db/
│   ├── models.py               # loan_offers / earnings_daily / funding_positions /
│   │                            # bot_state / offer_wait_forecasts 的 DDL
│   │                            # （funding_positions 為 D030、
│   │                            #   offer_wait_forecasts 為 D038 新增）
│   └── repository.py           # SQLite WAL 讀寫封裝（M3 新增）
├── notify/
│   └── line_messaging.py       # LineNotifier：LINE Messaging API push（見 D002、D024）
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
├── tests/                      # 三層測試 312 項（M4 新增，見 DECISIONS.md D015、D016）
│   ├── conftest.py             # 共用 fixture 與測試替身（FakeLogger／FakeNotifier／repository）
│   ├── unit/                   # 純邏輯：策略、重試、資料層、設定、日誌、交易所客戶端、告警腳本
│   ├── functional/             # run_once() 巡檢流程、FailureTracker 告警去重、離開碼與退出路徑
│   └── integration/            # dry-run 端到端、Bitfinex 公開端點格式守門（live marker）
├── config.yaml
├── main.py                     # 只做 bootstrap：組裝各層元件、把離開碼交給作業系統
└── .project-docs/              # 本文件所在
```

搬遷本身不改行為（見 D021），迴歸保護來自既有的 283 項測試。
結構已補齊：`notify/line_messaging.py` 於 2026-08-15 改寫完成並實測送達（見 D024），M4 完成。

## 主要模組

- `config/settings.py`：讀取 `config.yaml`，以環境變數與 `BFX_SECRETS_FILE` 覆蓋敏感值。已可用。
- `api/base.py`：`ExchangeClient` 抽象介面。重點不在方法簽章而在**例外契約**——實作必須
  把底層套件的例外轉成 `RetryableError` / `FatalError` 再往外拋，主迴圈才分得出「下一輪
  重試」與「直接停止」；漏一個 ccxt 例外出去就會被最外層當成未預期例外，離開碼與重啟
  決策全錯（見 D021）。
- `api/bitfinex_client.py`：封裝 `ccxt.bitfinex`，實作上述介面，提供
  `test_connection`、`get_available_balance`、`get_frr`、`get_funding_book`、
  `get_recent_trades`、`get_rate_candles`、`get_active_offers`、`get_active_positions`、
  `cancel_active_offers`、`create_loan_offer`。**三個市場端點回答的是不同問題**：
  `get_funding_book()` 是「別人開價多少、我排第幾位」，`get_recent_trades()` 是
  「借款人實際付了多少」，`get_rate_candles()`（D035 新增，讀
  `/v2/candles/trade:1h:fUSD:p2/hist`）是「過去每小時的需求掃到多高」。
  只看第一個會被一筆低價大單牽著走（D033）；只看前兩個會把一個時間切片誤當成常態，
  而這個市場在每小時之內的振幅動輒 5 個百分點（D035）。
  K 線一次可取 5000 根（涵蓋 7 個月），而 `/v2/trades` 一次只涵蓋約 4 小時
  ——**樣本窗太短正是 D035 第一個錯誤結論的成因**。
  `get_active_offers()` 的回傳帶 `created_at_ms`（MTS_CREATE），是閒置時間量測的基準（D038）。
  兩者都走公開端點，dry-run 下也拿得到，所以離線也驗得了定價。四者皆已修正為呼叫 ccxt 的 raw/implicit API（`public_get_ticker_symbol`／
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
- `strategies/expected_value.py`：`ExpectedValueStrategy`，**2026-08-17 起的預設策略**
  （見 D035、D038）。**繼承 `OrderBookDepthStrategy`，只換掉「怎麼決定 base_rate」這一步**
  ——金額拆分、風控上限、成交價下限、利率量化、排隊位置描述全部共用，
  兩個策略的差異因此是一個可以單獨檢視的方法，不是兩份平行演化的程式碼。

  定價的主張只有一句：**掛在哪個價位，由「利率 × 借出期間 ÷ (等待 + 借出期間)」
  最大的那一個決定**（D034 已驗證的單位時間報酬），而等待時間每輪從 1 小時 K 線重估：

  1. **候選價位**取自窗內出現過的 `high`——沒有掃到過的價位不該成為候選，
     這同時是天然的上限，不必另設「最高不准超過多少」的旋鈕。
  2. **等待估計**（`estimate_wait()`）問的是**「我在任意時刻進場要等多久」**，
     不是「命中間隔平均多長」（D038）。從窗內每個小時各出發一次算等待，
     長空檔會依它實際佔掉的時間長度被加權。回傳平均／中位數／p75／命中數／右設限數。
     **舊版逐根走訪算出間隔後取平均，把剛保留下來的陣發性又抹掉了**——
     `[6,0,0]` 與 `[2,2,2]` 的平均都是 2。
  3. **右設限**（等到窗尾還沒等到）**計入而非丟棄**：丟掉的正是最長的那些等待。
     算出來的是下界，所以 `censored_ratio` 一併輸出，當作這個下界有多不可信的刻度。
  4. **`ev_min_hits`** 擋尾端：窗內最高的那一兩根 K 永遠「命中 1 次」，
     不擋的話期望值會一路爬到一個只發生過一次、等不到的價位。

  `describe_decision()` 把整段推導濃縮成一行給迴圈層寫日誌，
  `chosen_forecast()` 交出掛單當下的預估供落 DB（策略層仍然不碰 IO）。
  D033 與 D030 的兩道防線（成交價下限、`minimum_rate` 絕對地板）**原封不動沿用**。
- `strategies/orderbook_depth.py`：`OrderBookDepthStrategy`，2026-08-16 至 08-17 的預設策略，
  **已由 `ExpectedValueStrategy` 取代（D035），但仍是它的父類別**——
  上面列的共用邏輯都住在這裡，所以它不是死碼。
  被取代的原因是**模型的自變數選錯了**：排隊位置模型假設需求穩定地從簿子前端吃過來，
  而這個市場的成交是陣發掃單——**站在最前面不會更快成交，只保證用最低價成交**。
  （見 D030、D033）。輸入餘額、市場深度與近期成交，輸出 `OfferPlan` 清單。
  定價是一句話加兩道下限：
  1. **排隊規則**：在「排在我們前面的錢不超過 `target_queue_usd`」的前提下挑利率最高的一檔。
  2. **成交價下限**（D033）：不得低於「同天期成交的金額加權中位數 × `market_floor_pct`」。
     訂單簿講「有人開價多少」，講不出「借款人實際付多少」——2026-08-16 夜間
     一道 182 萬 USD 的低價牆讓排隊規則把報價砍到年化 5.47% 並真的成交。
     **下限只往上拉不往下壓**：排隊規則算出的價位更高時不動它。
  3. **絕對地板** `minimum_rate`：語意是**「低於它就不掛」而不是「拉高到它」**——
     後者會把單子推到簿子外，變成永遠不會成交的死單。
  送出前一律用 `_quantize()` **無條件捨去**（不可 `round()`）：對放貸方而言利率越低
  排得越前面，四捨五入有一半機率把價位往上推、跨過某一檔就從「排它前面」
  變成「同價而排它後面」（D033）。
- `strategies/frr_plus.py`：`FrrPlusStrategy`，舊的 FRR 加減碼策略，保留供一行切換對照。
  **不是備援**：它已知會把單子掛到市場之上（FRR 高過成交天花板），
  拿不到市場深度時一律不掛，而不是退回這條路。
- `core/bot_engine.py`：`BotEngine.run_once()` 單輪巡檢，順序為
  **對帳已借出部位（成交偵測）** → 查場上現有掛單 → 查餘額 → 抓 FRR →
  取得市場深度與近期成交 → 產生掛單計畫 → **與場上比對，實質相同就什麼都不做** →
  **往下調價的話再檢查划不划算** → 取消舊掛單 → 等待餘額釋放 →
  **確認取消真的生效** → 以真實餘額重算 → 逐筆掛單並落帳 → 寫入 `bot_state` → 通知。
  **對帳一定要排在取消之前**（取消會改變場上狀態）。動場上那張單有**兩道**關卡：
  「條件沒變就不重掛」保護排隊位置——同利率下先掛先成交（D030）；
  「往下調價要先證明划得來」則比較 `利息 ÷ (等待 + 借出期間)`，
  **只管往下這個方向**，因為那個方向放棄的利息是確定的、換來的速度是估的（D034）。
  取消之後**再查一次場上掛單**而不是用餘額回推：兩者會分岔，而單子還在時再掛一筆
  就是雙倍曝險（D034）。主迴圈分類處理 `RetryableError` / `FatalError` / `SkipCycleError`，
  並以 `FailureTracker` 累計連續失敗、跨過門檻時告警一次、恢復時再通知一次（D013）。
  `run_forever()` 包住啟動檢查、主迴圈與三條退出路徑，回傳離開碼（`EXIT_OK` / 
  `EXIT_UNEXPECTED` / `EXIT_FATAL` 也定義在這裡，見 D016、D017、D019）。
- `db/repository.py`：SQLite WAL 模式（搭配 `synchronous=NORMAL`），記錄掛單流水、
  每日收益彙總、`bot_state`。掛單成功走 `record_offer()`、失敗走 `record_offer_failure()`——
  掛單 API 無法 rollback，同一輪前幾筆成功時錢已經出去了，只有逐筆落帳才對得出真實狀態。
  檔案位置由 `resolve_db_path()` 決定：`BFX_DB_PATH` 優先，相對路徑一律相對於專案根目錄
  ——**必須與 `scripts/healthcheck.py` 的同名函式算出相同結果**，兩邊分家的症狀是健康檢查
  永遠回報「尚未寫入任何心跳」而機器人其實是好的（D019）。
  `offer_wait_forecasts` 存的是**掛單當下對「要等多久」的預估**，一張單一列（D038）：
  實際等待事後算得出來（掛單時間在 `loan_offers`、成交時間在 `funding_positions`），
  **「當初以為要等多久」才是不存就永遠消失的那一半**——策略每輪重算，
  記憶體裡永遠只有「現在這一輪怎麼想」。少了它就只能拿今天的模型解釋昨天的決定（D036）。
  尚待：`earnings_daily` 只有表結構與 `upsert_daily_earning()` 介面，還沒有資料來源（D013）。
- `notify/line_messaging.py`：LINE Messaging API push（`POST /v2/bot/message/push`）。
  `send()` 永遠不拋例外——它在致命錯誤的退出路徑上被呼叫，拋例外會蓋掉原始錯誤與離開碼。
  **只送事件、不送例行**：免費方案每月 200 則，每輪巡檢推一則會在兩天內用光（見 D024）。
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
  檔案不存在就失敗、不建立（與 healthcheck 同一原則）。LINE 推播已於 2026-08-15 接上
  （自己讀 `secrets.env`，因為告警單元不會帶憑證進來；**INFO 等級不推**，那是部署重啟
  造成的觸發，見 D023、D024）。

## 刻意排除的部分

為降低複雜度並符合單帳戶單幣種現況，不採用 MikaLendingBot 的：Plugin 生態
（`PluginsManager`/`Plugin` hooks）、多 Worker/`Manager` 多執行緒架構、Web 前端頁面
（先以 CLI/日誌觀測，未來再加）。

## 關鍵技術選型

- 交易所串接：`ccxt.bitfinex`（V1/V2 已合併），取代舊專案的獨立 V1 API —— 見 DECISIONS D001、D009。
- API 呼叫方式：Bitfinex funding 相關操作一律呼叫 ccxt 的 raw/implicit API，不使用（也不存在）
  統一方法 —— 見 DECISIONS D010。
- 併發模型：單執行緒 + `time.sleep` 主迴圈，不引入 `asyncio` —— 見 DECISIONS D003。
- 通知：LINE Messaging API push，取代已停用的 LINE Notify —— 見 DECISIONS D002、D024。
  兩份**獨立實作**：容器內的 `notify/line_messaging.py`（用 `requests`）與主機端的
  `scripts/notify_failure.py`（只用標準函式庫）。刻意不共用程式碼——後者執行的時機
  正是機器人壞掉的時候，不能依賴專案模組或第三方套件。兩邊要一起改。
- 持久化：SQLite（WAL 模式），非外部 DB —— 見 DECISIONS D006。SQLite 檔須以 volume 掛出
  容器（`/app/data`），否則重新部署即歸零。
- 部署：Podman 容器化為主線 —— 見 DECISIONS D007。容器**由 systemd --user 的 Quadlet 單元
  `systemd/shuyu-lending-bot.container` 啟動**，不由 CI job 直接 `podman run`（否則 job
  收尾會殺掉 conmon，日誌與重啟都形同虛設）—— 見 DECISIONS D017。重啟節流以
  `Restart=on-failure` + `StartLimitBurst` 表達、`RestartPreventExitStatus=2` 讓
  `EXIT_FATAL` 不重啟；`--log-driver=k8s-file` 讓日誌取得回來、`--health-cmd` 掛上
  心跳檢查 —— 見 DECISIONS D016。
- 金鑰：唯一真實來源是 `~/.config/bfx-lending-bot/secrets.env`（目錄 700／檔案 600），
  以**唯讀掛載單一檔案**的方式進容器，並用 `BFX_SECRETS_FILE` 指路 —— 見 DECISIONS D022。
  兩條約束：**不掛整個目錄**（容器只該看到金鑰檔，不該看到同目錄的其他東西）、
  **不用 `Environment=` 傳金鑰**（會同時洩漏到版控中的單元檔、`podman inspect`、
  `systemctl show` 與 `/proc/<pid>/environ`）。放家目錄而非 `/workspace`，
  是為了讓版控與 CI 在結構上就碰不到它。`docker-compose.yml` 必須與 Quadlet 單元一致。
- 失效處理只有一個權威：**systemd**。健康檢查不健康時用 `HealthOnFailure=kill`
  （不是 `restart`）——podman 只負責殺掉容器、產生一個非 0 離開碼，重啟一律由
  `Restart=on-failure` 接手，因此節流與告警自動涵蓋這條路徑，不會出現 podman 與
  systemd 兩套機制各自計數互相打架 —— 見 DECISIONS D020。
- 告警管道：機器人自己的連續失敗告警走 `FailureTracker`（D013，容器內）；
  「機器人整個不在了」則走 systemd 的 `OnFailure=` + `scripts/notify_failure.py`
  （D020，容器外）。兩者分工的界線是「還有沒有東西活著可以報告」。
- 可觀測：固定檔名日誌輪替、指數退避重試、`bot_state` 心跳與連續失敗告警 —— 見 DECISIONS D013。
