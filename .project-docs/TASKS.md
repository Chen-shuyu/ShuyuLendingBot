# TASKS

## 進行中
（無）

## 🔴 下一步・最高優先（阻塞 M2 其餘項目與 M3／M4，先查完才能繼續）

- [ ] **調查 ccxt 第三方套件在 Bitfinex funding 功能上的可靠性，決定往後統一的呼叫方式**
      （2026-07-26 使用者指示：目前已連續在三個地方踩到 ccxt 版本相關的隱藏 bug
      ——`ccxt.bitfinex2` 被移除（D009）、`fetch_balance` 預設查錯錢包且回傳格式對不上
      （D009）、`cancel_active_offers()` 原本查錯訂單類型且從未真的取消（本次修正）；
      使用者要求先把這個第三方套件的問題徹底查清楚，再繼續開發，而不是每次都撞一次修一次）。
      調查範圍：
      1. 盤點 `modules/exchange_client.py` 目前每個方法呼叫的到底是 ccxt「統一
         （unified）」方法，還是「implicit/raw」方法（如 `private_post_auth_*`／
         `public_get_ticker_symbol`）——列出清單，標明各自風險
      2. 確認並修正 `create_loan_offer()`：目前檢查 `create_funding_offer` /
         `createFundingOffer` 是否存在，但這兩個統一方法在目前釘選的 ccxt 4.5.64
         的 bitfinex（V1/V2 合併版）裡都不存在，**代表實盤模式下目前一定會在「掛單」
         這一步失敗**，是本次修 `cancel_active_offers()` 時意外發現、尚未修正的問題
      3. 評估是否乾脆整支 `exchange_client.py` 統一改走 Bitfinex V2 raw API
         （也就是使用者說的「直接打 Bitfinex API」——實際上就是 ccxt 的 implicit
         方法，如 `private_post_auth_w_funding_offer_submit`；`get_frr()` 和這次的
         `cancel_active_offers()` 已經是這種做法），減少「這個統一方法在這個 ccxt
         版本到底存不存在」的不確定性；或評估是否要更進一步完全繞開 ccxt 自行實作
         簽章直接呼叫 REST（trade-off：失去 ccxt 內建的重試/rate-limit 工具）
      4. 確認 `requirements.txt` 釘選的 `ccxt>=4.2.0`（實測 4.5.64）與 Bitfinex 相關
         的版本更動紀錄，理解為什麼 funding 相關統一方法支援不完整/不穩定
      - **在這項調查有結論並記錄成 DECISIONS.md 新決策之前，M2 其餘項目（只補掛差額、
        spread、maxtolend）與 M3／M4 一律暫緩。**

## 待處理（依優先級，對應 PLAN.md 的 M1～M4；上面調查完成前暫緩開工）

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
      （2026-07-26，分支 `fix/m1-frr-and-loop`）
- [ ] `create_loan_offer()` 改走 raw API（`private_post_auth_w_funding_offer_submit`），
      目前檢查的 `create_funding_offer`/`createFundingOffer` 在這版 ccxt 不存在，實盤
      模式下必定失敗——併入上方 ccxt 調查項目一起處理
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
- [ ] 通知模組改寫為 `notify/line_messaging.py`，走 LINE Messaging API push
      （取代已停用的 LINE Notify）—— 原列在 M1，2026-07-26 使用者指示改排到最後一步；
      **被下方使用者端待辦卡住，尚無法實測**

## 基礎建設待辦（使用者端）
- [ ] 申請 LINE Developers Channel，取得 `Channel Access Token` 與 `User ID`
      （目前尚未申請，是 LINE 通知模組串接測試的前置阻塞項目）

## 已完成
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
