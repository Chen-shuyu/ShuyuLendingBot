# CHANGELOG

## [Unreleased]

### Fixed（2026-08-19，分支 `fix/honest-wait-estimate-and-idle-tracking`）
- **等待估計問錯了問題**（D038）：`estimate_wait_hours()` 逐根走訪算出命中間隔後
  用 `fmean()` 取平均，而 `[6,0,0]` 與 `[2,2,2]` 的平均都是 2——**它的 docstring
  宣稱處理了陣發性，那一行卻把陣發性抹掉了**。改為 `estimate_wait()`：
  從窗內每一個小時各出發一次，算「我這個時候進場要等多久」
  - 同一份 168 小時真實 K 線：9.96% 這個價位舊算法說等 3.2h，實際 10.8h（低估 3.4 倍）；
    最佳解由 9.96% 改為 **9.78%**
  - **修正不是單向的**：陣發時算出更長（測試中 3.75 倍），
    命中規則時反而算出更短（47.7h → 29.9h）。修的是「算對」，不是「調高」
  - 右設限（等到窗尾還沒等到）改為**計入而非丟棄**——丟掉的正是最長的那些等待
- `_parse_offers()` 補上 `created_at_ms`（funding offers 索引 2 = MTS_CREATE），
  **已對正式帳號實打驗證**：`'1787087004000'` → `2026-08-19 05:03:24 +0800`

### Added（2026-08-19，同分支）
- **閒置時間量測**（D037 順位 1）：每輪印出場上掛單已閒置多久、機會成本（USD），
  並與掛單當初的預估對照（在中位數內／已超過中位數／已超出 p75）
  - 量測點放在所有「要不要動這張單」的判斷**之前**：閒置最久的輪次走的正是
    「維持不動」那條提早 return 的路徑
- 新表 `offer_wait_forecasts`：掛單當下對「要等多久」的預估，一張單一列。
  **實際等待事後算得出來，「當初以為要等多久」才是不存就永遠消失的那一半**
- `describe_decision()` 的日誌行補上中位數、p75 與右設限比例——
  只印平均會讓「平均 6 小時」看起來像「大概 6 小時會成交」
- 測試 493 → 509 項；測試替身校正（`make_offer_array()`／`live_offer()` 帶
  MTS_CREATE 字串，`FakeClient` 補 `get_rate_candles()`）

### Observed（2026-08-19）
- **05:03:19 借款人提前還款**（原定 08-20 22:11 到期，提前 41 小時），
  部位 `464047005` 實際只借 6 小時 52 分，年化 9.96%
- 05:03:24 以年化 9.78% 重新掛單，**至 23:09 已閒置 18.1 小時未成交**
- 掃到 9.78% 的兩根 K（03:00、04:00）都在掛單**之前**；
  當下 250 檔可見最高只有 9.04%，掛單越出可見範圍（A3 現場重現、B9 順帶證實）


### Deployed（2026-08-18 22:39，main `205a757`）
- PR #32（盤查與路線圖重排、D036）與 A1（定價決策進日誌）**合併進 main 並完成部署**。
  CI 四個 job 全綠，容器 22:39:02 重啟並確認採用 `expected_value` 策略
- **合併時機是挑過的**：22:11 成交後資金已借出、訂單簿上沒有我們的單，
  重啟不會取消任何掛單、不損失排隊位置——**部署成本為零的視窗**
- 機器上沒有 `gh` CLI 也沒有 token，改以本機合併後推 main；
  GitHub 偵測到 head commit 已可從 main 到達，**PR #32 自動標示為 Merged**

### Validated（2026-08-18）
- **期望值定價（D035）第一次拿到真實市場的正面證據**：344.36 USD 以年化 9.96%
  掛出，期間市場常態價跌到 5.47%，**22:11:22 被一波掃單成交**。
  等待 3.6 小時，**含閒置的實質年化 9.27%**，對照立刻成交的 5.47%
- ⚠️ **但 A2 那個退化的守門檻整天沒被觸發**（擋下重掛的是 2% 利率容差），
  這筆成交**不構成 A2 的背書**，見 D037

### Added（2026-08-17 深夜，分支 `fix/log-expected-value-reasoning`）
- **定價決策寫進日誌**（TASKS.md A1）：`ExpectedValueStrategy.describe_decision()`
  ＋ `BotEngine._log_pricing_rationale()`。輸出含候選價位數、選中的利率、平均等待、
  窗內命中次數、實質年化，**並對照「最快成交的候選」**——後者正是舊策略會選的價位，
  兩者並排才看得出取捨換到了什麼

