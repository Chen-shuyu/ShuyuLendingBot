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

### 本次追加（PR #10 合併後驗收與部署盤查，分支 `docs/m4-deploy-audit`）
- 確認：`deploy/m4-podman-hardening` 已由 **PR #10 合併進 main**（合併點 `9a12e40`），
  兩個 commit 依 D012 以 `git merge-base --is-ancestor` 逐一確認都在 `origin/main` 內；
  CI 三個 job 全部通過
- 確認（有效的部分）：正式容器已套用新參數——`on-failure`（上限 3 次）、`k8s-file`、
  健康狀態 `healthy`。**healthcheck 確實在運作**：每 60 秒一次、累積 5 筆全為離開碼 0，
  訊息「心跳正常，距離上次巡檢 183 秒（上限 1860 秒）」。機器人本身正常：
  心跳 09:45:35、連續失敗 0、`loan_offers` 累計 234 筆
- **發現（重大）**：`podman logs shuyu-lending-bot` **仍然完全沒有內容**。往下追查發現
  **容器的 conmon 行程不存在**——`podman inspect` 記錄的 conmon PID 查無此行程，
  整台機器上沒有任何 conmon，容器主行程的父行程已變成 `systemd --user`（被認養）。
  容器建立於 17:35:35、runner 的 deploy job 於 17:35:42 完成，時間吻合
- 驗證方式（對照實驗，可重現）：起兩個測試容器，指令都是「印一行 → 睡 15 秒 →
  以離開碼 1 結束」，都帶 `--restart=on-failure:3 --log-driver=k8s-file`，
  其中一個在啟動後 `kill -9` 掉它的 conmon：
  - conmon 活著：容器退出後**會**重啟（RestartCount=1），`podman logs` 有內容
  - conmon 被殺：**完全不重啟**（RestartCount=0），`podman logs` 停在被殺那一刻，
    而且 `podman ps` 對一個主行程早已不存在的容器仍顯示 `running`
- 結論：PR #10 的四項修改中，**離開碼語意化與 healthcheck 兩項有效**，
  **自動重啟與容器日誌兩項在目前的部署方式下不會生效**。程式碼與參數都正確，
  卡在部署層。這**不是 PR #10 改壞的**——PR #8（M3）那版同樣由 CI 部署、同樣沒有
  conmon，所以 `podman logs` 自 M3 起就一直是空的、重啟策略也從來沒生效過
- 一併發現：`loginctl show-user shuyu` 顯示 `Linger=no`，所有登入 session 結束後
  `systemd --user` 會停止，掛在它底下的容器會一起消失
- **被推翻的推論（記下來免得下次又繞回去）**：曾懷疑「conmon 不在，沒人讀 stdout pipe，
  寫滿 64KB 後 Python 會阻塞、機器人會卡死」。實測灌 200KB 輸出後測試容器仍正常跑完
  並以離開碼 0 結束，**不成立**
- 另檢查、確認沒問題的：workflow 中等待日誌檔的迴圈在 GitHub Actions 的 `bash -e` 下
  不會提前退出（實測 `[ -s "$f" ] && break` 在 `&&` list 中不觸發 `set -e`）；
  healthcheck 的門檻算式與實際輸出相符；healthcheck 唯讀開啟 DB 無副作用；
  236 項單元／功能測試與 19 項整合測試全數通過
- 程式碼層另外盤到三項（都不緊急，已列入 TASKS.md A3～A5）：`main.py` 三條退出路徑
  在落帳失敗時會蓋掉原始錯誤；DB 相對路徑的解析主程式相對 cwd、healthcheck 相對專案根目錄，
  兩邊不一致；`config.yaml` 沒有列出 `engine.health_max_silence_seconds`
- 文件更正：D016 的第 3 點根因判斷錯誤（原歸因為「journald 在 rootless 下拿不到」），
  已在該條後補「⚠️ 2026-08-02 驗收後更正」段；CHANGELOG.md 的 Fixed 移除兩條不成立的
  宣稱、Known Issues 補回四條；PLAN.md 的 M4 部署狀態由完成改為部分完成
