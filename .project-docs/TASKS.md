# TASKS

## 進行中
（無）

## 🔴 下一步・最高優先

（無，已於 2026-07-26 完成調查並記錄為 DECISIONS.md D010，解除阻塞，見下方「已完成」）

## 待處理（依優先級，對應 PLAN.md 的 M1～M4）

### M1：修正致命問題
- [x] 修正 `get_frr()`：改抓 Bitfinex V2 `GET /v2/ticker/fUSD` 的 FRR 欄位（原本用
      `fetch_funding_rate` 讀到永續合約資金費率，數據錯誤，不是真正的放貸 FRR）
      （2026-07-26，分支 `fix/m1-frr-and-loop`）
- [x] `main.py` 加入 `while True` 主迴圈 + `time.sleep(interval)` + 例外分類隔離
      （`RetryableError` / `FatalError` / `SkipCycleError`，見 `utils/exceptions.py`）
      （2026-07-26，分支 `fix/m1-frr-and-loop`）

### M2：補策略與風控
- [x] `cancel_active_offers()` 真正實作取消未成交掛單，改用 Bitfinex V2 raw API
      （`private_post_auth_r_funding_offers_symbol` 查詢 + `private_post_auth_w_funding_offer_cancel`
      取消），原本誤用 `fetch_open_orders` 查錯訂單類型、且從未真的取消
      （2026-07-26，分支 `feature/m2-strategy-and-risk`）
- [x] `create_loan_offer()` 改走 raw API（`private_post_auth_w_funding_offer_submit`，
      `type="LIMIT"`），原本檢查的 `create_funding_offer`/`createFundingOffer` 在 ccxt
      裡從未存在過，實盤模式下必定失敗（2026-07-26，見 DECISIONS.md D010）
- [x] 掛單更新機制：改為「每輪全取消重掛」，`run_once()` 補上 `cancel_active_offers()`
      呼叫與 `cancel_settle_seconds` 等待。原需求寫的「只補掛差額」前提有誤（funding 錢包
      的 `free` 本來就已扣除掛單與已放貸金額），實質問題是舊掛單利率落後市場
      （2026-07-26，見 DECISIONS.md D011）
- [x] 策略層補多筆階梯利率（spread）：百分比遞增（`spread_step_pct`）、金額均分、餘數併入
      第一筆、筆數依 `min_loan_size_usd` 自動降階、每筆各自判斷天期
      （2026-07-26，見 DECISIONS.md D011）
- [x] 補 `maxtolend` / `maxpercenttolend` 風控上限檢查（單輪量控版，觸及上限縮量掛；
      預設 0 = 不限制）（2026-07-26，見 DECISIONS.md D011）

### M3：資料與可觀測
- [x] 建立 `db/`（`models.py` + `repository.py`），SQLite WAL 模式，記錄
      `loan_offers`、`earnings_daily`、`bot_state`
      （2026-07-27，分支 `feature/m3-data-and-observability`）
- [x] `utils/logger.py` 改用 `RotatingFileHandler`，並移除 `logger.py`／`start.sh` 兩處的
      檔名時間戳邏輯——常駐後每次重啟另起一串新檔的話，`backup_count` 形同沒有上限
      （2026-07-27，見 DECISIONS.md D013）
- [x] 建立 `api/rate_limiter.py`：`with_retry` decorator，指數退避重試。攔的是
      `exchange_client` 已分類好的 `RetryableError` 而非 ccxt 原始例外，因此一行即可套用；
      `create_loan_offer()` 刻意不套（掛單不冪等，重試會重複借出）
      （2026-07-27，見 DECISIONS.md D013）
- [x] 補 heartbeat（`bot_state.last_run_at`，每輪含略過都更新）與連續 N 次失敗告警
      （`FailureTracker`，只在跨門檻與恢復時各送一次）（2026-07-27，見 DECISIONS.md D013）
- [ ] 評估把 `maxtolend` 從「單輪量控版」升級為「含已放貸的真實總曝險版」：需每輪查詢
      `private_post_auth_r_funding_credits_symbol`（已被借走）與
      `private_post_auth_r_funding_loans_symbol`（已出借未被借走），這兩份查詢結果 DB 也用得到
      （2026-07-26 決定延後，見 DECISIONS.md D011）