### Fixed（2026-08-17 深夜）
- **「本輪不掛單」的理由不再寫死成「可放貸金額不足」**。策略有六個出口會回傳空計畫，
  **其中五個跟金額無關**；最糟的是「價格低於年化 8% 地板」——帳上有 344 USD 卻寫
  「可放貸金額不足（目前 344.3 USD）」，自相矛盾又把人指向錯的方向，
  **而那正是市場走弱時最可能出現的情況**。這是 D026「靜默失效」的第三次現身
- `Strategy` 基底新增 `last_skip_reason` 與 `_skip()`，**三個策略的每個出口都要交代理由**。
  只修 `expected_value` 的話，之後切回 `orderbook_depth` 做對照就會踩回同一個坑。
  策略答不出來時退回中性的「未提供原因」——講「不知道」遠比講一個具體但錯誤的原因好

### Changed（2026-08-17，分支 `fix/market-floor-goes-stale`）
- **定價基準由「訂單簿排隊位置」改為「單位時間報酬的期望值」**（TASKS.md P1-5、D035）。
  `strategy.mode` 預設改為 `expected_value`。掃過候選價位，挑
  `r × 借出期間 ÷ (等待 + 借出期間)` 最大者（沿用 D034 的算式），
  等待時間每輪從 1 小時 K 重新估，不再是人手填進設定檔的常數
- **排隊定價之所以要換掉**：它假設需求會穩定地從簿子前端吃過來，實測不成立——
  這個市場的成交是**陣發掃單**（最近 30 天 **90.0% 的小時曾觸及年化 8% 以上**，
  單根 1 小時 K 振幅動輒 5 個百分點），而簿子底端長期被大額低價單佔住。
  **站在隊伍最前面不會更快成交，只保證用最低價成交**——2026-08-16 那筆年化 5.47%
  的成交，發生在一個曾漲到 11.77% 的小時裡
- `strategies/base.py` 新增 `requires_candles` 旗標與 `build_offer_plan(candles=...)` 參數

### Added（2026-08-17）
- `api.get_rate_candles()`：利率 K 線查詢（`/v2/candles/trade:{tf}:f{ccy}:p{period}/hist`）。
  **不用 `/v2/trades` 代替**——後者一次最多 10000 筆、活躍時段只涵蓋約 4 小時，
  而**樣本窗太短正是 D035 第一個錯誤結論的成因**
- `strategies/expected_value.py`：新策略，繼承 `OrderBookDepthStrategy`，
  只換掉「怎麼決定 base_rate」那一步
- 設定 `strategy.ev_window_hours`（168）／`ev_min_hits`（5）／`ev_min_candles`（48）／
  `candle_limit`（240）／`candle_timeframe`（1h）／`candle_hours`（1.0）

### Unchanged（2026-08-17，刻意保留）
- **`minimum_rate` 維持年化 8.00%**。一度打算調低它（因為當下 30 分鐘內「年化 8% 以上
  成交佔 0.0%」），查完 K 線後推翻——那個判斷用一個時間切片代表市場，
  與 D030 記過的爆發桶陷阱同類。年化 8% 的平均等待只有 0.6 小時，保留成本接近零
- `market_floor_pct`（0.85）與 D033 的成交價下限語意完全不動

### Known gaps（2026-08-17）
- **天期仍寫死 2 天**：D032／P1-2 指出天期與利率是同一個期望值問題的兩個維度，
  本次只做了利率那一維。比較天期要一輪打三次 K 線端點（`p2`／`p7`／`p30`）
  並各自估等待，列為 P1-5 的剩餘部分
- `get_funding_book()` 的 `len=250` 註解已過期：可見的 250 檔最高只到年化 8.33%，
  簿子在 8% 以上的部分看不到。改用期望值定價後訂單簿不再是主要資料源，
  影響隨之改變，但註解要修

### Changed（2026-08-16 夜間第三段，分支 `fix/requeue-queue-position-guard`）
- **往下調價的重掛要先證明划得來**（TASKS.md P1-4、D034）。判準是
  `利息 ÷ (等待 + 借出期間)`：新價位比場上那張低時，排隊位置的改善要補得回少收的
  利息才重掛。**往上調價不受這條限制**——那個方向多賺的利息是確定的，
  而往下調時「換來的速度」是估的，估的那半邊目前只有一個校準樣本
