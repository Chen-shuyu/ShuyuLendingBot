# PROGRESS

## 2026-07-26
- 完成：接手專案（原由 GitHub Copilot 協助撰寫），盤點現有 dry-run 雛型與
  `SHUYU_PROJECT_PLAN.md` 規劃書內容；建立 `.project-docs/` 文件結構
  （PLAN／PROGRESS／DECISIONS／TASKS／CHANGELOG／ARCHITECTURE），把規劃書內容分類歸位
- 完成：與使用者確認 4 項待定事項並記錄為決策：部署主線採 Podman 容器化（D007）、
  舊規劃文件歸檔至 `archive/` 不刪除（D008）、LINE 憑證尚未申請（列入 TASKS 待辦）、
  roadmap 不設具體時間點
- 進行中：（無，本輪僅整理文件，未動程式碼）
- 下一步：依 TASKS.md 的 M1 開始修正三個致命問題 —— 修正 `get_frr()`、通知模組改寫為
  LINE Messaging API、`main.py` 補上常駐主迴圈
- 遇到的問題：LINE Messaging API 的串接測試需要使用者先申請 Channel Access Token / User ID，
  暫時只能先把 `enabled=false` 的安全略過邏輯做好

### 本次（M1 開發，分支 `fix/m1-frr-and-loop`）
- 完成：M1 三個致命問題中的 2 個（LINE 部分因使用者端待辦仍卡住，暫緩）：
  - 修正 `get_frr()`：改呼叫 Bitfinex V2 公開端點 `GET /v2/ticker/fUSD`（經由 ccxt 的
    `public_get_ticker_symbol`），取陣列 index 0 為真正的放貸 FRR，取代原本誤用的
    `fetch_funding_rate`（永續合約資金費率，數據錯誤）
  - `main.py` 加入 `while True` + `time.sleep(engine.interval_seconds)` 常駐主迴圈；新增
    `utils/exceptions.py`（`RetryableError`／`FatalError`／`SkipCycleError`）做例外分類；
    捕捉 `KeyboardInterrupt` 優雅結束
  - `config.yaml` 新增 `engine.interval_seconds`／`engine.dry_run`，`main.py` 不再寫死
    `dry_run=True`
- 意外發現並一併修正 2 個原本不在 TASKS 清單上的隱藏 bug（詳見 DECISIONS.md D009）：
  - `ccxt.bitfinex2` 在目前釘選的 ccxt 4.5.64 已不存在（V1/V2 已合併為單一 `bitfinex`），
    代表實盤模式下交易所物件其實從未成功初始化過
  - `get_available_balance()` 少帶 `type: "funding"` 參數，預設查的是 exchange 錢包而非
    放貸用的 funding 錢包；且舊的 `info.funding` 解析方式對不上目前 ccxt 回傳的統一
    balance 格式
- 驗證：`python -m py_compile` 全數通過；用 `BFX_CONFIG` 指向 `interval_seconds: 1` 的暫存
  設定檔跑 `main.py`，確認多輪迴圈正常執行、`SIGINT` 能優雅結束；CI smoke test 腳本改為
  呼叫 `run_once()` 單輪（因為 `main()` 現在是常駐迴圈不會自己返回），本地重跑一致通過
- 下一步：LINE Messaging API 改寫仍卡在使用者尚未申請 Channel Access Token／User ID，
  待解除後才能補上 M1 最後一項；M2（`cancel_active_offers` 真取消、spread、`maxtolend`）
  尚未開始

### 本次（M2 開發，分支 `fix/m1-frr-and-loop`）
- 完成：LINE 通知改寫依使用者指示從 M1 移到 M4 最後一步（待 LINE Developers 憑證申請好才做）
- 完成：`cancel_active_offers()` 真正實作取消未成交放貸掛單——原本呼叫 `fetch_open_orders`
  查錯訂單類型（查到一般現貨/保證金訂單，不是放貸掛單），而且只回傳清單、從未真的取消；
  改用 Bitfinex V2 底層 raw API（`private_post_auth_r_funding_offers_symbol` 查詢 +
  `private_post_auth_w_funding_offer_cancel` 取消），因為目前釘選的 ccxt 4.5.64
  沒有提供 `fetch_funding_offers`／`cancel_funding_offer` 這兩個統一方法