- [ ] 接上 `earnings_daily` 的資料來源：新增查詢 Bitfinex ledger
      （`/v2/auth/r/ledgers/{ccy}/hist`）取得利息入帳紀錄，餵給既有的
      `upsert_daily_earning()`。M3 只建了表與介面，尚無呼叫端；dry-run 下無法驗證正確性，
      建議與小額實單測試一起做（2026-07-27 決定延後，見 DECISIONS.md D013）

### M4：架構重構、測試與部署（依 DECISIONS.md D015 拆成子分支）
- [ ] **子分支 `refactor/m4-layering`**：依 ARCHITECTURE.md 完成目錄搬遷：
      `modules/exchange_client.py` → `api/bitfinex_client.py`（+ 新增 `api/base.py`）、
      `modules/lending_strategy.py` → `strategies/frr_plus.py`（+ 新增 `strategies/base.py`）、
      新增 `core/bot_engine.py`、`modules/line_notifier.py` → `notify/line_messaging.py`。
      搬遷時 `tests/` 的 import 路徑要同步改，改完重跑 227 項即可確認沒搬壞
- [x] 建立 `tests/unit`、`tests/functional`、`tests/integration` 目錄與測試，共 227 項
      （2026-08-01，分支 `test/m4-test-suite`）。一併補掉三個 CI 缺口：拿掉
      `pytest ... || true`（測試失敗必須擋下合併）、新增 `requirements-dev.txt`
      取代臨時的 `pip install pytest`、把 workflow 內嵌的 heredoc smoke test 收斂進
      `tests/integration/test_dry_run_cycle.py`
- [x] 修正 `upsert_daily_earning()` 的 `principal_avg` 缺陷（2026-08-01，測試抓到）：
      `db/models.py` 宣告 `NOT NULL` 但函式簽章預設 `None` 且 ON CONFLICT 用了
      `COALESCE`，NOT NULL 在衝突解析前先擋下，導致首次插入與後續累加兩條路徑都必定
      `IntegrityError`。改為 `principal_avg REAL`；當時尚無任何 DB 檔存在，遷移成本為零
- [ ] **子分支 `deploy/m4-podman`**：收斂部署路線為 Podman 容器化（見 DECISIONS.md D007）：
      - [x] 修正部署一直失敗的主機端目錄問題（2026-08-01）：podman 的 bind mount 不會
            自動建立主機端目錄，`.../ShuyuLendingBot/data` 從未存在，deploy job 自 M3
            加上該 volume 起每次都以 exit code 125 失敗。workflow 補 `mkdir -p` 一步
      - [ ] 補 `secrets.env` 到部署目錄（`/workspace/deploy/active-bots/ShuyuLendingBot/`）。
            目前該檔不存在，`dry_run: true` 下不影響，**實單前必須補上**（使用者端待辦）
      - [x] `podman logs` 取不到內容（log driver 為 `journald`，rootless 下拿不到）：
            改用 `--log-driver=k8s-file`（含 `max-size=10mb`），CI 的「取得最近容器日誌」
            改讀掛載出來的 `logs/bfx_lending_bot.log`，`podman logs` 降為備援
            （2026-08-02，分支 `deploy/m4-podman-hardening`，見 DECISIONS.md D016）
      - [x] 清理 `logs/` 底下 M3 之前產生的帶時間戳舊檔（部署目錄 7 個、專案目錄 4 個），
            刪前確認全是 dry-run 常規巡檢、無 ERROR/CRITICAL（2026-08-02）
      - [x] 容器崩潰重啟策略：採 `--restart=on-failure:3`（次數上限），
            `docker-compose.yml` 同步由 `unless-stopped` 改為 `on-failure`（2026-08-02）
      - [x] `FatalError` 與自動重啟的衝突：`main.py` 離開碼語意化為
            `EXIT_OK=0` / `EXIT_UNEXPECTED=1` / `EXIT_FATAL=2`，三條退出路徑退出前
            都先把原因寫進 `bot_state.last_action`。restart policy 看不到離開碼，
            節流靠 `on-failure:3` 的次數上限（2026-08-02）
      - [x] 容器 healthcheck：新增 `scripts/healthcheck.py`，唯讀讀取
            `bot_state.last_run_at` 判斷心跳是否過期（門檻 = 巡檢間隔 × 3 + 60 秒）。
            **刻意不看 `consecutive_failures`**——那是交易所端的問題，重啟容器無益，
            已由 `FailureTracker` 告警負責（2026-08-02，見 DECISIONS.md D016）
      - [ ] 觀察期滿後評估加上 `--health-on-failure=restart`：目前 healthcheck 只標記
            healthy/unhealthy，不會自動處理。先累積一段實際運行資料確認不會誤判，
            再決定要不要讓卡死的容器自動重啟（2026-08-02 決定延後，見 DECISIONS.md D016）
      - [ ] 本 PR 合併後確認正式容器已套用新參數：正在跑的容器仍是舊設定
            （無 restart、journald），要等 CI 重新部署才生效。屆時確認
            `podman ps` 顯示 healthy、`podman logs` 有內容
      - 確認 `systemd/bfx-lending-bot.service` 的去留：D016 已決定維持本機測試用途，
        正式路線不採 `podman generate systemd`；檔案本身的去留仍待確認
