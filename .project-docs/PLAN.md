# PLAN

## 目標

打造一個可 24 小時常駐、模組解耦、可觀測的 Bitfinex USD 放貸機器人。核心是把
[MikaLendingBot](../../MikaLendingBot) 的策略精華（FRR 底線、spread 分批、xDays 動態天期、
maxtolend 風控）以 Python 3 + `ccxt`（Bitfinex V2 API）重寫成純函式策略層，取代原本已停用的
Python 2 / Bitfinex V1 API 版本，並補上主迴圈狀態機、Rate Limit 重試、SQLite 收益記錄，
最終以 Podman 容器化常駐部署。

目前狀態：現有程式碼是「單次 dry-run 雛型」（跑一次即結束），本 milestone 規劃即是把它推進到
可正式上線常駐運作的版本。

## Milestone

- [ ] M1：修正致命問題 —— 讓現有雛型「正確」
  - 修正 `get_frr()` 誤用永續合約資金費率的問題，改抓 Bitfinex V2 `/v2/ticker/fUSD` 的真實 FRR
  - 通知模組改寫為 LINE Messaging API push（取代已於 2025-03 停用的 LINE Notify）
  - `main.py` 加入 `while True` 主迴圈 + `time.sleep(interval)` + 例外分類隔離
- [ ] M2：補策略與風控
  - `cancel_active_offers()` 真正實作取消未成交掛單（目前只回傳清單，未真的取消）
  - 策略層補「只補掛差額」、多筆階梯利率（spread）、`maxtolend` 風控上限
- [ ] M3：資料與可觀測
  - 建立 `db/`（SQLite WAL 模式），記錄掛單與每日收益
  - `logger` 改用 `RotatingFileHandler`；補 API Rate Limit 重試、heartbeat 與失敗告警
- [ ] M4：架構重構、測試與部署
  - 依 [ARCHITECTURE.md](ARCHITECTURE.md) 完成 `config/api/strategies/core/db/notify/utils` 分層搬遷
  - 補齊 `tests/unit`、`tests/functional`、`tests/integration`，CI 真正跑得動
  - 收斂部署路線為 Podman 容器化（見 [DECISIONS.md](DECISIONS.md) D007），先 dry-run 驗證再小額實單

四個 milestone 依 [SHUYU_PROJECT_PLAN.md 附錄 B](../archive/SHUYU_PROJECT_PLAN.md) 的「第一步～第四步」
一一對應，介面簽章、設定鍵名、邊界情況等實作規格以該附錄為準。

暫不設定具體時間目標，按開發步驟循序推進；若之後有明確時間目標，再回來補上。

## 目前所在位置

規劃/文件建立階段。程式碼尚未開始改動，下一步是從 M1 的三個致命問題開始修正。