- **取消掛單後改為確認場上狀態，不再用餘額回推**（D031 的第二個缺口）。
  19:31 證明兩者會分岔：餘額沒回來不代表取消沒生效，也可能是那張單根本沒被取消。
  仍有單就整輪不重掛——**再掛一筆就是雙倍曝險**
- 日誌分出「候選價位」與「場上掛單」兩個排隊位置。原本只有前者，
  而 19:31 的誤讀正是把前者讀成後者
- `describe_queue()` 新增 `period` 參數：問「場上那張單排在哪」時天期要取自那張單，
  不能取自設定檔（分桶實驗一開始，同時掛 2 天與 30 天就是常態）

### Added（2026-08-16 夜間第三段）
- 設定 `engine.queue_clear_usd_per_hour`（預設 540000）：排隊的錢被吃掉的速率。
  取自唯一一筆真實成交（前方 73 萬 USD、1.35 小時後成交）。
  **遠低於訂單簿成交流量**（當日 2 天期約 415 萬 USD/小時）——成交量不等於隊列消化速度

### Rejected（2026-08-16 夜間第三段，實測否決）
- **D031 原本指定的「排隊位置守門檻」沒有實作**，理由見 D034：排隊金額對利率單調，
  「前方金額少」幾乎等同「這張單掛得比市場便宜」，固定門檻鎖住的正好是最該往上調價
  的那些。實測 2% 容差擋不住的 64 個往上調價位，重掛期望值**全部為正**
- 中間版本「利率更差、隊伍又更長就不動」同樣被否決：因為單調性，那種情況除了完全
  平手之外不可能發生，判準是空的

### Verified（2026-08-16 夜間，實單驗證，無程式變更）
- 🎉 **第一筆成交**：2026-08-16 19:31:31，344.30 USD、日利率 0.000250（年化 9.12%）、
  2 天期。從新策略首次掛單（18:10:24）到成交歷時 1.35 小時。
  **上方「定價基準改為訂單簿排隊位置」的變更由此得到實單驗證**
- **P2-1 的已知缺口部分關閉**：`credits` 端點的欄位索引已用真實回應核對，
  解析完全正確（金額／利率／天期／時間全對）。**`loans` 端點仍未驗證**
- **「不再每輪無條件取消重掛」實際生效**：18:20、19:20 兩輪日誌顯示
  「掛單條件與場上 1 筆一致（利率容差 2.0%），維持不動以保住排隊位置」
- 🔴 **同時發現缺陷（D031，待修）**：19:31:02 機器人送出取消，
  25 秒後那張單才成交——**取消沒趕上，純屬運氣**。
  觸發原因是排隊位置掉到 0 而策略想掛更高的利率；
  排隊位置只寫進日誌、沒有餵回重掛判斷。詳見 TASKS.md P1-4

### Changed（2026-08-16，分支 `feature/orderbook-pricing-and-fill-detection`）
- **定價基準改為訂單簿排隊位置**（TASKS.md P1-1、D030）。新增
  `strategies/orderbook_depth.py` 並設為預設（`strategy.mode`）。
  **根因**：舊策略掛 0.000272，而當時簿子頂端就是 0.000272——單子一直落在
  整個供給側的最後面，78 輪掛空。新演算法只有一句：在「前方排隊金額 ≤
  `target_queue_usd`」的前提下挑利率最高的一檔。實測會掛 0.000250（年化 9.12%）。
  **刻意不用 trades 百分位**：那會被爆發桶汙染，等於 FRR 落後問題換個來源重演
- **`minimum_rate` 語意改變**：從「算出來太低就拉高到這裡」改成
  「低於這裡就整輪不掛」。舊寫法會把價格拉到簿子外，掛一張永遠不會成交的單
- **不再每輪無條件取消重掛**：同利率下先掛先成交，每 600 秒重掛等於一天把自己
  送回隊伍末端 144 次。改為先查場上現況再比對，實質相同就什麼都不做
  （容差 `engine.rate_tolerance_pct`，預設 2%）
- **`spread_count` 由 3 改為 1**：344 USD 最多拆 2 筆，而第 2 筆會被乘到 0.000288、
  簿子頂端才 0.000270——一半的錢會變死單。**觸發條件正是「把資金全部投入」**