- 教訓：當時的驗證用的是**自己手動起的容器**，而問題只發生在 **CI 起的容器**上，
  驗證環境與故障環境根本不同，卻當成修好了。往後部署層的修正要在真正的部署路徑上驗收
- 下一步（依 TASKS.md 排序）：A2 開 linger → A1 容器生命週期改由 systemd 管理
  → A3～A5 程式碼層三項 → 之後才回到 `refactor/m4-layering`。
  **本次只做盤查與文件，沒有動任何程式碼與正式容器**

### 本次追加（A1／A2：容器生命週期改由 systemd 管理，分支 `deploy/m4-systemd-lifecycle`）
- 起點：確認 `docs/m4-deploy-audit` 已由 **PR #11 合併進 main**（合併點 `2189715`），
  以 `git merge-base --is-ancestor dddc4a3 origin/main` 驗證後切回 main 並 fast-forward，
  再從最新的 main 開本分支
- 動手前先查現況，確認上一輪盤查的結論仍成立：`Linger=no`、整台機器沒有任何 conmon、
  `~/.config/containers/systemd/` 不存在。正式容器是 PR #11 合併觸發 CI 重新部署後
  於 18:05 起的，一樣沒有 conmon——問題與部署次數無關，是部署**方式**的問題
- 完成 **A2**：`loginctl enable-linger shuyu`，確認 `Linger=yes`
- 完成 **A1**：容器生命週期改由 systemd --user 的 Quadlet 單元管理（見 DECISIONS.md D017）
  - 新增 `systemd/shuyu-lending-bot.container` 並納入版控。CI 每次部署複製到
    `~/.config/containers/systemd/`，主機上那份視為產物
  - CI deploy job 改寫：移除「停止並移除舊容器」「準備主機端掛載目錄」「啟動 Podman 容器」
    三步，改為「安裝／更新 Quadlet 單元」「重新啟動服務」。掛載目錄的 `mkdir -p`
    移進單元的 `ExecStartPre`，開機自動啟動與非 CI 觸發的重啟才會成立
  - 移除 podman 端的 `--restart=on-failure:3`，節流改用 `Restart=on-failure` +
    `StartLimitIntervalSec=1800` / `StartLimitBurst=4`
  - 新增 `RestartPreventExitStatus=2`：systemd 看得到離開碼，`EXIT_FATAL` 直接不重啟。
    D016 當時寫「restart policy 看不到離開碼」，換到 systemd 後這個限制就消失了
  - CI 新增「驗證容器生命週期真的由 systemd 接管」步驟：斷言服務 active、conmon 存在、
    `podman logs` 有內容，任一不成立就紅燈
- 驗證（記取 D016 的教訓，這次先做對照實驗，再在正式容器上驗收）：
  - 測試用 Quadlet 單元「印一行 → 睡 N 秒 → 以指定離開碼結束」：
    離開碼 1 → `ExecMainStatus=1`，重啟 4 次後觸及 StartLimitBurst 停在 failed；
    離開碼 2 → `ExecMainStatus=2`、`NRestarts=0`，完全不重啟。
    順帶證實離開碼確實會透過 `--sdnotify=conmon` 傳回 systemd
  - **直接針對根因的對照實驗**：用 `systemd-run --user --scope` 建一個模擬 CI job 的
    scope，在裡面 `systemctl --user start` 服務，再把整個 scope 的行程樹 SIGKILL。
    結果 conmon 存活、容器續跑，cgroup 是
    `user@1000.service/app.slice/shuyu-lending-bot.service/runtime`——與 job 完全脫鉤
  - 正式容器實際接管後：服務 active、conmon PID 存在、**`podman logs` 終於有內容**
    （自 M3 以來第一次）、podman 端重啟策略為 `no`（已交給 systemd）、
    `Up (healthy)`、`podman healthcheck run` 離開碼 0、DB 心跳與 `loan_offers`
    累計 274 筆都正常
  - 測試 236 項單元／功能 + 19 項整合全數通過；workflow YAML 另以 `yaml.safe_load` 驗過