- 驗證：`py_compile` 通過；用 mock 過的假 exchange 物件手動測試 4 種情境
  （dry-run 略過、正常查詢+取消 2 筆掛單且欄位解析正確、單筆取消失敗不中斷其他筆、
  查詢逾時正確轉成 `RetryableError`），全部通過（尚無正式 `tests/` 目錄，見 TASKS.md M4）
- 意外發現但**尚未修正**的問題：`create_loan_offer()` 檢查 `create_funding_offer` /
  `createFundingOffer` 是否存在來決定怎麼掛單，但這兩個統一方法在目前 ccxt 版本的
  bitfinex（V1/V2 合併版）裡都不存在，代表**目前即使啟用實盤模式，機器人到「掛單」
  這一步也一定會失敗**——已列入下方待辦，尚未動手修
- 決策：使用者認為短時間內連續三次撞到 ccxt 版本相關隱藏 bug
  （`ccxt.bitfinex2` 移除、`fetch_balance` 查錯錢包/格式對不上、這次的
  `cancel_active_offers`），要求先暫停繼續開發功能，徹底調查 ccxt 這個第三方套件在
  Bitfinex funding 功能上的可靠性、決定往後統一怎麼呼叫 API，調查有結論才繼續
  （詳見 TASKS.md「🔴 下一步・最高優先」）
- 下一步：**下一輪工作優先且唯一要做的事，是完成 ccxt 可靠性調查**（含盤點
  `exchange_client.py` 各方法目前用的是統一方法還是 raw API、修正 `create_loan_offer()`、
  評估是否整支改走 raw API 或完全繞開 ccxt），有結論後記錄成 DECISIONS.md 新決策，
  才能繼續 M2 其餘項目（只補掛差額、spread、`maxtolend`）

### 本次（ccxt 可靠性調查，分支 `fix/m1-frr-and-loop`）
- 完成：ccxt 對 Bitfinex funding 的可靠性調查——讀 ccxt 4.5.64 的 `bitfinex.py`／
  `abstract/bitfinex.py` 原始碼、全套件搜尋、比對 Bitfinex 官方 REST 文件（19 個
  funding 端點），逐一比對 `exchange_client.py` 每個方法的呼叫方式與官方規格，寫成
  `.project-docs/CCXT_BITFINEX_API_INVESTIGATION.md`
- 關鍵結論：`create_funding_offer`／`fetch_funding_offers` 這組「統一方法」在 ccxt 裡
  從未被任何交易所實作過（非版本移除），`create_loan_offer()` 原本的 `hasattr()` 判斷式
  必定每次都失敗；已改走 raw API 的 `get_frr()`／`cancel_active_offers()` 從未出過問題
- 決策：使用者確認 4 項決定，記錄為 DECISIONS.md D010——(1) 保留 ccxt、只用 raw API，
  不自行改寫 REST client；(2) `create_loan_offer()` 用 `type="LIMIT"` 固定利率；
  (3) `cancel_active_offers()` 維持查詢+逐筆取消；(4) `test_connection()` 補上
  `type="funding"`
- 完成：依決策修正 `modules/exchange_client.py` 的 `create_loan_offer()`（改呼叫
  `private_post_auth_w_funding_offer_submit`，解析回應信封的 STATUS／FUNDING_OFFER_ARRAY）
  與 `test_connection()`（`fetch_balance()` 補 `type="funding"`）
- 驗證：`py_compile` 通過；用 mock 過的假 exchange 物件測試 `create_loan_offer()` 三種情境
  （成功掛單、Bitfinex 回報 ERROR、速率限制轉 `RetryableError`），全部通過
- 下一步：M2 剩餘項目——策略層補「只補掛差額」、多筆階梯利率（spread）、`maxtolend` 風控上限；
  另注意調查過程中發現 `cancel_active_offers()` 目前未被 `main.py` 呼叫，補「只補掛差額」邏輯
  時要一併決定何時呼叫