### Added（2026-08-16，分支 `feature/orderbook-pricing-and-fill-detection`）
- **成交偵測**（TASKS.md P2-1、D030）：機器人終於知道自己借出去了。
  新增 `funding_positions` 表、`Repository.sync_positions()` 對帳，
  以及「資金已借出」「借出的資金已收回」兩則 LINE 通知。
  查 credits 與 loans **兩個端點**——只查一個會漏掉一半。
  **已知缺口**：那兩支的欄位索引取自官方文件、尚未經真實回應核對（至今零成交），
  解析已寫成防禦式，第一筆成交後要回來核對
- `api/base.py` 新增 `get_funding_book()`／`get_active_offers()`／`get_active_positions()`
- `config.yaml` 新增 `strategy.mode`、`strategy.offer_period`、
  `strategy.target_queue_usd`、`engine.rate_tolerance_pct`
- 測試 347 → 437 項

### Added（2026-08-16，分支 `feature/notify-format-and-trade-events`）
- **交易面通知**（TASKS.md P2-4、D029）：掛單上線／掛單消失／掛單被拒三種事件會推 LINE。
  推的是**狀態轉換**不是每輪結果——原規劃的「內容有變才推」擋不住 FRR 漂移，
  等於每輪都推。現在一天通常 0～2 則。**「掛單已不在場上」是目前唯一能察覺
  「錢可能借出去了」的訊號**，但刻意不寫死成「成交」（也可能是資金被搬走）
- **統一訊息格式**（P2-3、D029）：新增 `notify/messages.py`，三段式——
  結論行／`欄位：值`／「需人工介入」或「無需處理」二選一。
  分類分成【系統】【交易】【收益】【風控】，圖示為正常看分類、異常看等級。
  日誌維持單行（`grep ERROR` 才抓得到），只有推播用三段式
- `config.yaml` 新增 `line.push_trade_events`（預設 true）：額度安全閥，
  關掉的是通知不是紀錄
- 測試 308 → 347 項

### Changed（2026-08-16，分支 `docs/tasks-notify-and-ci-deploy-skip`）
- **只動 `.project-docs/` 的推送不再觸發部署**（TASKS.md P1-3、D017 的 2026-08-16 補充）。
  先前每次文件同步都會 `systemctl --user restart`，等於**把交易所上正在排隊的掛單
  取消後重掛一筆新的**——空窗加上時間優先權歸零，白白拉長成交的等待。
  新增 `changes` job 比對變更路徑，`deploy` 整個 job 被條件擋下；
  `test`／`integration` 照跑。判斷不出來的情況一律照常部署（fail-open）

### 2026-08-15：M4 完成並切換為小額真金運作
- LINE Messaging API push 接上，取代 2025-03 停用的 LINE Notify（D024）。
  環境變數改為 `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_TO_USER_ID`。
  **例行巡檢不再推 LINE**——免費方案每月 200 則，每輪推一則兩天就用光
- 金鑰檔唯一真實來源改為 `~/.config/bfx-lending-bot/secrets.env`，
  Quadlet 改為唯讀掛載**單一檔案**而非整個部署目錄（D022）
- systemd 失效告警改三分法，修掉「每次部署都送假 ERROR」（D023）
- `engine.dry_run` 切為 `false`，以 160 USD 起始，曝險由融資錢包餘額鎖住
- **修正**：掛單金額四捨五入後超出可用餘額，被交易所拒單（D025）。
  `_split_amount()` 改用整數分運算
- **修正**：取消掛單時 id 未轉整數導致 `id: invalid`，且失敗被吞掉不觸發任何告警（D026）。
  改為「查到掛單卻一筆都取消不掉」時拋 `RetryableError`
- 測試 283 → 315 項

### Added
- `.project-docs/` 專案文件結構（PLAN/PROGRESS/DECISIONS/TASKS/CHANGELOG/ARCHITECTURE），
  取代原本散落根目錄的 `PRD.md`／`SHUYU_PROJECT_PLAN.md`（已歸檔至 `archive/`）
- dry-run 雛型：設定載入（`config/settings.py`）、策略骨架（`modules/lending_strategy.py`）、
  交易所封裝骨架（`modules/exchange_client.py`）、LINE 通知骨架（`modules/line_notifier.py`）
- CI workflow 骨架（`.github/workflows/python-app.yml`）：test / integration / deploy 三個 job
- spread 階梯利率：以 `frr + premium` 為最低階、每階乘 `(1 + spread_step_pct)` 遞增，金額均分、
  餘數併入最容易成交的第一筆，筆數依 `min_loan_size_usd` 自動降階，每筆各自判斷天期