- 過程中修掉自己寫錯的一處：CI 驗證步驟原本用 `{{.ConmonPid}}` 取 conmon PID，
  podman 5.8 的正確欄位是 `{{.State.ConmonPid}}`，前者會直接讓該步驟報錯。
  是在正式容器上實跑指令時發現的——只寫不跑就會帶著壞掉的斷言合併進去
- 依使用者指示，**A3～A5（程式碼層三項）本次不做**，已在 TASKS.md 移到
  「🟡 延後處理」段落並註明之後另開 `fix/m4-audit-findings` 一次處理。
  A6 的前提隨 A1 完成而改變（改走 systemd 表達「不健康就重啟」），維持觀察期規劃
- 下一步：推送分支開 PR；合併後確認 CI 的新驗證步驟在真正的部署路徑上是綠的。
  之後回到 `refactor/m4-layering`，或先清掉延後的 A3～A5

### 本次追加（PR #12 合併後驗收與兩項新發現，分支 `fix/m4-audit-findings`）
- 確認 `deploy/m4-systemd-lifecycle` 已由 **PR #12 合併進 main**（合併點 `4c83f73`），
  以 `git merge-base --is-ancestor 9c193ee origin/main` 驗證後切回 main 並 fast-forward
- **在真正的部署路徑上驗收（這次有做對）**：容器由 CI 於 21:25:27 重建（非手動啟動），
  **等 deploy job 完全結束之後**再檢查——conmon 仍存活，cgroup 為
  `user@1000.service/app.slice/shuyu-lending-bot.service/runtime`。舊做法下 conmon 正是
  在 job 收尾這一刻被清掉的，所以這是根因解除的直接證據。一併確認：`podman logs` 有內容、
  服務 `active`／`Result=success`／`NRestarts=0`、容器 `Up (healthy)`、podman 端重啟策略
  為 `no`、主機單元檔與 repo `diff` 一致、`loan_offers` 由 274 累積到 280（DB 跨部署保留）、
  開機自動啟動連結存在
- 驗收過程踩到的一個小坑（記下來免得重蹈）：用 `pgrep -f "Runner.Worker"` 判斷 CI job
  是否還在跑會**誤判成「還在跑」**——`-f` 比對完整命令列，而執行這個判斷的 shell 自己的
  命令列裡就含有 `Runner.Worker` 這串字，等於自我匹配。改用
  `ps -eo pid,etimes,cmd | grep -i "[R]unner\."` 才問得到正確答案。
  據此寫的 `until ! pgrep -f ...` 等待迴圈會永遠不結束
- **新發現 B1（自我修正）**：PR #12 加的那道 CI 檢查「驗證容器生命週期真的由 systemd 接管」，
  **抓不到它想抓的迴歸**。它斷言 conmon 存在與 `podman logs` 有內容，但這兩件事在舊的
  `podman run` 做法下、於 job 執行期間同樣成立——舊做法的 conmon 是 **job 收尾那一刻**
  才被清掉，而檢查跑在 job 執行期間。修法是改為比對 conmon 的 cgroup 是否屬於
  `shuyu-lending-bot.service`（這個差異在 job 執行期間就看得出來）。
  D017 已補上更正段，細節與可照抄的程式碼片段見 TASKS.md B1
- **新發現 B2**：systemd 用盡 `StartLimitBurst` 放棄重啟後，單元停在 `failed` 而
  **不會通知任何人**。不是這次改壞的（舊的 `--restart=on-failure:3` 同樣沒通知，
  只是從未真的執行過），但 D017 讓重啟第一次真的會運作，這個缺口也第一次變得有意義。
  實單前必補，見 TASKS.md B2
- **教訓**：D016 的錯是「驗證環境與故障環境不同」，B1 的錯是「**驗證時機與故障時機不同**」
  ——檢查跑在故障發生之前的時間點，所以永遠看不到故障。設計自動化檢查時，
  除了問「這個檢查會不會通過」，還要問「**如果故障真的發生了，它會不會失敗**」