### 本次（M2 收尾：掛單更新機制、spread、maxtolend，分支 `fix/m1-frr-and-loop`）
- 釐清：原需求「只補掛差額，避免重複掛出已成交部分」的前提有誤——Bitfinex funding 錢包的
  `free` 本來就已扣除掛單中與已放貸出去的金額，`get_available_balance()` 取的正是 `free`，
  所以「重複掛出已成交部分」不會發生。實質問題是**未成交舊掛單的利率會落後市場**，
  資金卡在不可能成交的單子上空轉
- 完成：與使用者討論三項設計細節後定案（記錄為 DECISIONS.md D011）：
  掛單更新採「每輪全取消重掛」（非混合式偏離判斷）、spread 用百分比遞增（非固定增量）、
  maxtolend 先做單輪量控版（不查已放貸部位）
- 完成：`main.py` 的 `run_once()` 流程改為 cancel → settle 等待 → balance → frr → plan →
  offer → notify，`cancel_active_offers()` 從此真正被主迴圈呼叫；新增
  `engine.cancel_settle_seconds`（預設 3 秒，僅在真的取消到掛單時才等待），因為 Bitfinex
  取消掛單是非同步的，回應 SUCCESS 不代表餘額已釋放
- 完成：`modules/lending_strategy.py` 的 `build_offer_plan()` 重寫，拆出四個私有方法——
  `_apply_lend_limit()`（maxtolend 縮量）、`_resolve_spread_count()`（依單筆最小量自動降階）、
  `_split_amount()`（均分、向下取到分位避免超額、餘數併入最容易成交的第一筆）、
  `_resolve_duration()`（逐筆判斷天期，高階鎖 30 天、低階維持 2 天）
- 完成：`config.yaml` 新增 `min_loan_size_usd`／`spread_count`／`spread_step_pct`／
  `max_to_lend_usd`／`max_percent_to_lend`／`engine.cancel_settle_seconds`；移除
  `split_threshold_usd`（原「超過 300 才拆單」的語意已被 spread 自動降階規則等價涵蓋）
- 驗證：`py_compile` 通過；策略層 11 項情境全部通過（餘額低於門檻不掛單、餘額剛好等於門檻
  視為可掛單、344.12 自動從 3 筆降為 2 筆、餘數正確併入第一筆、高階利率突破暴利閾值時天期
  分歧為 [2, 2, 30]、FRR 近乎 0 時底價被 `minimum_rate` 墊住、兩種 maxtolend 上限各自縮量
  與並存時取較嚴格者、上限壓到低於單筆最小量時不掛單、`spread_count=1` 退回單筆全下）；
  `run_once()` 取消重掛流程 4 項情境通過（呼叫順序正確、無舊掛單時不等待、取消後餘額不足
  時跳過本輪且不掛任何單、settle 秒數可設 0）；以 `interval_seconds: 1` 實跑 `main.py`
  確認多輪常駐正常；CI smoke test 同一段程式碼本地重跑通過
- 下一步：**M2 已全數完成**，進入 M3（資料與可觀測）——建立 `db/`（SQLite WAL，記錄
  `loan_offers`／`earnings_daily`／`bot_state`）、`logger` 改 `RotatingFileHandler`、
  建立 `api/rate_limiter.py` 的 `with_retry` 指數退避、補 heartbeat 與連續失敗告警

### 本次（分支重整與合併進 main，分支 `feature/m2-strategy-and-risk`）
> 更正：上方三筆條目標註的分支 `fix/m1-frr-and-loop` 是當時的工作分支；經本次重整後，
> M2 相關 commit（`cancel_active_offers`、`create_loan_offer`、spread／maxtolend／取消重掛）
> 實際都落在 `feature/m2-strategy-and-risk` 分支上並由該分支合併進 main。
> 依 append-only 原則不回頭改寫舊條目，於此註明。

- 起因：使用者指出 M1 與 M2 的工作混在同一條分支（`fix/m1-frr-and-loop`）上，要求改成
  「先把 M1 合併進 main，再開新分支做 M2」，避免兩個 milestone 的 commit 難以分辨。
  當下 M2 收尾的改動尚未 commit，仍在工作區，因此來得及分開
