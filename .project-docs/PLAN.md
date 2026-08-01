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
  - `main.py` 加入 `while True` 主迴圈 + `time.sleep(interval)` + 例外分類隔離
- [x] M2：補策略與風控
  - [x] `cancel_active_offers()` 真正實作取消未成交掛單（原本只回傳清單，未真的取消）
  - [x] 掛單更新機制改為「每輪全取消重掛」，`run_once()` 補上取消步驟與餘額釋放等待
        （原需求「只補掛差額」的前提有誤，見 DECISIONS.md D011）
  - [x] 多筆階梯利率（spread）：百分比遞增、依單筆最小量自動降階、每筆各自判斷天期
  - [x] `maxtolend` / `maxpercenttolend` 風控上限（單輪量控版，觸及上限縮量掛）
- [x] M3：資料與可觀測
  - [x] 建立 `db/`（SQLite WAL 模式），記錄掛單流水與機器人狀態
        （`earnings_daily` 只建表與介面，資料來源延後，見 DECISIONS.md D013）
  - [x] `logger` 改用 `RotatingFileHandler`（固定檔名 + 大小輪替）
  - [x] 補 API Rate Limit 重試（`api/rate_limiter.py`，掛單刻意不套）、heartbeat
        （`bot_state.last_run_at`）與連續失敗告警（`FailureTracker`）
- [ ] M4：架構重構、測試與部署（依 DECISIONS.md D015 拆成 3~4 條子分支，各自開 PR）
  - 依 [ARCHITECTURE.md](ARCHITECTURE.md) 完成 `config/api/strategies/core/db/notify/utils` 分層搬遷
  - [x] 補齊 `tests/unit`、`tests/functional`、`tests/integration`，CI 真正跑得動
        （2026-08-01，分支 `test/m4-test-suite`，227 項；CI 的 `|| true` 一併拿掉）
  - 收斂部署路線為 Podman 容器化（見 [DECISIONS.md](DECISIONS.md) D007），先 dry-run 驗證再小額實單
  - 通知模組改寫為 LINE Messaging API push（取代已於 2025-03 停用的 LINE Notify）——
    原列在 M1，2026-07-26 使用者指示改排到最後一步，待使用者申請好 LINE Developers
    Channel 憑證後才實作／實測

四個 milestone 依 [SHUYU_PROJECT_PLAN.md 附錄 B](../archive/SHUYU_PROJECT_PLAN.md) 的「第一步～第四步」
一一對應，介面簽章、設定鍵名、邊界情況等實作規格以該附錄為準。

暫不設定具體時間目標，按開發步驟循序推進；若之後有明確時間目標，再回來補上。

## 目前所在位置

**M1、M2、M3 已完成**（M1 的 LINE 通知項目依使用者指示延後至 M4 最後一步）。過程中意外發現並
一併修正的隱藏 bug（`ccxt.bitfinex2`、`get_available_balance()` 錢包查詢、
`create_loan_offer()` 呼叫不存在的方法）已全數處理完畢；「ccxt 在 Bitfinex funding 功能上的
可靠性」調查結論記錄為 DECISIONS.md D010（**funding 相關操作統一走 raw/implicit API**，
詳細盤點見 `.project-docs/CCXT_BITFINEX_API_INVESTIGATION.md`）。

2026-07-26 完成 M2 收尾三項（DECISIONS.md D011）：掛單更新改「每輪全取消重掛」、spread
百分比遞增階梯、maxtolend 單輪量控版。`cancel_active_offers()` 現已真正被主迴圈呼叫。

2026-07-27 完成 M3（DECISIONS.md D013）：日誌固定檔名輪替、`api/rate_limiter.py` 指數退避
重試（掛單刻意不套，因為不冪等）、`db/` SQLite WAL 資料層、心跳與連續失敗告警。連帶補上
`.gitignore` 的 DB 排除規則與容器的 `/app/data` volume。

2026-07-27 之後 M3 已由 **PR #6 合併進 main**（合併點 `6497d54`），六個 commit 全數驗證在 main 內。

**目前進行中：M4**，依 DECISIONS.md D015 拆成子分支推進：

- [x] `test/m4-test-suite`（2026-08-01）：`tests/` 三層測試 227 項、CI 拿掉 `|| true`、
      新增 `requirements-dev.txt` 與 `pytest.ini`、把 workflow 內嵌的 heredoc smoke test
      收斂進整合測試。過程中修掉一個測試抓出的實際缺陷：`upsert_daily_earning()` 因
      `principal_avg` 被宣告為 `NOT NULL`，整條「傳 None 保留舊值」的路徑從來無法使用
- [ ] `refactor/m4-layering`：`strategies/`、`core/`、`notify/` 分層搬遷（有測試當回歸保護）
- [ ] `deploy/m4-podman`：容器崩潰重啟策略、healthcheck、`FatalError` 與
      `restart: unless-stopped` 的衝突
- [ ] `feature/m4-line-messaging`：LINE Messaging API —— 仍卡在使用者尚未申請
      LINE Developers Channel 憑證，刻意排在最後一條