- 依使用者指示開了分支 `fix/m4-audit-findings`（從 main `4c83f73`），把 A3～A5 與
  B1、B2 五項集中在這條分支處理。**本次只寫文件，沒有動任何程式碼**，
  五項的修法都已寫進 TASKS.md 的「🟡 延後處理」段落，下次可直接照做

## 2026-08-09 —— 修好 CI 的容器生命週期斷言（分支 `fix/m4-ci-lifecycle-assertion`）

### 起點：PR #13 合併後 deploy job 紅燈
- 開工前先做分支盤查（`git fetch` 後逐一比對）：13 條本地分支中 11 條都已推遠端且
  以 `git merge-base --is-ancestor` 驗證確實在 main 內。兩個例外都不擋事——
  `fix/m4-audit-findings` 是當時的工作分支（1 個純文件 commit 未推）；
  `fix/m1-frr-and-loop` 是殘留舊分支，實查後確認它「有而 main 沒有」的只剩 M2 之前的
  舊策略程式（已被階梯利率取代），三個 raw API 實作與 D010 全都在 main 內，沒有漏掉的工作
- 依使用者選擇：文件 commit 先走自己的 PR（#13）合併進 main，再從最新 main 開新分支，
  與 PR #9、#11 的做法一致。合併後以 `git merge-base --is-ancestor 8814cd0 origin/main`
  實際驗證（不只看 PR 顯示已合併）
- PR #13 合併觸發部署，deploy job 在「驗證容器生命週期真的由 systemd 接管」失敗

### 根因：斷言讀錯了管道（B3）
- **不是 systemd 接管失敗**。實查：conmon PID 4185319 存在、cgroup 為
  `user@1000.service/app.slice/shuyu-lending-bot.service/runtime`、`NRestarts=0`、
  `podman logs` 有 11 行內容、容器 `Up (healthy)`——三個前提全部成立
- 真正的原因是檢查本身：機器人日誌走 **stderr**（`logging.StreamHandler()` 不帶參數，
  Python 預設 stderr），程式無任何 `print()` 所以 stdout 恆空，而檢查用
  `$(podman logs ... 2>/dev/null)` 只捕捉 stdout 又丟掉 stderr。**親手扔掉自己要找的東西**
- 現場驗證：同一個容器，`2>/dev/null` 捕捉到 0 個字元，`2>&1` 得到 11 行
- 推論並確認影響範圍：這道檢查**從加進來就不可能通過**，deploy job 自 PR #12 合併
  （8/2）以來一路是紅的。當時手動驗收看得到日誌，是因為終端機下 stderr 直接顯示在螢幕上。
  機器人本身不受影響——重啟服務在這一步之前就已完成，容器連續運行 7 天、心跳正常

### 修改內容
- **B3**：改用 `CONTAINER_LOGS=$(podman logs --tail=20 ... 2>&1)`，並同時要求 podman
  指令本身成功——否則「no such container」這類錯誤訊息會被當成「有日誌」而誤放行
- **B1**（同一個步驟，順手一起改）：conmon 的判斷從「行程存不存在」改為
  「**cgroup 是否屬於 `shuyu-lending-bot.service`**」。原本已經把 cgroup 印出來了，
  只是印給人看、沒拿去比對，補一個 `case` 判斷即可
- 刻意**不改 `utils/logger.py`**：日誌走 stderr 是 Python 的預設行為，本身沒錯，
  兩邊（`podman logs` 與掛載出來的日誌檔）都收得到。為了讓寫錯的斷言通過而改動
  機器人的輸出行為，是把因果關係倒過來

### 驗證
- 把 workflow 裡那段斷言抽出來做成可帶參數的腳本，兩個情境各跑一次：

  | 情境 | 期望 | 實測 |
  |---|---|---|
  | 正式容器（systemd 啟動） | 通過 | 離開碼 0，11 行日誌正常印出 |
  | 假容器（直接 `podman run`，模擬舊做法） | 紅燈 | 離開碼 1，被 cgroup 判斷擋下 |