- 完成：`git stash` 暫存 M2 改動 → 合併 M1 進 main → 從 main 開
  `feature/m2-strategy-and-risk` → `stash pop` 還原 → commit
- 意外：推送時發現遠端 main 已由 GitHub PR #5 合併過 `fix/m1-frr-and-loop`，但**該 PR 只
  帶進 `9bb7027`**（get_frr + 主迴圈），並未包含事後才 push 的 `479a6e2`
  （`cancel_active_offers`）與 `e942310`（`create_loan_offer`）——後兩者在 TASKS.md 裡
  本來就列在 M2 底下，因此把它們歸進 M2 分支反而讓 M1／M2 分界更準確
- 完成：因 M2 分支尚未推送，以 `git rebase --onto a247b0c 9bb7027` 把它重整到遠端 main
  （PR #5 的合併點）之上，捨棄本地重複的 M1 合併 commit；重整前後以 `git diff` 比對確認
  **內容零差異**，並在每次分支切換後重跑驗證
- 完成：`main` 以 `--no-ff` 合併 M2 分支（`e17742b`），推送 `main` 與
  `feature/m2-strategy-and-risk`；最終歷史為 M1 一條分支、M2 一條分支各自合併，
  `git stash list` 已清空無遺留
- 決策：把此分支流程記錄為 DECISIONS.md D012，讓 M3、M4 自動沿用
- 待處理（使用者端）：`fix/m1-frr-and-loop` 分支已是完成後的殘留（其唯一未推送的 commit
  內容已以 rebase 後的形式進入 main），可考慮刪除；另 git 未設定 `user.name`／`user.email`，
  所有 commit 作者皆為 `shuyu <shuyu@localhost.localdomain>`，GitHub 可能無法關聯到帳號
- 下一步：進入 M3，依 D012 從 main 開 `feature/m3-data-and-observability` 分支

## 2026-07-27

### 本次（M3 資料與可觀測，分支 `feature/m3-data-and-observability`）
- 前置：依使用者要求先做完整分析與計畫再動手；同時設定 git `user.name`／`user.email`
  為 `Chen-shuyu` / `suyuchen322@gmail.com`，解掉 PROGRESS 先前記錄的「commit 作者是
  `shuyu@localhost.localdomain`、GitHub 關聯不到帳號」問題
- 完成：與使用者確認 4 項設計選擇並記錄為 DECISIONS.md D013——日誌改固定檔名輪替、
  掛單刻意不重試、`earnings_daily` 先建表不填、告警只在跨門檻與恢復時各送一次
- 完成：`utils/logger.py` 改 `RotatingFileHandler`（預設單檔 10MB、保留 5 份），移除
  `logger.py` 與 `start.sh` 兩處的檔名時間戳邏輯；補 `debug()`／`exception()` 方法
- 完成：新增 `api/rate_limiter.py`（`RetrySettings` + `with_retry` 指數退避）。原本五個
  交易所方法只把 ccxt 例外轉成 `RetryableError` 就往外拋，**完全沒有重試**，一次網路抖動
  就整輪跳過。decorator 攔的是分類後的 `RetryableError` 而非 ccxt 原始例外，因此每個方法
  只要加一行、內部邏輯不動；`create_loan_offer()` 刻意不套（掛單不冪等，見 D013）
- 完成：新增 `db/models.py`／`db/repository.py`（SQLite WAL + `synchronous=NORMAL`），
  三張表 `loan_offers`／`earnings_daily`／`bot_state`。`loan_offers` 主鍵改用自增序號、
  交易所 ID 另存可為 NULL 的 `offer_id`，因為 dry-run 與掛單失敗都拿不到交易所 ID 但同樣
  要留痕；`bot_state` 用 `CHECK (id = 1)` 從結構上保證單列
