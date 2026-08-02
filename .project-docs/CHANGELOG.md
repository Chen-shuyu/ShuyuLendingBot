# CHANGELOG

## [Unreleased]
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

### Changed
- 移除 `strategy.split_threshold_usd`：原「餘額超過 300 才對半拆單」的語意已被 spread 的
  自動降階規則（餘額不足 `筆數 × min_loan_size_usd` 就降階）等價涵蓋
- log 檔名不再附加啟動時間戳（`utils/logger.py` 與 `start.sh` 各一處），改為固定檔名 +
  大小輪替；否則每次重啟另起一串新檔，`backup_count` 等於沒有上限
- CI 的測試步驟移除 `|| true`：測試失敗現在會擋下合併。原本的寫法讓 CI 永遠綠燈，
  等於寫了測試也攔不住壞掉的程式碼
- CI 內嵌的 heredoc smoke test 收斂進 `tests/integration/test_dry_run_cycle.py`，
  workflow 不再需要維護兩份驗證邏輯；測試依賴改由 `requirements-dev.txt` 統一安裝

### Known Issues
- `line_notifier.py` 呼叫已停用的 LINE Notify 端點，通知永遠失敗（待使用者申請 LINE
  Developers 憑證後改寫為 Messaging API，見 TASKS.md）。**連帶影響**：M3 的連續失敗告警
  目前實際上只會留在日誌裡，換成 Messaging API 後即自動生效
- `maxtolend` 目前只管本輪掛出的總額，未計入已放貸出去的部位，尚非真實總曝險上限
  （見 DECISIONS.md D011、TASKS.md M3）
- `earnings_daily` 只有表結構與 `upsert_daily_earning()` 介面，尚無資料來源與呼叫端
  （需另接 Bitfinex ledger 端點，見 DECISIONS.md D013、TASKS.md M3）
- `FatalError` 會讓程式 `return 1` 退出，但容器設 `restart: unless-stopped`，
  金鑰失效這類錯誤會導致無限重啟迴圈（見 TASKS.md M4）
- CI 的 `podman run` 沒有任何 `--restart` 參數，容器崩潰後不會自行復原；與
  `docker-compose.yml` 的 `restart: unless-stopped` 兩邊策略不一致（見 TASKS.md M4）
- `podman logs shuyu-lending-bot` 取不到任何內容（log driver 為 `journald`），
  deploy job 最後的「取得最近容器日誌」步驟等於空跑；除錯需改讀掛載出來的 log 檔
- 部署目錄尚無 `secrets.env`，`dry_run: true` 下不影響，實單前必須補上

本專案尚未發版（無 git tag），暫不建立版本號段落；待 M1～M4（見 PLAN.md）完成、
可穩定 dry-run 常駐後，再開始標記版本。
