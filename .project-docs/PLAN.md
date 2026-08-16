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

- [x] M1：修正致命問題 —— 讓現有雛型「正確」
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
- [x] M4：架構重構、測試與部署（依 DECISIONS.md D015 拆成 3~4 條子分支，各自開 PR）
  - [x] 依 [ARCHITECTURE.md](ARCHITECTURE.md) 完成 `config/api/strategies/core/db/notify/utils`
        分層搬遷（2026-08-15，分支 `refactor/m4-layering`，見 DECISIONS.md D021）
  - [x] 補齊 `tests/unit`、`tests/functional`、`tests/integration`，CI 真正跑得動
        （2026-08-01，分支 `test/m4-test-suite`，227 項；CI 的 `|| true` 一併拿掉）
  - [x] 收斂部署路線為 Podman 容器化（見 [DECISIONS.md](DECISIONS.md) D007、D016、D017）：
        部署已恢復、容器可靠性四項（重啟節流、離開碼語意化、日誌取得、心跳健康檢查）
        全部完成並實測生效（2026-08-01～02）。其中自動重啟與容器日誌兩項一度因 conmon
        被 CI job 殺掉而未生效，已於 2026-08-02 把容器生命週期改由 systemd --user 的
        Quadlet 單元管理後解決。仍在 dry-run 驗證階段，小額實單待使用者補 `secrets.env`
  - [x] 通知模組改寫為 LINE Messaging API push（取代已於 2025-03 停用的 LINE Notify）
        （2026-08-15，分支 `feature/m4-line-messaging`，見 DECISIONS.md D024）。
        兩條管道各實際送出一則測試訊息並確認送達；因免費方案每月 200 則，
        例行巡檢改為只寫日誌、通知管道只送事件

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
- [x] **`refactor/m4-layering`（2026-08-15）**：分層搬遷完成，見 DECISIONS.md D021。
      `modules/` 移除，四個檔案歸位到 `api/`／`strategies/`／`notify/`，新增
      `api/base.py`、`strategies/base.py`、`core/bot_engine.py`；`main.py` 縮為純
      bootstrap（227 → 60 行）。**行為零變動**——283 項測試的斷言一行沒改就全過，
      另以 dry-run 實跑 `main.py` 驗過接線
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
- [x] **`feature/m4-line-messaging`（2026-08-15）**：LINE Messaging API 接上並實測送達，
      見 DECISIONS.md D024。環境變數改名、`config.yaml` 的 `line.enabled` 開啟、
      主機端告警腳本一併接上（INFO 不推）。**M4 至此全部完成**

**M4 已全部完成（2026-08-15）**：測試、部署、分層重構、LINE 通知四條子分支都收尾。
可靠性目標有對照實驗與正式容器實測佐證，CI 的迴歸防線已從「看起來有」變成
「真的擋得住」（D018），兩輪盤查累積的六項缺陷（A1～A6、B1～B3）與後續的 B4 全部清完。
通知管道兩條（主程式、systemd 失效告警）都已實測送達。

## 目前所在位置：小額真金測試進行中（2026-08-15 上線）

**四個 milestone 全部完成，機器人已在真金模式常駐運作。**
2026-08-15 完成上線：LINE 通知（D024）→ `dry_run: false`（#20）→
兩個實單才浮現的 bug 修正（D025、D026）。目前掛出 160 USD、日利率 0.000523、2 天期，
曝險上限由融資錢包餘額鎖住（其餘資金已移到現貨錢包）。

實單第一天的收穫比預期大：**兩個 bug 都是 dry-run 與既有測試不可能發現的**
（掛單金額四捨五入超出餘額、取消掛單的 id 型別），因為 dry-run 下
`create_loan_offer()` 直接回傳假成功、沒有任何人驗證參數合不合法。
兩者的共同成因寫成 D027（測試替身與測試資料一律取自真實回應）。

### 2026-08-16 更新：定價基準查明用錯，並重排工作順序

**掛單 78 輪一筆都沒成交**，根因不是參數大小，而是定價基準本身：
FRR 是落後加權平均，當日為年化 11.77%，**已經高過 fUSD 市場成交的天花板年化 10.00%**，
所以 `FRR + 任何正數` 必然掛空——連 `premium_rate = 0` 都不會成交。
昨天寫的兩條對策（降 premium 到 0.00037、改用 FRRDELTAVAR）實測都是 0 筆成交。

