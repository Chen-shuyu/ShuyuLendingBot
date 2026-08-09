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
  - [x] 收斂部署路線為 Podman 容器化（見 [DECISIONS.md](DECISIONS.md) D007、D016、D017）：
        部署已恢復、容器可靠性四項（重啟節流、離開碼語意化、日誌取得、心跳健康檢查）
        全部完成並實測生效（2026-08-01～02）。其中自動重啟與容器日誌兩項一度因 conmon
        被 CI job 殺掉而未生效，已於 2026-08-02 把容器生命週期改由 systemd --user 的
        Quadlet 單元管理後解決。仍在 dry-run 驗證階段，小額實單待使用者補 `secrets.env`
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
- [x] `deploy/m4-podman`（PR #8，2026-08-01）：修掉讓部署自 M3 起一直失敗的主機端目錄
      問題——**機器人已恢復常駐運行**，dry-run 下心跳與落帳皆正常
- [~] `deploy/m4-podman-hardening`（PR #10，2026-08-02）：容器可靠性四項一次收斂
      （`--restart=on-failure:3` 次數上限、離開碼語意化 0/1/2 並在退出前落帳、
      日誌驅動改 `k8s-file` 且 CI 改讀掛載出來的日誌檔、新增 `scripts/healthcheck.py`
      心跳檢查），見 DECISIONS.md D016。測試 227 → 236 項。
      **合併後驗收發現其中兩項實際上沒有生效**：容器的 conmon 行程被 CI job 收尾時
      殺掉，自動重啟從不執行、`podman logs` 依然是空的。離開碼與 healthcheck 兩項確認有效。
      這兩項已由下一條分支補完
- [x] `deploy/m4-systemd-lifecycle`（2026-08-02）：部署可靠性補完，見 DECISIONS.md D017。
      開啟 linger（A2）；容器生命週期改由 systemd --user 的 Quadlet 單元管理（A1），
      CI deploy job 不再自己 `podman run`，conmon 因而與 job 脫鉤。重啟節流改用
      `StartLimitBurst`、並用 `RestartPreventExitStatus=2` 表達「EXIT_FATAL 不重啟」
      （podman 的 restart policy 做不到）。以對照實驗＋正式容器實測驗收：
      **自動重啟與 `podman logs` 都確認生效**，後者是自 M3 以來第一次
- [ ] `refactor/m4-layering`：分層搬遷（承上方，仍未開始）
- [x] `fix/m4-audit-findings`（PR #13，2026-08-09）：純文件同步，記錄 PR #12 的驗收結果
      與 B1／B2 兩項新發現
- [x] **`fix/m4-ci-lifecycle-assertion`（2026-08-09）**：修好 CI 紅燈，見 DECISIONS.md D018。
      PR #13 合併後 deploy job 在「驗證容器生命週期真的由 systemd 接管」失敗，查出
      **systemd 接管一切正常，壞的是斷言本身**——機器人日誌走 stderr，而檢查用
      `$(podman logs ... 2>/dev/null)` 只捕捉 stdout，等於扔掉自己要找的東西（B3）。
      這道檢查自 2026-08-02 加入起就不可能通過，deploy job 一路是紅的。
      同一步驟順帶完成 **B1**（conmon 判斷改為比對 cgroup 歸屬）。
      以對照實驗驗收：正式容器通過、直接 `podman run` 的假容器紅燈
- [x] **`fix/m4-code-audit-findings`（2026-08-09）**：程式碼層三項 A3～A5 全部完成，
      見 DECISIONS.md D019。退出路徑的落帳不再蓋掉原始錯誤與離開碼、DB 相對路徑
      改以專案根目錄解析（與 healthcheck 一致）、`config.yaml` 補上健康檢查門檻設定。
      測試 255 → 265 項，三項都在故障情境下實跑驗證過
- [x] **`deploy/m4-failure-alert`（2026-08-09）**：B2 與 A6 完成，見 DECISIONS.md D020。
      systemd 放棄重啟時會透過 `OnFailure=` 送出告警（寫進日誌檔與 `bot_state.last_action`，
      不碰心跳）；容器 healthcheck 觀察期滿，以 `HealthOnFailure=kill` 接上 systemd 重啟。
      兩個實機對照實驗把「不健康 → 殺掉 → 重啟 → 放棄 → 告警」整條鏈驗過一次。
      測試 265 → 283 項。**兩輪盤查的六項缺陷至此全部清完**
- [ ] `feature/m4-line-messaging`：LINE Messaging API —— 仍卡在使用者尚未申請
      LINE Developers Channel 憑證，刻意排在最後一條

M4 目前的狀態：測試與部署兩條都已完成，**可靠性目標這次是真的達成了**（有對照實驗與
正式容器實測佐證），CI 的迴歸防線也已從「看起來有」變成「真的擋得住」（D018）。
小額實單剩下的前置條件是使用者補上 `secrets.env`。
未完的是 `refactor/m4-layering` 分層搬遷，以及被憑證卡住的 LINE 通知。
兩輪盤查累積的六項缺陷（A1～A6、B1～B3）已全部清完。