- `maxtolend` / `maxpercenttolend` 放貸上限（單輪量控版）：觸及上限時縮量掛，預設 0 = 不限制
- `engine.cancel_settle_seconds`：取消舊掛單後等待餘額釋放的秒數（Bitfinex 取消為非同步）
- `api/rate_limiter.py`：`with_retry` 指數退避重試（預設最多 5 次、2 秒起跳加倍、上限 60 秒），
  套用於 `get_available_balance` / `get_frr` / `cancel_active_offers`
- `db/`：SQLite WAL 資料層，三張表 `loan_offers`（掛單流水，含 dry-run 與失敗）、
  `earnings_daily`（每日收益，本輪只建表與介面）、`bot_state`（單列狀態，兼作心跳）
- heartbeat：每輪巡檢（含正常略過）都更新 `bot_state.last_run_at`
- 連續失敗告警：`FailureTracker` 在連續失敗達 `engine.alert_after_failures` 輪時告警一次，
  恢復時再通知一次，中間不重複發送
- `config.yaml` 新增 `database.path`、`retry.*`、`logging.max_bytes` / `backup_count`、
  `engine.alert_after_failures`
- `podman run` 與 `docker-compose.yml` 掛上 `/app/data` volume，讓 SQLite 紀錄跨容器保存
- `tests/` 三層測試套件共 227 項：`unit`（策略、重試、資料層、設定、日誌、交易所客戶端）、
  `functional`（`run_once()` 巡檢流程、`FailureTracker` 告警去重）、
  `integration`（dry-run 端到端、Bitfinex 公開端點格式守門，連不上時 skip）
- `pytest.ini`（`pythonpath = .` 與 `live` marker）與 `requirements-dev.txt`
- `scripts/healthcheck.py`：容器健康檢查，唯讀讀取 `bot_state.last_run_at` 判斷心跳是否過期
  （門檻 = 巡檢間隔 × 3 + 60 秒，可用 `engine.health_max_silence_seconds` 覆寫），
  並在 `podman run` 與 `docker-compose.yml` 兩邊都掛上對應的 healthcheck 設定
- `main.py` 的離開碼常數 `EXIT_OK` / `EXIT_UNEXPECTED` / `EXIT_FATAL`，
  三條退出路徑退出前都會把原因寫進 `bot_state.last_action`
- 最外層攔截未預期例外：改為寫進日誌檔與 DB 後才結束，不再只噴 traceback 到取不到的 stderr
- 測試增加到 236 項：`tests/unit/test_healthcheck.py`、`tests/functional/test_main_exit_codes.py`
- `systemd/shuyu-lending-bot.container`：正式部署用的 Podman Quadlet 單元（納入版控，
  CI 每次部署複製到 `~/.config/containers/systemd/`），容器的常駐、開機自動啟動、
  重啟節流與離開碼判斷都在這一個檔案裡表達

### Fixed
- CI 部署階段自 M3 起持續以 exit code 125 失敗的問題：podman 的 bind mount 不會自動建立
  主機端目錄（docker 會），而主機上從未建立 `.../ShuyuLendingBot/data`。workflow 在
  `podman run` 之前補一步 `mkdir -p`。修正後機器人已恢復常駐運行
- `upsert_daily_earning()` 傳 `principal_avg=None`（含不傳、走預設值）必定
  `IntegrityError` 的問題：`earnings_daily.principal_avg` 原宣告為 `NOT NULL`，
  但 ON CONFLICT 用 `COALESCE` 表達的原意是「傳 None 保留舊值」，NOT NULL 會在衝突解析
  之前先擋下，導致首次插入與後續累加兩條路徑都無法使用。改為可為 NULL
- `get_frr()` 誤用 `fetch_funding_rate`（永續合約資金費率）的問題，改抓真正的放貸 FRR
- `main.py` 補上 `while True` 常駐主迴圈，不再僅單次執行
- `ccxt.bitfinex2` 於目前 ccxt 版本已移除的問題，改用合併後的 `ccxt.bitfinex`
- `cancel_active_offers()` 原本查錯訂單類型、從未真的取消掛單的問題
- `create_loan_offer()` 檢查不存在的統一方法、實盤模式下必定失敗的問題
- `cancel_active_offers()` 從未被主迴圈呼叫的問題：`run_once()` 改為每輪先取消舊掛單再重掛，
  避免利率落後市場的舊掛單卡住資金空轉