市場的成交價帶極窄（年化 8.68%～10.00%），借款需求側最高只有一檔 10.25%、
第二高就掉到 7.30%，放貸供給側 439 萬 USD 全擠在 9.00%～10.10%。
**訂價權不在我們手上**——由此得到這個專案的核心定價原則：

> 問題不是「利率訂多高」，而是「在這條窄帶裡站第幾位」。
> 沒成交的時間年化是 0%，所以利率差要用閒置時間去換——2 天期的單子掛在天花板，
> 只要多等超過 3.1 小時，就輸給掛中位數立刻成交。

當日以 `premium_rate: -0.00005` 做過驗證（PR #24），掛單利率降到 0.000273，
證實這個價位確實有人成交，但成交是**陣發的**（3.7 小時的 23 個時段只有 3 個時段
有 ≥0.000273 的成交），至今仍未成交。同日另完成時區統一（PR #25，D028）。

### 2026-08-16 稍晚更新：定價根因修掉，成交偵測上線（D030）

**掛單一直落在整個供給側的最後面**——舊策略掛 0.000272，而當時簿子頂端就是 0.000272。
定價改以「排隊位置」為基準（讀訂單簿深度，不是原規劃的 trades 百分位，
因為後者會被爆發桶汙染而重演 FRR 的落後問題）。實測會掛 0.000250、前方排隊 73 萬 USD。

同時完成 **P2-1 成交偵測**（機器人終於知道自己借出去了）、拆掉 spread 的死單地雷
（`spread_count: 3 → 1`），並修掉一個沒列進計畫的問題：**每輪無條件取消重掛，
把時間優先權歸零，一天 144 次**。

三份實測改寫了既有規劃：P1-2「7 天期高 0.5 個百分點」的論據取自含爆發桶的窗而不成立；
長期資料顯示長天期確實較優但溢價會大幅變動，**寫死任何天期都是錯的架構**；
而 344 USD 的規模讓 P3-1／P3-2 的年收益都是 0 元，兩項因此降級。

### 接下來的順序（詳見 [TASKS.md](TASKS.md) 的「工作計畫」）

**一句話總結現況：所有「不出事」的能力都做完了，「賺錢」那條主線一次都沒跑通。**

1. **讓錢真的借得出去**（P1）——定價改為跟著市場成交價走（取中位數附近的百分位，
   不是原先寫的第 90），天期由 2 天改為 7 天。擋在「賺到第一塊錢」前面的只有這兩項。
   另加一項五分鐘的前置（P1-3）：**純文件變更不要觸發部署重啟**——現在推上 main
   就會重啟並把掛單取消重掛，等於用一次文件同步重置一張正在排隊的單子，
   而這個價位的成交本來就是陣發的，白白拉長 P1 的驗證期。
2. **成交之後要看得見**（P2）——2026-08-16 讀程式碼時發現：**機器人成交了自己不知道**。
   餘額歸零後日誌只寫「可放貸金額不足，略過本輪」，與「錢包本來就空的」完全一樣，
   沒有通知、DB 也沒有紀錄。這是 D026「靜默失效」的鏡像（靜默成功）。
   補上已借出部位的查詢後，`earnings_daily` 才接得上 ledger 資料源。
   同一層再加兩項通知面的工作：**P2-3 訊息格式規範**（現有六則訊息是散在程式各處的
   裸字串，沒有任何地方負責組訊息；分成【系統】【交易】【收益】【風控】四類、
   結論放第一行、最後一行明講要不要人工介入）與 **P2-4 交易面通知擴充**
   （掛單／成交／日結）。後者受**每月 200 則**額度硬限制，只能走
   「事件驅動 ＋ 每日一則摘要」，掛單通知必須「有變化才推」。
3. **把錢轉回來之前必做**（P3）——spread 階梯的乘法遞增會在金額超過 300 USD 時
   產生必定掛空的死單；`maxtolend` 升級為含已放貸的真實總曝險版（與 P2 共用查詢）。
4. **品質債**（P4）——B6 測試替身校正（建議排在接 ledger 之前）、B5 錯誤分類。
5. **雜務**（P5）——清理 23 條殘留分支、`systemd/bfx-lending-bot.service` 去留。

暫不設定時間目標，按開發步驟循序推進。