- 完成：`main.py` 的 `run_once()` 逐筆落帳（成功走 `record_offer()`、失敗走
  `record_offer_failure()`），結束時寫 `bot_state`；兩條略過路徑也照樣寫狀態，因為機器人
  是活著且判斷正確的，心跳不該因略過而中斷。新增 `FailureTracker` 處理連續失敗告警，
  `main()` 補 `try/finally` 關閉 DB 連線
- 完成：連帶修正三處部署／CI 缺口——`.gitignore` 補 `data/` 與 `*.sqlite3` 系列
  （原本完全沒排除，DB 檔會被 commit 進 git）、`podman run` 與 `docker-compose.yml` 補掛
  `/app/data` volume（否則每次重新部署 SQLite 紀錄就歸零）、CI smoke test 補 repository
  參數並加上落帳與心跳的斷言
- 驗證：`py_compile` 全數通過；logger 輪替 4 項（檔數上限、單檔大小、重啟沿用同組檔案、
  `exception()` 帶堆疊）；`rate_limiter` 8 項（首次成功不退避、中途恢復、重試耗盡後拋出、
  `max_delay` 封頂、`FatalError` 不重試、`max_attempts=1` 停用、設定載入、確認
  `create_loan_offer` 未被包上重試）；資料層 10 項（目錄自動建立、WAL 生效、三張表、
  重複初始化冪等、成功／dry-run／失敗三種落帳、收益 upsert 累加、`bot_state` 單列限制、
  WAL 下讀寫並行）；`run_once` 與告警共 32 項情境；以 `interval_seconds: 1` 實跑 5 輪並以
  SIGINT 優雅結束，確認 DB 落帳 10 筆、心跳與 `last_frr` 正確；CI smoke test 本地重跑通過
- 遇到的問題：驗證過程中有兩次是**測試腳本自己寫錯**而非程式有問題——一次是斷言 log 內容
  時沒考慮訊息已被輪替到 `.1` 檔，一次是刻意觸發 `IntegrityError` 後沒 rollback，導致後續
  `PRAGMA wal_checkpoint` 撞到鎖。修正測試後皆通過
- 流程更正：原先依 D012 在本地做了 `--no-ff` 合併進 main，使用者指正應改走
  **push 分支 → 開 GitHub PR → 由 PR 合併**的流程。因該合併尚未推送，以
  `git reset --hard origin/main` 退回即可，分支 commit 完好無損；記錄為 DECISIONS.md D014。
  過程中還犯了一個錯：退回後 HEAD 停在 main，卻直接編輯 DECISIONS.md，等於改到 main 的
  工作區而非分支，還原後切回分支才重做——已一併寫進 D014 的踩坑紀錄
- 一併更正 D012 的踩坑紀錄：原本寫「GitHub PR 只涵蓋建立 PR 當時的 commit，事後 push 的
  不會被納入」，這個說法不正確。PR 追蹤的是 head 分支最新狀態，開啟期間再 push 的 commit
  會被納入；PR #5 少帶 commit 的真正成因是那兩個 commit 在合併當下還沒推到遠端
- 下一步：**M3 已全數完成**，進入 M4（架構重構、測試與部署）——依 ARCHITECTURE.md 完成
  `config/api/strategies/core/db/notify/utils` 分層搬遷、建立 `tests/` 三層測試、收斂
  Podman 部署、最後才做 LINE Messaging API（仍卡在使用者尚未申請 Channel 憑證）

## 2026-08-01

### 本次（M4 測試套件，分支 `test/m4-test-suite`）
- 前置：先確認 M3 的實際合併狀態。對話中一度依本地快取的 `origin/main` 判斷「M3 尚未合併」，
  經使用者質疑後 `git fetch` 才發現本地落後 7 個 commit——**M3 早已由 PR #6 合併進 main**
  （合併點 `6497d54`）。依 D012 的要求以 `git merge-base --is-ancestor` 逐一驗證 M3 分支的
  6 個 commit 全數在 `origin/main` 內。教訓：判斷分支狀態前一定要先 `git fetch`，
  本地的 `origin/*` 只是上次同步時的快照