- 交易所 API 完全沒有重試的問題：原本只把 ccxt 例外轉成 `RetryableError` 就往外拋，
  一次網路抖動就整輪跳過
- `utils/logger.py` 用 `FileHandler` 導致常駐後單檔無限增大的問題
- `.gitignore` 未排除 SQLite 檔的問題（`data/`、`*.sqlite3` 及 WAL 附屬檔）
- `FatalError` 直接退出與容器 `restart: unless-stopped` 打架、金鑰失效時會無限重啟的
  設定衝突：重啟策略改為 `on-failure` 系列並帶次數上限
- deploy job 的「取得最近容器日誌」空跑的問題：改讀掛載出來的 `logs/bfx_lending_bot.log`
- **容器崩潰後不會自行復原、`podman logs` 永遠是空的**（自 M3 起就存在）：根因是 CI 的
  deploy job 用 `podman run` 起容器，job 收尾時把容器的 conmon 一併殺掉——沒有 conmon
  就沒有人寫容器日誌、也沒有人在容器退出時執行重啟策略。改由 systemd --user 的 Quadlet
  單元管理容器生命週期，conmon 落在 `user@.service` 的 cgroup 底下與 job 脫鉤
  （見 DECISIONS.md D017）。修正後 `podman logs` 自 M3 以來第一次取得到內容
- `Linger=no` 導致所有登入 session 結束後 `systemd --user` 連同其下容器一起消失的問題：
  已執行 `loginctl enable-linger shuyu`

> **2026-08-02 更正**：上面「容器崩潰後不會自行復原」與「`podman logs` 取不到內容」
> 兩條，PR #10 曾宣稱修好、驗收後發現並沒有（參數正確但 conmon 不在，等於沒人執行），
> 一度移回 Known Issues。本次改由 systemd 接管容器生命週期後才真正成立，
> 並已用對照實驗與正式容器實測驗證，詳見 DECISIONS.md D017。

### Changed
- 移除 `strategy.split_threshold_usd`：原「餘額超過 300 才對半拆單」的語意已被 spread 的
  自動降階規則（餘額不足 `筆數 × min_loan_size_usd` 就降階）等價涵蓋
- log 檔名不再附加啟動時間戳（`utils/logger.py` 與 `start.sh` 各一處），改為固定檔名 +
  大小輪替；否則每次重啟另起一串新檔，`backup_count` 等於沒有上限
- CI 的測試步驟移除 `|| true`：測試失敗現在會擋下合併。原本的寫法讓 CI 永遠綠燈，
  等於寫了測試也攔不住壞掉的程式碼
- CI 內嵌的 heredoc smoke test 收斂進 `tests/integration/test_dry_run_cycle.py`，
  workflow 不再需要維護兩份驗證邏輯；測試依賴改由 `requirements-dev.txt` 統一安裝
- 容器重啟策略統一為 `on-failure`：`docker-compose.yml` 由 `unless-stopped` 改為
  `on-failure`。取次數上限是因為能自行恢復的問題三次內大多會過，過不了的重開再多次
  也沒用（見 DECISIONS.md D016）。正式部署那側原本用 `--restart=on-failure:3`，
  已於本次改由 systemd 表達（見下一條）
- **正式部署的容器改由 systemd --user 的 Quadlet 單元啟動**（DECISIONS.md D017）：
  - 新增版控的單元檔 `systemd/shuyu-lending-bot.container`，CI 每次部署複製到
    `~/.config/containers/systemd/` 並 `daemon-reload`
  - deploy job 不再 `podman run`，改為 `podman build` + `systemctl --user restart`；
    移除 podman 端的 `--restart=on-failure:3`（與 systemd 的重啟策略會打架）
  - 重啟節流改用 `Restart=on-failure` + `StartLimitIntervalSec=1800` /
    `StartLimitBurst=4`（30 分鐘內最多 4 次啟動），語意比 podman 的 `on-failure:N` 明確
  - 新增 `RestartPreventExitStatus=2`：systemd 看得到離開碼，`EXIT_FATAL` 直接不重啟。
    podman 的 restart policy 做不到這件事，這是換過來額外拿到的好處
  - 掛載目錄的 `mkdir -p` 從 CI 移進單元的 `ExecStartPre`，開機自動啟動時也才會成立
