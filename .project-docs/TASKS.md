# TASKS

## 進行中
（無）

## 待處理（依優先級，對應 PLAN.md 的 M1～M4）

### M1：修正致命問題
- [ ] 修正 `get_frr()`：改抓 Bitfinex V2 `GET /v2/ticker/fUSD` 的 FRR 欄位（目前用
      `fetch_funding_rate` 讀到永續合約資金費率，數據錯誤，不是真正的放貸 FRR）
- [ ] 通知模組改寫為 `notify/line_messaging.py`，走 LINE Messaging API push
      （取代已停用的 LINE Notify）—— **被下方使用者端待辦卡住，尚無法實測**
- [ ] `main.py` 加入 `while True` 主迴圈 + `time.sleep(interval)` + 例外分類隔離
      （`RetryableError` / `FatalError` / `SkipCycleError`）

### M2：補策略與風控
- [ ] `cancel_active_offers()` 真正實作取消未成交掛單（`cancel_funding_offer`），
      目前僅 `fetch_open_orders` 回傳清單，未真的取消，也不可動到已成交的 active loan
- [ ] 策略層補「只補掛差額」，避免重複掛出已成交部分
- [ ] 策略層補多筆階梯利率（spread），對應 MikaLendingBot 的 `spreadlend` 完整版
- [ ] 補 `maxtolend` / `maxpercenttolend` 風控上限檢查

### M3：資料與可觀測
- [ ] 建立 `db/`（`models.py` + `repository.py`），SQLite WAL 模式，記錄
      `loan_offers`、`earnings_daily`、`bot_state`
- [ ] `utils/logger.py` 改用 `RotatingFileHandler`（目前 `FileHandler` 24 小時常駐會讓單檔
      無限增大；雖然 `start.sh` 目前每次啟動都會建立帶 timestamp 的新檔，但改成程式內
      `while True` 常駐後，同一個檔案還是會持續增長）
- [ ] 建立 `api/rate_limiter.py`：`with_retry` decorator，指數退避重試，捕捉
      `ccxt.RateLimitExceeded` / `ccxt.NetworkError`
- [ ] 補 heartbeat（每輪成功巡檢送出）與連續 N 次失敗告警

### M4：架構重構、測試與部署
- [ ] 依 ARCHITECTURE.md 完成目錄搬遷：
      `modules/exchange_client.py` → `api/bitfinex_client.py`（+ 新增 `api/base.py`）、
      `modules/lending_strategy.py` → `strategies/frr_plus.py`（+ 新增 `strategies/base.py`）、
      新增 `core/bot_engine.py`、`modules/line_notifier.py` → `notify/line_messaging.py`
- [ ] 建立 `tests/unit`、`tests/functional`、`tests/integration` 目錄與基本測試
      （目前完全沒有測試檔案，CI 的 pytest 步驟因目錄不存在等於沒東西可跑）
- [ ] 收斂部署路線為 Podman 容器化（見 DECISIONS.md D007）：
      - 決定容器崩潰重啟策略（`podman run --restart` 或 `podman generate systemd`）
      - 確認 `systemd/bfx-lending-bot.service` 的去留（改為本機測試用途）
- [ ] 小額真金測試前，再次確認 API Key 權限已禁止「提現（Withdraw）」

## 基礎建設待辦（使用者端）
- [ ] 申請 LINE Developers Channel，取得 `Channel Access Token` 與 `User ID`
      （目前尚未申請，是 M1 通知模組串接測試的前置阻塞項目）

## 已完成
- [x] PRD.md／SHUYU_PROJECT_PLAN.md 規劃書撰寫，含附錄 B 實作指引（2026-07-14）
- [x] dry-run 雛型：`main.py` 單次執行流程、`config/settings.py` 讀取、
      `modules/lending_strategy.py` 策略骨架（門檻/拆單/天期判斷）（2026-07-14 之前）
- [x] CI workflow 骨架 `.github/workflows/python-app.yml`（test/integration/deploy 三個 job）
      （2026-07-14）
- [x] `.project-docs/` 文件結構建立，舊規劃書內容分類歸位（2026-07-26）