- 完成：與使用者確認 M4 的三項做法——M4 拆成 3~4 條子分支（不套用 D012 的「一 milestone
  一分支」）、先補測試再做搬遷、整合測試打 Bitfinex 公開唯讀端點且連不上時 skip。
  記錄為 DECISIONS.md D015
- 完成：本機同步 main 至 `6497d54` 後開出 `test/m4-test-suite`
- 完成：建立 `tests/` 三層測試共 227 項，全數通過（`pytest.ini` 以 `pythonpath = .`
  解決 import，並定義 `live` marker 供離線執行 `-m "not live"`）：
  - `tests/unit`（8 個檔）：策略層門檻／階梯利率／筆數降階／金額拆分／天期／風控上限、
    退避重試與「哪些方法刻意沒有重試」的界線、資料層三張表與 WAL、設定與 secrets 解析、
    日誌輪替上限、交易所客戶端的 ccxt 例外分類與 V2 陣列解析
  - `tests/functional`（2 個檔）：`run_once()` 的完整巡檢流程（取消→查餘額→掛單→落帳→通知）、
    兩條略過路徑仍寫心跳、掛單中途失敗要先落帳再往外拋；`FailureTracker` 的告警去重與恢復
  - `tests/integration`（2 個檔）：dry-run 端到端（真設定檔＋真 SQLite＋真日誌）、
    Bitfinex 公開端點的回應格式守門
- 完成（缺陷修正）：測試抓到 `upsert_daily_earning()` 的實際缺陷——`db/models.py` 把
  `principal_avg` 宣告為 `NOT NULL`，但函式簽章預設 `None` 且 ON CONFLICT 用了
  `COALESCE(excluded.principal_avg, ...)`，原意明顯是「傳 None 保留舊值」。NOT NULL 會在
  衝突解析之前先擋下，導致**首次插入與後續累加兩條路徑都必定 IntegrityError**，整條 None
  路徑從來沒能用過。因尚無任何 DB 檔存在（本機與部署目錄都沒有），直接改 DDL 為
  `principal_avg REAL`，遷移成本為零。已補上具名的回歸測試
- 完成（CI 缺口三項）：`pytest tests/unit -q || true` 的 `|| true` 拿掉——有測試卻擋不住
  壞掉的程式碼等於白寫；新增 `requirements-dev.txt`（`-r requirements.txt` + pytest），
  取代 workflow 裡臨時的 `pip install pytest`；把內嵌在 workflow 裡的 heredoc smoke test
  收斂進 `tests/integration/test_dry_run_cycle.py`，驗證內容相同但改得動、看得懂
- 驗證：三個 CI 步驟的指令逐一本機實跑（`tests/unit tests/functional` 208 項、
  `tests/integration -m "not live"` 13 項、`tests/integration` 19 項含實連 Bitfinex）；
  以 `yaml.safe_load` 確認 workflow 語法正確；把 ccxt 的 public API host 指向不可達位址，
  確認拋的是 `ccxt.NetworkError`（會被 fixture 攔下轉 skip），CI 不會因外部服務抖動變紅燈
- 遇到的問題：9 個日誌測試一開始全失敗。原因是 pytest 8.4 起會對 `propagate=False` 的
  logger 直接掛上 `LogCaptureHandler`，而 `BotLogger` 的邏輯是「已有 handler 就直接返回」，
  兩者相遇讓測試裡的 `BotLogger` 一個 handler 都不掛。這是測試框架行為而非程式缺陷，
  改以 `make_logger` fixture 在每次建立前即時清空共用 logger 解決
- 下一步：推送分支並開 PR 合併進 main；之後進 M4 第二條子分支（依 ARCHITECTURE.md 做
  `strategies/`、`core/`、`notify/` 的分層搬遷），有這 227 項測試當回歸保護

### 本次追加（部署修正，分支 `deploy/m4-podman`）
- 背景：`test/m4-test-suite` 由 PR #7 合併進 main（合併點 `e798f0c`，三個 commit 全數驗證
  在 main 內）後，main 的 CI 中 `測試階段`／`整合/系統測試` 皆通過，但 `容器化部署階段`
  以 exit code 125 失敗