- CI 的「取得最近容器日誌」改讀掛載出來的 `logs/bfx_lending_bot.log`，
  `podman logs` 降為備援——容器被收掉之後檔案還在，而那正是最需要日誌的時候
- CI deploy job 新增「驗證容器生命週期真的由 systemd 接管」步驟，斷言服務為 active、
  conmon 行程存在、`podman logs` 取得到內容，三者任一不成立就紅燈。加這一步是因為
  先前「重啟與日誌沒生效」拖了兩個 milestone 才發現——部署完只看 `podman ps` 顯示
  running 是不夠的

### Known Issues
- `line_notifier.py` 呼叫已停用的 LINE Notify 端點，通知永遠失敗（待使用者申請 LINE
  Developers 憑證後改寫為 Messaging API，見 TASKS.md）。**連帶影響**：M3 的連續失敗告警
  目前實際上只會留在日誌裡，換成 Messaging API 後即自動生效
- `maxtolend` 目前只管本輪掛出的總額，未計入已放貸出去的部位，尚非真實總曝險上限
  （見 DECISIONS.md D011、TASKS.md M3）
- `earnings_daily` 只有表結構與 `upsert_daily_earning()` 介面，尚無資料來源與呼叫端
  （需另接 Bitfinex ledger 端點，見 DECISIONS.md D013、TASKS.md M3）
- `main.py` 三條退出路徑在落帳失敗時會蓋掉原始錯誤（DB 故障或 volume 掉了的情況下，
  離開碼會從 2 變成 1、通知也不會送出），見 TASKS.md A3
- 資料庫相對路徑的解析方式主程式與 healthcheck 兩邊不一致（前者相對 cwd、後者相對
  專案根目錄）。目前三條啟動路徑的 cwd 剛好都對，尚不會出錯，見 TASKS.md A4
- 容器 healthcheck 目前只標記 healthy／unhealthy，**不會自動重啟**卡死的容器
  （`--health-on-failure=restart` 的評估前提已因 A1 改變，見 TASKS.md A6）
- CI deploy job 的「驗證容器生命週期真的由 systemd 接管」步驟**擋不住它想擋的迴歸**：
  它斷言 conmon 存在與 `podman logs` 有內容，但這兩件事在舊的 `podman run` 做法下、
  於 job 執行期間同樣成立（舊做法的 conmon 是 job 收尾才被清掉）。修法是改為比對
  conmon 的 cgroup 歸屬，見 TASKS.md B1。**在那之前不要把這道檢查當成迴歸保險**
- systemd 用盡 `StartLimitBurst` 放棄重啟後，單元停在 `failed` 而**不會通知任何人**，
  機器人等於無聲躺平。舊的 `--restart=on-failure:3` 同樣沒有通知（只是從未真的執行），
  因此不是新的迴歸，但實單前必須補上，見 TASKS.md B2
- 部署目錄尚無 `secrets.env`，`dry_run: true` 下不影響，實單前必須補上

本專案尚未發版（無 git tag），暫不建立版本號段落；待 M1～M4（見 PLAN.md）完成、
可穩定 dry-run 常駐後，再開始標記版本。

### Fixed（2026-08-09，分支 `fix/m4-ci-lifecycle-assertion`）
- CI deploy job 的「驗證容器生命週期真的由 systemd 接管」步驟：`podman logs` 斷言改為
  合併 stderr（`2>&1`）並同時檢查 podman 指令本身的離開碼。舊寫法
  `$(podman logs ... 2>/dev/null)` 只捕捉 stdout，而機器人的日誌全走 stderr、
  容器 stdout 恆空，導致這道檢查自 2026-08-02 加入起就不可能通過（見 DECISIONS.md D018）
- 同一步驟的 conmon 判斷由「行程是否存在」改為「cgroup 是否屬於 `shuyu-lending-bot.service`」，
  讓它真的擋得住「部署改回 CI job 直接 `podman run`」的迴歸（TASKS.md B1）

### Fixed（2026-08-09，分支 `fix/m4-code-audit-findings`）
- `main.py` 三條退出路徑的落帳改由 `_record_exit_reason()` 包住，DB 故障時不再蓋掉
  原始錯誤、不再吃掉通知、也不再讓離開碼從 `EXIT_FATAL` 變成 `EXIT_UNEXPECTED`
  （systemd 的 `RestartPreventExitStatus=2` 依賴它）；`finally` 的 `close()` 一併保護