- [ ] 小額真金測試前，再次確認 API Key 權限已禁止「提現（Withdraw）」
- [ ] **子分支 `feature/m4-line-messaging`**：通知模組改寫為 `notify/line_messaging.py`，走 LINE Messaging API push
      （取代已停用的 LINE Notify）—— 原列在 M1，2026-07-26 使用者指示改排到最後一步；
      **被下方使用者端待辦卡住，尚無法實測**。一併注意 `config/settings.py` 讀的環境變數
      名還是舊的 `LINE_NOTIFY_TOKEN`／`LINE_NOTIFY_CHANNEL`，要同步改成
      `LINE_CHANNEL_ACCESS_TOKEN`／`LINE_TO_USER_ID`（2026-07-27 於 M3 發現）
- [ ] 清理已合併完成的殘留分支：`fix/m1-frr-and-loop`、`feature/m2-strategy-and-risk`、
      `docs/sync-m2-branch-workflow`、`feature/roadmap-and-tests`（本地與遠端）
      （2026-07-27 使用者選擇先不處理）

## 基礎建設待辦（使用者端）
- [ ] 申請 LINE Developers Channel，取得 `Channel Access Token` 與 `User ID`
      （目前尚未申請，是 LINE 通知模組串接測試的前置阻塞項目）

## 已完成
- [x] 設定 git `user.name` / `user.email` 為 `Chen-shuyu` / `suyuchen322@gmail.com`
      （原本所有 commit 作者都是 `shuyu <shuyu@localhost.localdomain>`，GitHub 關聯不到帳號）
      （2026-07-27）
- [x] `.gitignore` 補上 `data/` 與 `*.sqlite3` 系列：原本完全沒排除，M3 建立的 SQLite 檔
      會被 commit 進 git（2026-07-27）
- [x] `podman run` 與 `docker-compose.yml` 補掛 `/app/data` volume，否則每次重新部署
      SQLite 紀錄就歸零（2026-07-27）
- [x] 調查 ccxt 第三方套件在 Bitfinex funding 功能上的可靠性，決定往後統一的呼叫方式：
      確認 ccxt 對 Bitfinex funding 從未實作過統一（unified）方法（非版本移除），一律改走
      raw/implicit API；同時查證 Bitfinex 官方 REST 文件，盤點 19 個 funding 端點規格，
      逐一比對現有程式碼用法。結論記錄為 DECISIONS.md D010，詳細盤點見
      `.project-docs/CCXT_BITFINEX_API_INVESTIGATION.md`（2026-07-26）
- [x] 修正 `test_connection()`：`fetch_balance()` 補上 `type="funding"`，與
      `get_available_balance()` 查詢同一個錢包（2026-07-26，見 DECISIONS.md D010）
- [x] PRD.md／SHUYU_PROJECT_PLAN.md 規劃書撰寫，含附錄 B 實作指引（2026-07-14）
- [x] dry-run 雛型：`main.py` 單次執行流程、`config/settings.py` 讀取、
      `modules/lending_strategy.py` 策略骨架（門檻/拆單/天期判斷）（2026-07-14 之前）
- [x] CI workflow 骨架 `.github/workflows/python-app.yml`（test/integration/deploy 三個 job）
      （2026-07-14）
- [x] `.project-docs/` 文件結構建立，舊規劃書內容分類歸位（2026-07-26）
- [x] 修正 `ccxt.bitfinex2`（已於目前釘選的 ccxt 版本移除）改用 `ccxt.bitfinex`，並修正
      `get_available_balance()` 未指定 `type: "funding"`、解析格式對不上新版 ccxt 統一
      balance 結構的問題（意外發現，見 DECISIONS.md D009）（2026-07-26）
- [x] 同步調整 CI smoke test：`main()` 已變成常駐迴圈不會自己返回，smoke test 改為呼叫
      `run_once()` 跑單輪（2026-07-26）