- 完成：診斷出根因為 **podman 的 bind mount 不會自動建立主機端目錄**（docker 會），
  `/workspace/deploy/active-bots/ShuyuLendingBot/data` 從未在主機上建立過。該 volume 是
  M3 的 `451da1d` 加入的，本次測試 PR 完全沒有動到 deploy job——也就是說 **PR #6（M3）
  合併時部署就已經失敗，只是當時沒有注意到**
- 完成：在 workflow 的 `podman run` 之前加一步 `mkdir -p` 建立 `logs/` 與 `data/`。
  選 workflow 內建立而非手動在主機建一次，是為了讓主機重建或換機時自動成立
- 驗證：在 runner 主機上以相同掛載參數重現同一則 `statfs ...: no such file or directory`；
  執行 mkdir 後再跑一次即通過，並確認 `/app/data` 在容器內可寫（rootless podman 的 UID
  映射不影響寫入）；另以暫存目錄實跑映像一輪，確認 dry-run 巡檢掛出 2 筆、SQLite 落帳 2 筆、
  `bot_state` 心跳與 `last_frr` 正確——掛出的 172.06 × 2 與利率 0.0004／0.00046 和單元測試
  算出的預期值完全一致
- 一併發現（尚未處理，留給本分支的下一個 PR）：
  - **機器人自 2026-07-26 之後就沒有部署成功過**，`podman ps -a` 為空
  - `podman run` 完全沒有 `--restart` 參數，容器崩潰後不會自己起來；而
    `docker-compose.yml` 設的是 `restart: unless-stopped`，兩邊策略不一致
  - 部署目錄裡沒有 `secrets.env`。目前 `dry_run: true` 不受影響，實單前必須補上
- 下一步：推送並開 PR 讓 main 的 CI 轉綠；之後在同一條分支處理 restart 策略、
  容器 healthcheck、`FatalError` 與自動重啟的衝突

## 2026-08-02

### 本次（部署修正驗收與文件同步，分支 `docs/sync-m4-deploy`）
- 確認：`deploy/m4-podman` 的修正已由 **PR #8 合併進 main**（合併點 `6983394`），
  兩個 commit 依 D012 逐一比對確認都在 `origin/main` 內；PR 的三個 job 全部通過
- 確認：**部署真的成功了，機器人已恢復常駐運行**。容器 `shuyu-lending-bot` 自
  2026-08-01 22:27 起持續運行約 17 小時，`bot_state` 顯示：
  - `last_run_at` = 2026-08-02T07:37:34+00:00（心跳正常）
  - `consecutive_failures` = 0
  - `last_action` = 「掛出 2 筆掛單，合計 344.12 USD」
  - `loan_offers` 累積 208 筆（全為 `dry_run`），約 104 輪巡檢，與 600 秒間隔相符
- 確認：M3 的固定檔名輪替在正式環境確實生效，`logs/bfx_lending_bot.log` 正常寫入。
  目錄下仍留有 M3 之前產生的一批帶時間戳舊檔（`bfx_lending_bot_2026*.log`），
  已是歷史殘留、不再增加
- 新發現（尚未處理）：**`podman logs shuyu-lending-bot` 完全沒有輸出**。容器的
  log driver 是 `journald`，rootless 環境下實際取不到內容，導致 CI deploy job 最後
  那個「取得最近容器日誌」步驟等於拿不到東西。要看日誌只能讀掛載出來的檔案。
  已列入 TASKS.md 的 `deploy/m4-podman` 待辦
- 流程更新：使用者指示「PR 沒問題且已順利合併進 main 後，一律切回 main」，
  記錄為 DECISIONS.md D014 的補充步驟；同時寫入 `.ai-brain/CORE.md` 作為跨專案慣例
- 下一步：`deploy/m4-podman` 的剩餘項目（容器重啟策略、healthcheck、`FatalError`
  與自動重啟的衝突、podman logs 取不到內容），以及 `refactor/m4-layering` 分層搬遷