- `db/repository.py` 新增 `resolve_db_path()`：`database.path` 的相對路徑一律相對於
  專案根目錄（與 `scripts/healthcheck.py` 一致），`BFX_DB_PATH` 在兩邊都有最高優先權。
  修正前若從專案目錄以外啟動，健康檢查會永遠回報「尚未寫入任何心跳」

### Added（2026-08-09）
- `config.yaml` 的 `engine:` 補上 `health_max_silence_seconds` 說明（註解狀態，
  不設就是 `interval_seconds × 3 + 60`）

### Added（2026-08-09，分支 `deploy/m4-failure-alert`）
- 失效告警（TASKS.md B2）：主單元掛上 `OnFailure=shuyu-lending-bot-alert.service`，
  新增 `systemd/shuyu-lending-bot-alert.service` 與主機端 `scripts/notify_failure.py`。
  告警會分辨「systemd 正在重試」（ERROR）與「已放棄、需人工介入」（CRITICAL），
  寫進機器人日誌檔與 `bot_state.last_action`，**不碰心跳 `last_run_at`**。
  LINE 推播位置已留好，待憑證到位
- CI deploy job 新增「驗證失效告警已接上」步驟與告警單元／腳本的安裝步驟

### Changed（2026-08-09）
- 容器 healthcheck 觀察期滿，Quadlet 加上 `HealthOnFailure=kill`（TASKS.md A6）：
  不健康的容器由 podman 殺掉（離開碼 137），重啟仍然只由 systemd 負責，
  避免 podman 與 systemd 兩套重啟機制並存

### Changed（2026-08-15，分支 `refactor/m4-layering`）
- 完成分層搬遷，`modules/` 移除：`exchange_client.py` → `api/bitfinex_client.py`、
  `lending_strategy.py` → `strategies/frr_plus.py`、`line_notifier.py` →
  `notify/line_messaging.py`（**只搬位置，內容仍是已停用的 LINE Notify**）
- 新增 `api/base.py`（`ExchangeClient` 介面）、`strategies/base.py`（`Strategy` 介面
  與 `OfferPlan`）、`core/bot_engine.py`（`BotEngine` 主迴圈與 `FailureTracker`）
- `main.py` 精簡為 bootstrap（227 → 60 行），巡檢流程與離開碼常數移入 `core/bot_engine.py`
- 策略類別更名 `LendingStrategy` → `FrrPlusStrategy`
- 測試 import 路徑同步調整，`test_exchange_client.py` → `test_bitfinex_client.py`、
  `test_lending_strategy.py` → `test_frr_plus.py`；CI 的 `py_compile` 清單一併更新
- 行為零變動：283 項測試（含 live）維持全過，另以 dry-run 實跑 `main.py` 驗證接線


## 2026-08-16（夜間第二段）

### 修正

- **定價補上成交資料源，不再被一筆低價大單牽著走**（DECISIONS.md D033）。
  當晚簿子底端一道 182 萬 USD 的低價牆，讓只看訂單簿的排隊規則把報價砍到
  年化 5.47%，並真的用半價把 344.30 USD 借了出去。新增
  `BitfinexClient.get_recent_trades()`，策略以「同天期成交的金額加權中位數」
  為常態成交價，掛單利率不得低於其 85%；拿不到成交資料就整輪不掛。
- **掛單利率改為無條件捨去**（`round()` → `_quantize()`，8 位小數）。
  四捨五入會把價位往上推，跨過某一檔就從「排它前面」變成「同價而排它後面」。
- **`describe_queue()` 由 `<` 改為 `<=`**：同價位的錢要算進「前面」（時間優先），
  與 `_price_from_depth()` 一致。修正前在有牆時低估 1,775 倍。
- **`minimum_rate` 0.0001 → 0.00021918**（**年化 8.00%**，使用者指定）。
  語意是「年化 8% 以下我不借」，低於它的那一輪整輪不掛單。這個值會實際咬到——
  歷史成交帶是 8.68%～10.00%，8% 就貼在下緣。

### 新增

- 日誌每輪寫出「市場常態成交價」，與掛單利率對照。
- `positions_closed()` 通知補上實際借出時長、提前還款或到期、利息毛估；
  提前還款時第一行直接講明。
- `/v2/trades/fUSD/hist` 的即時契約測試。測試 469 → 479 項。

### 變更

- `format_rate()` 由 6 位小數改為 8 位——這個市場的價差就落在第 7、8 位上，
  6 位會把 `0.00014999` 顯示成 `0.000150`。