- 第二個情境的關鍵：**那個假容器的 `podman logs` 是有內容的**，所以它是被「啟動方式不對」
  擋下來的，不是碰巧因為沒日誌而失敗——這正是 B1 要的鑑別力。測完已移除假容器
- workflow YAML 以 `yaml.safe_load` 驗過；完整測試套件 255 項全數通過

### 教訓與下一步
- 這是同一系列的第三條：D016 是「驗證**環境**與故障環境不同」、B1 是「驗證**時機**與
  故障時機不同」、B3 是「驗證**管道**與資料實際流經的管道不同」。三次都是同一個病——
  檢查沒有在檢查它以為在檢查的東西。往後寫自動化斷言，**一定要在故障情境下實際跑一次
  看它會不會失敗**，不能只在正常情境下看到綠燈就收工。記為 DECISIONS.md D018
- 下一步：合併後回到剩下的 A3、A4、A5、B2（B2 仍與 A6 一起設計），之後才是
  `refactor/m4-layering`

## 2026-08-09（續）—— 程式碼層三項 A3／A4／A5（分支 `fix/m4-code-audit-findings`）

- 先確認 PR #14 已合併：`git merge-base --is-ancestor 705df91 origin/main` 通過，
  main 前進到 `27e0e69`。部署後容器 `Up (healthy)`、`NRestarts=0`、conmon cgroup 正確，
  **修好的 CI 斷言在真正的部署路徑上第一次綠燈**
- **A3**：抽出 `main._record_exit_reason()`，三條退出路徑共用，落帳失敗只記日誌，
  不影響離開碼與通知。順帶把 `finally` 的 `repository.close()` 也包起來——
  `finally` 拋出的例外會取代回傳值，離開碼會直接變成 1。
  這件事在 D017 之後變得更重要：systemd 用 `RestartPreventExitStatus=2` 依離開碼
  決定要不要重啟，落帳失敗把 `EXIT_FATAL` 變成 `EXIT_UNEXPECTED` 會讓它去重啟
  一台永遠起不來的機器人
- **A4**：`db/repository.py` 新增 `PROJECT_ROOT` 與 `resolve_db_path()`，相對路徑一律
  相對專案根目錄；一併讓 `BFX_DB_PATH` 在主程式端也有最高優先權（原本只有 healthcheck
  認得，設了就兩邊分家，是同一缺陷的另一面）。
  **刻意不共用同一個函式**：healthcheck 要維持零專案相依、零副作用，
  改以測試釘住「兩邊算出的路徑必須相同」，兩支檔案的 docstring 都寫明要一起改。
  容器內行為不變（`PROJECT_ROOT` 就是 `/app`）
- **A5**：`config.yaml` 的 `engine:` 補上註解掉的 `health_max_silence_seconds` 與說明
- 測試 255 → 265 項：新增 `TestExitPathSurvivesBrokenDatabase`（4 條）與
  `TestPathResolution`（6 條，含兩條「主程式與 healthcheck 必須算出同一路徑」的斷言）
- **每一項都在故障情境下實跑驗證過**（D018 的教訓）：
  - A3：`git stash` 掉 `main.py` 的修正後重跑，4 條新測試全部失敗，還原後全過
  - A4：以 cwd=`/tmp` 實跑，修正前兩邊算出 `/tmp/data/...` 與專案目錄兩個不同位置，
    修正後一致
  - A5：確認註解狀態下門檻是預設 1860 秒，取消註解設 1200 後覆寫生效
- 過程中修掉一個既有測試的問題：`test_from_config_falls_back_to_default_path` 原本
  `monkeypatch.chdir` 後斷言相對路徑，等於釘住舊行為；改成只驗 `resolve_db_path()`
  的結果，不再實際建立 `Repository`——否則預設路徑會指向**真正的專案目錄**，
  測試會在 repo 裡留下一個 `data/lending.sqlite3`（第一次改完跑測試時真的發生了，已清掉）
- 順帶更正 `main.py` 模組 docstring 裡「節流交給 `--restart=on-failure:N`」的說法，
  該參數已於 D017 移除