### 本次追加（容器可靠性收尾，分支 `deploy/m4-podman-hardening`）
- 背景：機器人自 PR #8 起已能常駐運行，但等於沒有安全網。上一段列出的四個剩餘項目
  彼此牽動（重啟策略 ↔ 致命錯誤的退出方式 ↔ 健康檢查），一次收斂成 DECISIONS.md D016
- 完成：`podman run` 加上 `--restart=on-failure:3`。原本完全沒有 restart 參數，
  崩了就永遠躺平；直接用 `unless-stopped` 又會和「致命錯誤直接退出」變成無限重啟迴圈，
  因此取次數上限這個中間解
- 完成：`main.py` 離開碼語意化為 `EXIT_OK=0` / `EXIT_UNEXPECTED=1` / `EXIT_FATAL=2`，
  並在三條退出路徑（啟動檢查失敗、`FatalError`、未預期例外）退出前都先把原因寫進
  `bot_state.last_action`。未預期的例外原本只會噴 traceback 到 stderr，而這個環境的
  容器 stderr 拿不到，等於崩潰現場整個消失；現在改成寫進日誌檔與 DB，兩者都掛在主機上
- 完成：容器日誌驅動由 `journald` 改為 `k8s-file`（`--log-opt max-size=10mb`），
  CI 的「取得最近容器日誌」改讀掛載出來的 `logs/bfx_lending_bot.log`，
  `podman logs` 降為備援（檔案 30 秒內仍是空的才退回去用）
- 完成：新增 `scripts/healthcheck.py` 與容器 `--health-*` 參數。只讀
  `bot_state.last_run_at` 判斷心跳是否過期（門檻 = 巡檢間隔 × 3 + 60 秒），
  一律以 SQLite 唯讀模式開啟——健康檢查不能像 `Repository` 那樣順手建目錄建表，
  否則 DB 掛載掉了反而會被檢查本身補回去，真正的問題就被蓋掉
- 完成：`docker-compose.yml` 的 `restart` 由 `unless-stopped` 改為 `on-failure`，
  並補上同一支腳本的 healthcheck，讓本機測試與正式部署行為一致
- 完成：測試從 227 項增加到 236 項（`tests/unit/test_healthcheck.py` 22 項、
  `tests/functional/test_main_exit_codes.py` 6 項；`scripts/` 補 `__init__.py`
  與其他套件目錄一致，並把 `scripts/healthcheck.py` 加進 CI 的語法檢查清單）
- 完成：清掉兩處 `logs/` 底下 M3 之前產生的帶時間戳舊檔（部署目錄 7 個、專案目錄 4 個），
  刪前確認內容全是 dry-run 常規巡檢、無任何 ERROR/CRITICAL；固定檔名的
  `bfx_lending_bot.log` 保留
- 驗證（實際跑 podman，不是只看設定檔）：
  - 以測試映像另起 `bot-verify-a`：`podman ps` 顯示 `Up (healthy)`，
    `podman inspect` 確認 `on-failure`／上限 3 次／`k8s-file`；**`podman logs` 終於有內容**，
    與掛載出來的日誌檔一致；容器內執行 healthcheck 回 `healthy` 離開碼 0；
    DB 心跳、`last_frr`、掛單筆數皆正常
  - 從外部送 `podman kill --signal=STOP` 凍結主行程，模擬「行程活著但不巡檢」：
    09:03:56 凍結 → 09:06:16 轉 `unhealthy`，輸出為「距離上次心跳已 140 秒，超過上限 120 秒」，
    與設計的門檻一致（該次測試 interval 設 20 秒，故上限為 120 秒）
  - 另起 `bot-verify-b` 以 `dry_run: false` 且無金鑰啟動，必定啟動檢查失敗：
    **離開碼 2、重啟 3 次後停止**，確認不會無限重啟
  - 驗證完把兩個測試容器與測試映像都刪掉，正式容器 `shuyu-lending-bot` 全程未被動到
- 注意：正在運行的正式容器仍是舊參數（無 restart、journald），**本 PR 合併後 CI 重新部署
  才會套用**；屆時要再確認一次 `podman ps` 顯示 healthy、`podman logs` 有內容
- 下一步：推送分支開 PR；之後是 `refactor/m4-layering` 分層搬遷