- 下一步：只剩 **B2**（systemd 放棄重啟時無人收到通知，與 A6 一起設計），
  之後就是 `refactor/m4-layering`

## 2026-08-09（續）—— 失效告警 B2 與「不健康就處理」A6（分支 `deploy/m4-failure-alert`）

- 先確認 PR #15 已合併（`ac4e5a3` 在 main 內），main 前進到 `60b80bf`
- **A6 的觀察期資料**：healthcheck 自 8/2 起每 60 秒執行、連續 7 天零誤判
  （`FailingStreak=0`，容器一路 `healthy`），據此決定開啟
- **A6**：Quadlet 加 `HealthOnFailure=kill`（不是 `restart`）。`restart` 會讓 podman
  與 systemd 兩套重啟機制並存互相打架；`kill` 只負責殺掉不健康的容器，
  重啟仍然只由 systemd 負責，節流與告警自動涵蓋這條路徑
- **B2**：主單元 `[Unit]` 加 `OnFailure=`，新增 `systemd/shuyu-lending-bot-alert.service`
  與主機端腳本 `scripts/notify_failure.py`（純標準函式庫、不 import 專案模組——
  容器可能正是壞掉的那個，不能靠它報告自己死了）。CI deploy job 一併安裝這兩個檔案
- **實驗推翻了一個寫進設計裡的假設**：原本以為 `OnFailure=` 只在單元真正放棄時觸發，
  重試中途不會誤觸發，訊息因此寫死成「不會再自動重啟」。
  實測 `StartLimitBurst=3` 的單元，**告警被觸發 4 次**（重啟 0／1／2 次時各一次、
  最後放棄時一次），中途三次的訊息完全是錯的。
  改成由腳本自己查單元狀態分辨：`SubState=auto-restart` → ERROR「重試中」、
  `ActiveState=failed` → CRITICAL「已放棄」，查不到狀態時一律當成已放棄。
  查詢前等 2 秒讓狀態轉換走完，避免問到轉換前的舊狀態
- **刻意不做靜音**：多送一則「正在重試」只是稍微吵，漏掉「已經放棄」等於整個 B2 白做
- 兩個實機對照實驗（做完已清乾淨，正式服務全程 `active`、容器 `Up (healthy)`）：
  - 實驗 1（告警鏈）：觸發 4 次，3 次 ERROR + 1 次 CRITICAL，日誌與 DB 都寫入，
    **`last_run_at` 確認未被更動**（告警絕不能偽造心跳）
  - 實驗 2（A6 串接）：健康檢查失敗 → 容器被殺（**離開碼 137，不是 2**）→
    systemd 重啟 2 次 → 用盡次數停在 failed → 告警照常觸發。
    137 這點很重要：若剛好是 2，`RestartPreventExitStatus=2` 會把 A6 整個廢掉而毫無徵兆
- CI 新增「驗證失效告警已接上」步驟，三個斷言都問「systemd 眼中的實際狀態」而非
  repo 內容；`quadlet -dryrun` 另外驗過修改後的單元檔會產生正確參數
- 測試 265 → 283 項（新增 `tests/unit/test_notify_failure.py` 18 項）
- 下一步：兩輪盤查的六項缺陷全部清完，M4 只剩 `refactor/m4-layering` 分層搬遷，
  以及被憑證卡住的 LINE 通知
- 補上 **ARCHITECTURE.md** 的同步（前一個 commit 漏掉的）：新增「維運元件與主程式刻意分離」
  段落（healthcheck 在容器內、notify_failure 在容器外，兩者都零專案相依，理由是它們執行的
  時機正是東西壞掉的時候）、`scripts/` 與 `systemd/` 目錄結構、`notify_failure.py` 的模組說明、
  `resolve_db_path()` 與 healthcheck 必須一致的約束（D019）、失效處理權威唯一為 systemd
  與兩條告警管道的分工（D020）。測試數字 236 → 283。
  另修正 TASKS.md 裡 `refactor/m4-layering` 的指示：重跑的項數已過時，
  並註明兩支維運腳本刻意不參與分層搬遷
