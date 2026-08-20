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

## 2026-08-15 —— M4 分層搬遷（分支 `refactor/m4-layering`）

- 先確認 PR #16 已合併（`d00cb9d`、`27eb60f` 都在 main 內），main 前進到 `b844d49`，
  從最新的 main 開分支
- 搬遷前先跑一次基準測試：283 項全過（277 + 6 項 live），確認起點是綠的
- 用 `git mv` 搬四個檔案，保留檔案歷史：
  `modules/exchange_client.py` → `api/bitfinex_client.py`、
  `modules/lending_strategy.py` → `strategies/frr_plus.py`、
  `modules/line_notifier.py` → `notify/line_messaging.py`，`modules/` 整個移除
- 新增三個檔案：`api/base.py`（`ExchangeClient` 介面）、`strategies/base.py`
  （`Strategy` 介面 + `OfferPlan`）、`core/bot_engine.py`（`BotEngine` 與 `FailureTracker`）
- `main.py` 從 227 行縮到 60 行，只剩 bootstrap；主迴圈、`run_once()`、
  `_record_exit_reason()`、離開碼常數全部移進 `BotEngine`。**離開碼常數雖然改在
  `core/bot_engine.py` 定義，`main.py` 匯入後仍以同名存取**——systemd 的
  `RestartPreventExitStatus=2` 認的是實際回傳值，這條路徑不能有任何鬆動
- 類別更名 `LendingStrategy` → `FrrPlusStrategy`（見 DECISIONS.md D021）
- `notify/line_messaging.py` **只搬位置、不改內容**，仍打已停用的 LINE Notify 端點；
  模組 docstring 明寫這個落差，免得檔名誤導人以為 Messaging API 已經接上
- 測試同步：import 路徑全改，兩個測試檔跟著模組更名
  （`test_exchange_client.py` → `test_bitfinex_client.py`、
  `test_lending_strategy.py` → `test_frr_plus.py`）。
  `tests/functional/test_run_once.py` 加一個薄的 `run_once()` 測試輔助函式包住
  `BotEngine` 的建構，其餘測試本體一行沒動——**這樣測試本身就是「行為沒變」的證據**
- `monkeypatch` 的目標從 `main.time.sleep` 改成 `bot_engine.time.sleep`（sleep 跟著迴圈走）
- CI 的 `py_compile` 清單改成新路徑，順便補進原本漏掉的 `scripts/notify_failure.py`
  與兩個 base 檔
- 驗證：283 項測試全過（含 6 項實際連 Bitfinex 的 live 測試）、`py_compile` 全過、
  另外用暫存 DB／log 實跑 `python main.py` 一輪，確認 bootstrap 接線正確
  （啟動檢查 → 進入主迴圈 → 取消 → 查餘額 FRR → 掛兩筆 dry-run 單 → 進入睡眠）
- 下一步：M4 只剩 `feature/m4-line-messaging`，仍卡在使用者尚未申請 LINE Channel 憑證；
  小額實單的前置條件仍是使用者補上 `secrets.env`

## 2026-08-15（續）—— 金鑰檔位置與掛載強化（分支 `deploy/m4-secrets-hardening`）

- 起因是使用者問「`secrets.env` 到底放哪裡最安全、要不要用 root 建立」。盤點後
  發現兩件事：**家目錄那份其實早就存在**（07-12 建立，權限 600 正確，但四個鍵都是空值），
  而 Quadlet 掛的是**整個部署目錄**——進容器一看，`/run/secrets` 底下躺著
  `data/` 與 `logs/`，等於把完整交易紀錄放在一個叫「secrets」的目錄裡給容器讀
- 先界定威脅面再設計：`uid>=1000` 的一般使用者只有 `shuyu` 一個，root 本來就讀得到一切，
  所以「同機他人偷讀」實質不存在。真正該防的是誤入版控、容器被入侵後的橫向取得、
  備份誤打包——決策依這三項排（見 DECISIONS.md D022）
- 三項決策：金鑰唯一真實來源定為 `~/.config/bfx-lending-bot/secrets.env`（在 `/workspace`
  之外，結構上碰不到版控；且與本機直跑 `main.py` 讀同一份）、Quadlet 改掛**單一檔案**、
  金鑰一律走檔案不走 `Environment=`（後者會讓金鑰同時出現在單元檔／`podman inspect`／
  `systemctl show`／`/proc/<pid>/environ` 四個地方）
- 明確不採用的兩個選項也寫進 D022：`podman secret`（會多出第二個真實來源，
  而預設驅動的實質保護沒有比 600 的檔案好）、root 擁有金鑰檔（rootless 下容器根本讀不到，
  安全性也沒提升）
- 補一道 `ExecStartPre=/usr/bin/test -f`：掛單一檔案時來源不存在的話，podman 會自己
  建一個同名目錄頂替，程式開檔噴 `IsADirectoryError`——錯誤訊息離真正原因太遠，
  寧可當場失敗（同 `Pull=never` 的理由）
- `chmod 700 ~/.config/bfx-lending-bot`（原本 755；上層 `.config` 是 700，所以實際上
  一直擋得住，但不該依賴上層）
- 驗證：`quadlet -dryrun` 確認產生的 `podman run` 帶單一檔案的 `-v` 且無錯誤 →
  安裝單元、`daemon-reload`、重啟 → 服務 `active`、容器 5 秒內回到 `healthy` →
  容器內 `/run/secrets` 只剩 `secrets.env`（`data/`、`logs/` 已消失）→
  日誌全文搜尋金鑰樣式 0 筆 → 283 項測試維持全過
- 順帶釐清一個容易誤會的現象：容器內 `/run/secrets` 還有 `rhsm/`、`redhat.repo`、
  `etc-pki-entitlement/`，那是 **podman 在 RHEL 上預設注入的訂閱憑證**，
  與本專案的掛載無關
- **驗證重啟時抓到一個既有缺陷（B4）**：重啟會觸發一則假的「機器人啟動失敗」ERROR 告警。
  查日誌發現同樣的訊息在 08-09 22:57 與 08-15 17:26 也各有一筆，**三次都正好是重啟時刻**，
  所以不是本次改壞的。根因是 `notify_failure.py` 只分辨「重試中」與「已放棄」兩種狀態，
  重啟後單元回到 `active/running` 這第三種狀態沒有分支，落進了「重試中」的 else。
  LINE 接上之後每次部署都會推一則假警報到手機，實單前要修，已記為 TASKS.md B4
- 依使用者指示，B4 併入本分支一起修（見下段）

## 2026-08-15（續）—— B4：失效告警改三分法（同分支 `deploy/m4-secrets-hardening`）

- `notify_failure.py` 新增 `classify()`，把二分法改成三分法；第三種
  `active/running` 依 `NRestarts` 給 INFO（0 次，部署重啟造成的觸發）或
  WARNING（>0 次，確實失敗過但已恢復）。判斷順序刻意先問 `auto-restart`，
  否則重啟途中短暫的 `active` 會被誤判成「已恢復」（見 DECISIONS.md D023）
- 保留 `has_given_up()`（改成呼叫 `classify()`），既有 18 項測試一行沒改就全過
  ——這本身就是「兩條既有路徑沒被改壞」的證據
- 測試 283 → 292 項（新增 9 項：三分法各狀態、順序衝突、非數字 `NRestarts`、
  兩種新訊息的措辭與等級）
- **先反證再驗收**：用舊邏輯對同一份 `active/running` 狀態跑一次，確認它確實判成
  ERROR「啟動失敗」，證明新測試不是套套邏輯
- **實機驗證**：把新版腳本安裝到 `~/.local/share/shuyu-lending-bot/` 後重啟正式服務，
  日誌那一行從 `ERROR 放貸機器人啟動失敗` 變成
  `INFO 告警被觸發，但單元目前正常運作中`，服務 `active`、容器 `healthy`、機器人未中斷
- **驗證範圍的已知缺口（誠實記錄）**：原本要照 D020 起拋棄式單元實測
  「重試中 → 已放棄」兩條路徑，使用者當下不希望在 `~/.config/systemd/user/` 放實驗檔，
  故未做（已建的那個實驗檔當場刪除，目錄恢復原狀）。使用者選擇以單元測試
  ＋「兩條分支字串未動」作為證據直接提交
- 下一步：M4 仍只剩 `feature/m4-line-messaging`，等使用者申請 LINE Channel 憑證

## 2026-08-15（續）—— LINE Messaging API 接上，M4 完成（分支 `feature/m4-line-messaging`）

- 先確認 PR #18 已合併（`fc63f21`、`fcb0f36` 都在 main 內），main 前進到 `c43d6e7`，
  從最新的 main 開分支
- 使用者填好憑證後，先用**三個唯讀端點**驗證，不送任何訊息：`/v2/bot/info`（token 有效，
  官方帳號「Bitfinex貸款機器人」、`chatMode=bot` 代表自動回應已關）、
  `/v2/bot/profile/{userId}`（user ID 有效**且已是好友**——不是好友這個查詢會直接失敗）、
  `/v2/bot/message/quota`（`{"type":"limited","value":200}`）
- **額度數字改變了設計**：`run_once()` 結尾原本每輪 `notifier.send("已完成一輪巡檢")`，
  而巡檢間隔 600 秒 = 一天 144 輪，免費方案卻是每月 200 則——照原樣接上去**不到兩天
  就把整個月的額度用光**，之後真正的故障告警一則都送不出去。改為只寫日誌，
  通知管道只送事件（見 DECISIONS.md D024）
- `notify/line_messaging.py` 改寫為 `POST /v2/bot/message/push`：HTTP 錯誤碼一律翻成
  人看得懂的原因（403 最常見的其實是「對方不是好友」而不是權限設定）、超過 5000 字截斷、
  **永遠不拋例外也不重試**（它在致命錯誤的退出路徑上，承 D019）
- `scripts/notify_failure.py` 的 LINE 管道接上，維持**獨立實作**（只用標準函式庫）。
  自己讀 `secrets.env`——刻意不用 systemd `EnvironmentFile=`，因為每行的 `export ` 前綴
  會讓 systemd 把 `export LINE_CHANNEL_ACCESS_TOKEN` 整串當鍵名而**安靜地**解析失敗。
  **INFO 等級不推**：D023 剛修掉部署重啟的假 ERROR，不能換個管道再犯一次
- 環境變數與設定鍵改名（`LINE_NOTIFY_*` → `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_TO_USER_ID`、
  `channel` → `to_user_id`），**刻意不做向後相容**並補一條測試釘住：留著舊名只會讓人
  以為設了就有用，而舊 token 對新端點必定是 401
- **踩到一個坑並修掉**：接上之後第一次跑 `pytest`，告警腳本的測試從真實 `secrets.env`
  讀到金鑰，**實際推了 6 則訊息到使用者手機**，也吃掉當月額度 6 則。失敗方式很安靜
  ——測試照樣綠燈，只有手機會響。已在 `tests/conftest.py` 加 autouse fixture：所有測試
  一律清掉 LINE 環境變數並把 `BFX_SECRETS_FILE` 指到不存在的路徑；
  `test_notify_failure.py` 另把 `urlopen` 換成一呼叫就 AssertionError 當第二道保險。
  **刻意不做全域封鎖網路**——`tests/integration` 有 6 項刻意連 Bitfinex 公開 API 的 live 測試
- 測試 292 → 312 項（新增 `tests/unit/test_line_messaging.py` 13 項、告警腳本的
  LINE 與 `load_secrets()` 測試，並改寫兩條釘住舊行為的測試）
- **實測驗收**：兩條管道各實際送出一則測試訊息並確認送達——主程式路徑走
  `load_secrets_from_disk` + `config.yaml` 的真實接線（不是臨時 curl），
  告警腳本路徑走主機端獨立實作；INFO 等級確認略過
- **M4 四個 milestone 至此全部完成**。下一步是小額真金測試，前置條件全部在使用者身上：
  Bitfinex API Key（建立當下就關掉提現權限）、起始金額、`dry_run` 切換時機


## 2026-08-15（續）—— 首次實單：被拒單、找到金額四捨五入的 bug（分支 `fix/offer-amount-exceeds-balance`）

- PR #19（LINE）、#20（go-live）依指定順序合併，main 前進到 `b9abf94`，CI 部署完成
- **第一輪實單巡檢**：連線 ✅ → 取消 0 筆 ✅ → 餘額 160.00861413 ✅ →
  FRR 0.00032288767 ✅ → 掛單 **被拒**：
  `Invalid offer: not enough USD balance available in deposit wallet`
- **可靠性鏈按設計運作**：判為 `FatalError` → 離開碼 2 → `RestartPreventExitStatus=2`
  不重啟（避免無限迴圈燒錢）→ 停在 `failed` → `OnFailure=` 送出 CRITICAL 告警。
  事後查證 **0 筆掛單、0 筆已借出、餘額分毫未動**，資金零損失
- 根因見 DECISIONS.md D025：`_split_amount()` 先 floor 每筆、卻用 `round()` 處理餘數，
  `round(0.00861413, 2)` 進位成 0.01，總額 160.01 超出餘額 160.00861413
- 修法改用**整數分**運算（`Decimal(str(x))` 轉分、`divmod` 分配）。
  第一版只把 `round` 換成 `floor`，結果 `500.0 - 166.66*3 = 0.019999999999953`
  少算一分錢、弄壞三條既有測試——金額運算不該碰浮點誤差
- **測試設計的教訓**：`test_total_never_exceeds_balance` 斷言的正是這個性質、而且一直綠燈，
  但輸入全是小數點後兩位的「漂亮數字」，**那種輸入不可能違反該性質**。
  真實餘額有 8 位小數。已把真實值加進輸入集並補一條指名事故的迴歸測試，
  且先還原舊實作反證過兩條新測試確實會失敗
- 測試 312 → 313 項
- 新增 TASKS.md **B5**：ccxt 把餘額不足歸類成 `AuthenticationError`，日誌寫「認證失敗」，
  會把人引去查金鑰而不是查金額
- 下一步：合併後 CI 部署會自動 `reset-failed` 並重啟，屆時確認第一筆真單掛出

## 2026-08-15（續）—— 第一筆真單掛出，隨即抓到取消掛單失效（分支 `fix/cancel-offer-id-type`）

- PR #21 合併部署後，第一筆真單成功掛出並三方對帳一致：日誌、Bitfinex 實際掛單
  （`5081103121`、160 USD、`ACTIVE`、0.000523、2 天）、DB `loan_offers` 三邊數字相同。
  融資錢包可用餘額掉到 0.00861413（160.00 已鎖進掛單），符合預期
- **監看在第二輪抓到新問題**：`取消掛單 5081103121 失敗：bitfinex id: invalid`，
  且連續兩輪重複發生。根因是 ccxt 對這個端點回傳的欄位**全是字串**，
  而取消端點只收整數 id（見 DECISIONS.md D026）
- 更值得記的是**失效方式**：單筆取消失敗只記 ERROR 就 continue，本輪照樣算成功
  ——不告警、心跳照常、健康檢查綠燈，**機器人看起來完全正常，核心策略卻已停擺**。
  對照 D025 那次直接崩掉、五分鐘內被發現，這次沒有任何一道防線響過
- 修法兩項：`int(offer[0])` 轉型；「查到掛單卻一筆都取消不掉」改拋 `RetryableError`
  讓主迴圈看得見（部分成功不算失敗，避免反應過度）
- 測試替身 `make_offer_array()` 改成回傳字串——它原本比真實 API 乾淨，
  正是這個 bug 躲過測試的原因。與 D025 是同一種病（那次是輸入太乾淨、這次是替身太乾淨）
- 測試 313 → 315 項，拿掉 `int()` 反證有 4 條會失敗

## 2026-08-15（收工）—— 實單第一天總結

- **機器人已在真金模式常駐運作**：每 10 分鐘取消舊掛單、以當下 FRR 重算利率、重掛一筆。
  D026 修正部署後第一輪即完整跑通：`已取消 1 筆` → 餘額釋放回 160.00861413 →
  掛出新單 `5081124199`；Bitfinex 上獨立查證舊單確實消失、新單 ACTIVE
- 今日一共上線四條分支：#19（LINE）、#20（go-live）、#21（D025 金額）、#22（D026 取消 id）
- **實單第一天抓到兩個 dry-run 不可能發現的 bug**，都在首輪或次輪就暴露：
  - D025：掛單金額四捨五入超出餘額，被交易所拒單（機器人崩潰 → CRITICAL 告警 → 5 分鐘內發現）
  - D026：取消掛單的 id 型別錯誤，且失敗被吞掉（**沒有任何告警，連續三輪靠人盯日誌才發現**）
- 資金狀態：160 USD 掛在 `5081124199`（0.000523/日、2 天期），**尚未被借走**，
  融資錢包剩 0.00861413。整天零損失
- 明天的起點與待辦見 TASKS.md「進行中」段落

## 2026-08-16 —— 掛單 12 小時零成交，查出定價基準用錯（分支 `tune/market-rate-validation`）

- PR #23 合併，main 到 `a58aeba`，本地切回 main 同步後從最新 main 開本分支
- **回答昨天的「明天第一件事」：78 輪掛單一筆都沒成交**。機器人本身健康狀態全綠
  （心跳正常、連續失敗 0、12 小時零 ERROR），失效方式是「一切正常但什麼都沒發生」——
  每輪日誌完全相同：`已取消 1 筆` → 餘額回到 160.00861413 分毫未動 → 重掛 160.0
- **昨天寫的兩條對策，實測資料顯示兩條都不會成交**——這是昨天分析最大的盲點：
  - 對策 1（`premium_rate` 降到 0.00005 → 掛 0.00037）：當日成交裡 ≥ 0.00037 的有 **0 筆**
  - 對策 2（FRRDELTAVAR）：那是 `FRR + delta`，delta 不設負一樣掛在市場之上。
    **換掛單型別解決不了定價基準錯誤的問題**
- **真正的根因：FRR 本身就已經高過市場成交天花板**。FRR 是落後加權平均，今日 0.000322
  （年化 11.77%），而 fUSD 當日實際成交的最高利率是 0.000274（年化 10.00%）。
  所以 `FRR + 任何正數` 必然掛空——連 `premium_rate = 0` 都不會成交。
  我們掛的 0.000522 是年化 19.05%，接近市場天花板的兩倍
- **市場結構實測**（`/v2/trades/fUSD/hist` 10000 筆、跨 3.2 小時；`/v2/book/fUSD/P0`）：
  2 天期成交利率的全距只有 0.000238～0.000274（年化 8.68%～10.00%）；
  借款需求側最高只有一檔年化 10.25%（120 天期、40 萬 USD），第二高就掉到 7.30%；
  放貸供給側 439 萬 USD 全擠在年化 9.00%～10.10%。
  **訂價權不在我們手上**——掛 19% 不是比較貪心，是掛在沒有買家的價位上
- **訂價的真正取捨是排隊位置，不是利率高低**：沒成交的時間年化是 0%。
  以 2 天期算，掛在天花板 0.000274 只要多等超過 3.1 小時，就輸給掛中位數立刻成交。
  市場很深（2 天期每小時成交 331 萬 USD、供給側總共才 439 萬），故第 90～95 百分位是甜蜜點
- **本分支只改一個設定值做驗證**：`premium_rate` `0.0002` → `-0.00005`，
  掛單利率落到 0.000272（年化 9.93%、約第 90 百分位）。
  先證實「掛不出去的唯一原因就是利率」，後面的策略改寫才值得寫。
  315 項測試全過（測試用自己的 config fixture，不受 `config.yaml` 影響）
- **明確記為過渡手段**：負的 premium 語意是壞的，且綁在 FRR 上——實測 FRR 一升到 0.00035，
  掛單就變回 0.0003（年化 10.95%）而再度掛空。正解是改用市場成交價的百分位定價（待寫 D028）
- 連帶記錄三項後續與一項小事：天期 2 天 → 7 天（中位數差 0.56 個百分點）、
  spread 階梯的乘法遞增會在金額超過 300 USD 時產生必定掛空的死單、
  容器日誌時間戳是 UTC 而文件是 CST（差 8 小時，對帳容易誤判）

## 2026-08-16（續）—— 時區統一為 CST（分支 `fix/unify-timezone-cst`）

- PR #24 合併部署（13:20:40 CST），`premium_rate: -0.00005` 生效，
  掛單利率從 0.000522 降到 **0.000272～0.000273**（年化 9.93%～9.97%）。
  部署本身一切正常，D023 的三分法也如設計送出 INFO（不推 LINE）
- **使用者要求把時間統一成 CST**。查下去發現比原本記的嚴重：
  不只是「容器 UTC、文件 CST」，而是**同一個日誌檔裡就混了兩個時區**——
  機器人在容器裡寫 `05:20:41`、主機端的 `scripts/notify_failure.py` 寫 `13:20:42`，
  兩行緊挨著差 8 小時。而 `notify_failure.py` 的 docstring 還寫著
  「與機器人日誌同格式的時間戳，讓兩邊的行可以一起看」——**意圖對，但它從第一天起就是假的**
- 根因：兩邊都用「行程的本地時區」（`datetime.now()`、`logging` 的 `%(asctime)s`），
  程式碼看起來一致，行為卻由**它剛好跑在哪裡**決定
- 修法見 DECISIONS.md D028：新增 `utils/clock.py` 當唯一時區來源、
  `utils/logger.py` 的 `ZonedFormatter`、`db/repository.py` 的 `utc_now()` → `now_iso()`、
  `notify_failure.py` 複製一份最小解析（維持 D024 獨立實作原則）。
  時間戳一律附 `+0800`，讓每行自己講清楚是什麼時區
- **刻意不用 `TZ` 環境變數、也不動 Dockerfile**：那會把時區留在環境裡，
  而環境正是這次出錯的地方（Quadlet／compose／CI／本機各有各的，漏一個就再度分岔）。
  實測 `python:3.11-slim` 本來就帶 tzdata，`ZoneInfo("Asia/Taipei")` 在容器內直接可用
- **舊資料不遷移**：DB 舊列 `+00:00`、新列 `+08:00`，都是 aware，healthcheck 相減仍正確。
  已用新舊兩種格式各驗過判定結果（正常／過期都對）
- 測試 315 → 327 項。實測驗收三道：強制 `TZ=UTC` 跑 logger 仍輸出 `+0800`、
  真實容器內（無 `TZ` 變數）日誌與 DB 都是 CST 且與主機時鐘一致、健康檢查新舊格式都正確
- **定價驗證的中途觀察（尚未成交，已跑 5 輪 50 分鐘）**：把成交資料按 10 分鐘分桶後發現，
  我們這個價位的成交是**陣發的**——3.7 小時的 23 個時段裡，只有 3 個時段有
  ≥0.000273 的成交，其餘全是 0。13:20 部署至今（約 1 小時）一筆都沒有。
  這修正了先前「第 90 百分位是甜蜜點」的判斷：那個結論取自剛好含一次爆發的 32 分鐘窗，
  拉長來看第 90 百分位只在爆發時成交。正式改百分位定價時要取中位數附近而非 90（見 TASKS.md）

## 2026-08-16（續）—— 盤點待辦並排出工作計畫（直接更新 main，未開分支）

- PR #25（時區統一）合併，main 到 `2838f08`。部署後日誌確認生效：
  機器人與主機告警腳本兩邊都寫 `14:32:36,700 +0800`，與主機時鐘一致，
  自此同一個日誌檔不再混時區
- **使用者指示：只改專案文件、不必開分支，直接改 main**（本次為純文件變更）
- 盤點全部待辦後排出五個優先級，寫進 TASKS.md 的「工作計畫」段（權威清單）
  並同步 PLAN.md 的「接下來的順序」
- **盤點時讀 `core/bot_engine.py` 發現一項新缺口（已列為 P2-1）：機器人察覺不到自己成交了**。
  掛單成交後餘額歸零，下一輪 `build_offer_plan()` 回空清單，日誌寫
  「可放貸金額不足，略過本輪」——**與「錢包本來就是空的」完全無法區分**；
  沒有通知，DB 也沒有任何一筆記錄「這筆借出去了」。
  `api/bitfinex_client.py` 現有五個方法裡**沒有任何查詢已借出部位的能力**。
  這是 D026 的鏡像：那次是壞了沒人知道（靜默失效），這次是成功了也沒人知道（靜默成功）
- 一併確認既有設計正確的部分：成交後的 `SkipCycleError` 在主迴圈裡走
  `record_success()`，**不會誤觸連續失敗告警**，缺的純粹是「看得見」
- **API Key 權限經使用者確認**（先前 session 已告知，本次補記進文件與長期記憶）：
  開通六項——帳戶歷史查閱、融資狀態查閱、融資提供/取消/關閉（唯一寫入權限）、
  錢包餘額與地址查閱、帳戶設定讀取、允許從任何 IP 訪問。
  **提現（Withdraw）沒有開通**，金鑰外洩資金也搬不走。
  其中「融資狀態查閱」正是 P2-1 與 P3-2 所需，權限已具備、不必回後台調整
- 修掉 TASKS.md 三個過期勾選框（建立 API Key、決定起始金額與 `dry_run` 切換、
  確認提現權限），並把殘留分支數重新盤點為 23 條
- 定價驗證持續中：`premium_rate: -0.00005` 已跑約 2 小時仍未成交，符合「陣發成交」的觀察

## 2026-08-16（續）—— 新增三項待辦：CI 部署過濾與 LINE 通知規劃（分支 `docs/tasks-notify-and-ci-deploy-skip`）

- **本次為純文件變更**，但依規範從最新 main（`4d1457d`）開分支處理，未直接改 main
- 使用者提出兩件事，拆成三項寫進 TASKS.md 的「工作計畫」（權威清單），
  **插進既有的五個優先級，不另立新層級**：
- **`P1-3`　純文件變更不要觸發部署重啟**（歸在優先級 1，不是雜務）
  - 現在推上 main 就重建映像並 `systemctl --user restart`，即使只動 `.project-docs/`。
    代價不是「斷幾秒」而是**掛單被取消後重掛一筆新的**——中間有一段訂單簿上
    沒有我們單子的空窗，同利率下的時間優先權也歸零
  - **歸在 P1 的理由**：我們這個價位的成交是陣發的（3.7 小時 23 個時段只有 3 個有成交），
    而本專案幾乎每天同步文件。用文件 commit 重置一張正在排隊的單子，
    等於自己拉長 P1-1／P1-2 的驗證期，所以它是**保護 P1 驗證條件的前置**
  - 做法記了兩層：合併時在**合併 commit 訊息**加 `[skip ci]`（加在分支 commit 上無效，
    CI 看的是 GitHub 產生的合併 commit）；正解是 deploy job 前面加一步比對變更路徑。
    一併記下兩個坑：force push 時 `github.event.before` 是全 0 要退回 `HEAD~1`，
    而 `actions/checkout@v4` 預設 `fetch-depth: 1`、`HEAD~1` 不在本地
  - **明確排除 `on.push.paths-ignore`**：那會連 `test`／`integration` 一起跳掉，
    若設了必要檢查反而永遠處於未完成而擋住合併
- **`P2-3`　LINE 訊息格式規範**（優先級 2，建議與 P2-1 同分支或更早）
  - 讀程式碼確認「訊息很亂」的根因：**沒有任何地方負責組訊息**。六則訊息全是裸字串，
    散在 `core/bot_engine.py` 三條退出路徑、`FailureTracker` 兩處、
    `scripts/notify_failure.py` 四種單元狀態，各拼各的句子
  - 提案三段式格式：第一行 圖示＋`【分類】`＋一句話結論（手機通知列只看得到這行）、
    中間 `欄位：值`（時間帶 `+0800`）、最後一行**「需人工介入／無需處理」二選一**
  - 分類固定四種：`【系統】``【交易】``【收益】``【風控】`；等級沿用四級，
    INFO 只寫日誌不推播（D023 已定案）
  - **實作注意**：主程式可抽 `notify/messages.py`，但 `scripts/notify_failure.py`
    **不能 import**——它跑在容器外、刻意零專案相依（同 `healthcheck.py`，見 A4／D024）。
    規範要寫成「兩邊各自實作、對照同一份文件」，否則下一個人一定會想共用程式碼
  - **時機理由**：P2-1 一定會推出第一則交易面訊息，格式沒定就會生出第二套風格
- **`P2-4`　交易面通知擴充：掛單／成交／日結**（優先級 2）
  - 使用者要的是「掛了什麼單、成交什麼單」的能見度，現在只有系統壞掉才通知
  - **硬限制：每月 200 則 ≈ 每天 6.6 則**。巡檢 600 秒＝一天 144 輪，
    每輪推一則 1.4 天燒光額度，之後真故障一則都送不出去。
    D024「例行巡檢不推 LINE」不能被推翻，只能在額度內重分配
  - 設計因此固定為：成交每筆推、掛單**只在內容與上一輪不同時**推、掛單失敗每次推、
    每日一則摘要。額度試算 90～150 則/月（日結 30 ＋ 成交 30～90 ＋ 系統告警預留 30）
  - **想看更細的正解是換管道**（如 Telegram，無月額度）或「細節寫日誌＋每日摘要」，
    不要用提高頻率解——超額就是整個月靜音
  - 依賴：格式照 P2-3、成交依賴 P2-1、利息依賴 P2-2；**掛單／掛單失敗兩類無依賴，
    可先做**，也是最快讓使用者感覺到差別的部分
- 同步更新 PLAN.md 的「接下來的順序」第 1、2 點

## 2026-08-16（續）—— P1-3 實作：純文件變更不再觸發部署重啟（同分支）

- **使用者提議「有些事可以在這條分支直接做掉」，評估後只做 P1-3**：它與這條分支的主題
  （部署／文件流程）同一件事，而且是唯一一項不會碰到正在跑真金的機器人的程式碼。
  P2-3／P2-4 要動 `core/bot_engine.py` 與 `scripts/notify_failure.py` 的訊息路徑並改測試，
  P1-1／P1-2 會改變實際下單行為——那三項各自開分支，才能單獨回退、也才對得出
  「這次成交是哪個改動帶來的」
- 做法：`.github/workflows/python-app.yml` 新增 `changes` job 比對變更路徑，
  `deploy` job 補上 `needs.changes.outputs.docs_only != 'true'`
- **擋在 job 層而不是 step 層**：deploy 有六個以上步驟，逐個加 `if:` 只要漏一個
  就會變成「映像沒重建卻重啟了服務」這種做一半的部署，比不部署更糟
- **不用 `on.push.paths-ignore`**：那會連 `test`／`integration` 一起跳掉，
  若分支保護設了必要檢查，被跳過的檢查會永遠停在未完成而擋住合併
- **fail-open**：`workflow_dispatch`、force push（`before` 全 0）、撈不到基準 commit
  一律照常部署。兩種錯的代價不對稱——多部署一次只是白重啟一輪，
  少部署一次是程式改了但機器人還跑舊版且沒人會發現
- 踩到並處理的坑：`actions/checkout@v4` 預設 `fetch-depth: 1`，`HEAD~1` 不在本地，
  退路會失效，故設 `fetch-depth: 2`
- **驗證：把偵測邏輯抽成獨立腳本，以 `bash -e -o pipefail` 跑過九種情境**——
  只改文件／只改程式／混合／新增檔／刪除檔／`before` 全 0／`before` 撈不到／
  `workflow_dispatch`／**GitHub 合併 commit**，輸出全部符合預期。
  最後一種是實際會發生的路徑；D017 補充第 2 點吃過「驗證時機與故障時機不同」的虧，
  所以這次特地把真正的合併情境建出來測，而不是只測本地 commit
- 決策理由寫進 DECISIONS.md（D017 的 2026-08-16 補充），TASKS.md 的 P1-3 標記完成
- **這條分支自己合併時仍會部署一次**：改到的是 `.github/`，不在 `.project-docs/` 底下，
  所以判斷結果是「照常部署」——這是對的。若不想被打擾，合併時在合併 commit 訊息加
  `[skip ci]`；下一次純文件同步起就自動不會重啟了

## 2026-08-16（續）—— P2-3／P2-4：訊息格式統一與交易面通知（分支 `feature/notify-format-and-trade-events`）

- PR #26 已由使用者合併，main 到 `c3aba50`；本分支已 fast-forward 對齊該點
- **P2-3 完成**：新增 `notify/messages.py` 統一組裝三段式訊息
  （結論行／`欄位：值`／「需人工介入」或「無需處理」二選一）。
  `scripts/notify_failure.py` 另寫一份同規格的獨立實作——它跑在容器外、
  不能 import 專案模組（A4／D024 的約束），規格只能靠測試守住
- **實作時修正了規劃的一處自相矛盾**：原本寫「圖示與等級綁定」，範例卻給成交配了 💰。
  定案為**正常事件看分類（🔵💰📊🛡）、異常事件看等級（🟡🟠🔴）**，共五個
- **實作時才浮現的分工**：三段式訊息直接寫進日誌會讓後續幾行看起來不像日誌、
  `grep ERROR` 只抓得到第一行。所以**日誌維持單行、推播才三段式**，兩邊分開組
- **P2-4 完成一半**（掛單那半，成交與日結仍待 P2-1／P2-2）
- **設計比原規劃更省額度**：原本寫「掛單內容與上一輪不同才推」，
  **實作時發現那擋不住 FRR 漂移**——利率每輪都有小數點後幾位的差異，
  比對「內容有沒有變」等於每輪都變，又回到一天 144 則。改為只追蹤
  **「場上有沒有我們的單」這個狀態的轉換**：啟動後首輪／消失／重新上線／被拒單，
  利率微調只寫日誌。實際頻率一天通常 0～2 則
- **意外收穫**：「掛單已不在場上」正是目前唯一能察覺「錢可能借出去了」的訊號，
  等於在 P2-1 還沒做之前先拿到它一部分的價值。**訊息刻意不寫死成「成交」**——
  餘額歸零也可能是資金被搬走，猜錯一次這個管道就不會再被相信（同 D023 的判斷）
- `_offers_live` 只放記憶體不落 DB：現有 schema 只有 `CREATE TABLE IF NOT EXISTS`、
  沒有遷移機制，為了省一則訊息去動正在跑真金的資料庫結構不划算；
  而「啟動後首輪」那則本身有價值（部署完最想確認的事）
- 新增 `config.yaml` 的 `line.push_trade_events`（預設 true）當額度安全閥——
  **關掉的是通知，不是紀錄**
- 測試 308 → 347 項。既有測試改了兩條，都是行為刻意改變（見 D029 的「影響」段）
- 決策寫成 **D029**；連帶更新 TASKS.md 中 P1-1 的註記（D029 已被用掉，定價 ADR 取下一個號）

## 2026-08-16（續）—— P1-1／P2-1：訂單簿定價與成交偵測（分支 `feature/orderbook-pricing-and-fill-detection`）

- PR #27 已由使用者合併，main 到 `f740ecc`；本分支自該點開出
- **起點是一個規劃問題**：使用者問「天期拉到 7 天真的比較好嗎？兩天兩天滾會不會更高？」
  ——這個問題逼出了三份實測，其中兩份推翻了既有規劃

### 分析（先於實作）

- **P1-2 的論據不成立**：TASKS.md 寫「7 天期比 2 天期高 0.5 個百分點」，
  該數字取自**含爆發桶的窗**。實測 7 天期 1711 筆成交有 1357 筆擠在 12:50 那一個
  10 分鐘桶，剔除後兩個天期的常態成交價完全一樣。**與 D027 記過的統計陷阱是同一個**
- **改用 998 天日 K 重算**：長天期確實較優（2 天 6.47%／7 天 9.45%／30 天 10.47%），
  原因是結構性的——86% 的供給擠在 2 天期，競爭把價格壓下去。
  但溢價會大幅變動（2023-Q4 +4.34 個百分點、2026-Q3 只剩 +0.20），
  **所以寫死任何天期都是錯的架構**
- **條件式分析**：利率處於高位（當下是第 85 百分位）時鎖長天期最划算，
  鎖 30 天有 94.8% 機率優於滾動。原因是均值回歸——高位之後 30 天的 2 天期平均
  會從 11.58% 掉到 7.17%。「等待短天期高利率」是幻覺
- **資金規模重排了優先級**（使用者提醒「我們就那三百多 USD」）：讓單子掛進簿子
  +18.92 USD/年、把現貨錢包的錢也投入 +14.39、動態天期 +7.97、
  **P3-1 與 P3-2 都是 +0.00**。由此得到定價鐵律：
  **空轉一天要靠「利率高 1 個百分點」跑 9 天才補得回來**

### 實作

- **P1-1 定價改為訂單簿排隊位置**（新增 `strategies/orderbook_depth.py`，設為預設策略）。
  演算法一句話：在「前方排隊金額 ≤ `target_queue_usd`」的前提下挑利率最高的一檔。
  **不用 trades 百分位**——那會被爆發桶汙染，等於 FRR 落後問題換個來源重演
- **`minimum_rate` 語意改掉**：從「太低就拉高到這裡」改成「低於這裡就整輪不掛」。
  舊寫法會把價格拉到簿子外，掛一張永遠不成交的單
- **不再每輪無條件取消重掛**（這項沒在原計畫裡，是讀日誌時發現的）：
  同利率下先掛先成交，每 600 秒重掛等於一天把自己送回隊伍末端 144 次。
  改為先查場上現況再比對，**實質相同就什麼都不做**；容差 2%，
  沒有容差的話小數點後幾位的漂移就會讓保護失效（D029 踩過同一個坑）
- **可支配金額 = 可用餘額 ＋ 場上掛單金額**：只看可用餘額的話，單子一掛出去餘額就變 0，
  策略會以為沒錢可放，於是每輪都得先取消才有錢算——等於強迫自己每輪重掛
- **P2-1 成交偵測**：新增 `funding_positions` 表與 `sync_positions()` 對帳，
  查 credits 與 loans **兩個端點**（只查一個會漏掉一半）。狀態落地，
  否則每次重啟都會把既有部位當成新成交推假通知。**對帳排在取消掛單之前**——
  取消會改變場上狀態，先動手就永遠答不出「這一輪成交了嗎」
- **`spread_count: 3 → 1`**：344 USD 最多拆 2 筆，第 2 筆會被乘到 0.000288
  而簿子頂端才 0.000270——一半的錢會變死單，**觸發條件正是「把資金全部投入」**

### 驗證

- **依 D027 先打真實 API 拿回應結構再寫替身**：funding offers 21 欄、全部字串，
  與既有程式碼的欄位假設一致；公開 book 每欄也是字串（`'0.0002808219178082192'`）。
  **credits／loans 兩個端點都是空的**（至今零成交），所以那兩支的欄位索引
  只能取自官方文件、**尚未經真實回應核對**——解析因此寫成防禦式，
  並在 D030 與 TASKS.md 列為待追蹤缺口
- **用真實簿子跑過整條定價鏈**：新策略掛 0.000250（年化 9.12%）、前方排隊 73 萬 USD；
  同一時刻舊策略掛 0.000272，**正好貼在整個供給側的最後面**——這就是 78 輪掛空的原因
- 測試 347 → 437 項（新增 90 項），整合測試 19 項照常通過

## 2026-08-16（續）—— **第一筆成交**，以及它險些被自己取消掉（分支 `docs/first-fill-and-pricing-roadmap`）

- PR #28 已由使用者合併，main 到 `123c606`；CI 自動部署，容器 18:10:12 重啟
- **本次只做文件規劃，不動程式碼**（使用者明確指示）

### 上線後的觀察

- 18:10:24 新策略首輪掛單：344.3 USD、利率 0.000250、2 天期、**單筆**
  （`spread_count: 1` 生效），排隊位置同天期前方 135,296 USD
- 18:20、19:20 兩輪：**「掛單條件與場上 1 筆一致（利率容差 2.0%），維持不動以保住排隊位置」**
  ——D030 新增的重掛保護第一次實際生效，機器人首度沒有無條件取消重掛
- **19:31:31 第一筆成交**：344.30 USD、0.000250/日（年化 9.12%）、2 天期、`kind=credit`
  ——自 2026-08-15 真金上線、掛空 78 輪之後的第一塊錢

### 成交前的等待時間估算（回答使用者「會不會等好幾天」）

打公開端點實算，資料窗 5.57 小時：

- 訂單簿供給側 250 檔／512 萬 USD，最低 0.000205、**最高 0.000262**
  ——先前掛空的 0.000273 **根本在整個簿子之外**，不是排最後面，是沒站進隊伍
- 我們的 0.000250 站在供給側第 41 百分位；成交價 ≥ 0.000250 的成交佔 71.6%
  （2,458 萬 USD），30/33 個時段都有流量
- 等待估計：含爆發桶 0.48 小時、**剔除爆發桶 0.79 小時**（保守值）
- 各檔位比較後結論：**`target_queue_usd = 1_000_000` 是對的，不該再往前擠**
  ——擠到 5 萬只省下不到 1 小時（值 0.001 USD），代價是年化掉 1.2 個百分點
  （2 天期一單少賺 0.023 USD）
- **實際結果 1.35 小時**（18:10:24 掛出 → 19:31:31 成交），方向對但比保守估計久 1.7 倍

### P2-1 的已知缺口：credits 端點欄位索引核對完成

D030／TASKS.md 列為待追蹤的「欄位索引取自官方文件、尚未經真實回應核對」，
第一筆成交後核對完畢，`funding_positions` 內容：

```
position_id 463909082 / amount 344.3 / rate 0.00025 / period 2 / kind credit
opened_at 2026-08-16T19:31:31+08:00   first_seen_at 2026-08-16T19:41:07+08:00
```

金額、利率、天期、時間全部正確，**credits 端點的解析確認無誤**。
`loans` 端點仍未驗證（這筆是 credit），缺口尚未完全關閉。

### 發現：19:31 那一輪，機器人決定取消一張 25 秒後就要成交的單子

`opened_at` 與 `first_seen_at` 兩個欄位裁決了時序（詳見 DECISIONS.md D031）：
對帳（19:31:01）當下確實還沒成交 → 送出取消（19:31:02）→ 成交（19:31:31）。
**取消沒趕上，純屬運氣。**

觸發原因是排隊位置掉到 0，策略據此算出可以掛更高的利率，超過 2% 容差就重掛——
單看定價沒錯，但「前方 0 USD」正是**最不該撤單**的時刻。
缺陷在於排隊位置只進了日誌，沒有餵回重掛判斷。規劃寫成 **D031**，本次未實作。

### 附帶驗證：D029 的措辭規則兌現了

19:31:06 推的「掛單已不在場上」刻意不寫死成「成交」、並列出可能原因，
**以當下事實判斷完全正確**。若當初圖方便寫成「成交」，那則就會是錯的。
這條規則的價值在第一次真實成交當天就兌現，不要改掉。

### 下一步

- **D031（重掛保護看排隊位置）排在 D032 之前**——期望值算得再準，
  重掛邏輯還會撤掉即將成交的單子的話就兌現不了
- D031 實作前要先查清一個疑點：「前方 0 USD」是真實狀態還是簿子讀取的假象
  （`len=250` 截斷／聚合精度），**若是假象則影響 D030 整條定價鏈的可信度**
- **施工窗口**：資金已鎖 2 天期、場上無掛單，這期間部署重啟不損失排隊位置
- P5-1（清理 23 條分支）**決定不做**，理由見 TASKS.md

## 2026-08-16（夜間第二段）——用半價借出去了，定價鏈補上成交資料源（D033）

### 事故：21:31:57 第二筆成交，年化 5.47%

19:31 那筆 344.30 USD 在 **21:21:52 被借款人提前還款**（實際只借 1 小時 50 分，
Bitfinex 的天期是上限不是保證）。機器人 4 秒後重新掛單，算出 **0.000150/日
（年化 5.47%）**，並在 **21:31:57 成交**——大約是市場價的一半。

當下市場並沒有跌：最近 60 分鐘成交 9,595 萬 USD、中位數年化 10.62%，
**89.4% 的成交在 0.000250 以上**。

### 根因：簿子底端一道 182 萬 USD 的低價牆

排隊規則的前提是「排我前面的錢不超過 100 萬」，而那道牆讓**任何高於 0.00015
的價位前面都排著 182 萬**——條件在牆以上無解，規則只好跟著牆掉下去。
加上 `round(base_rate, 6)` 把算出來的 0.000149995 推成 0.00015，
正好等於牆的利率，時間優先又把我們排到 182 萬的後面。

**演算法沒錯，錯的是輸入不完整**：訂單簿講「有人開價多少」，
講不出「借款人實際付多少」。詳見 DECISIONS.md D033。

### 修正（分支 `fix/pricing-market-floor`）

- `api`：新增 `get_recent_trades()`（公開端點 `/v2/trades/{symbol}/hist`）
- 策略：新增常態成交價 = **同天期成交的金額加權中位數**，
  掛單利率不得低於 `常態成交價 × 0.85`；拿不到成交資料就不掛
- `round()` → `_quantize()` 無條件捨去到 8 位小數
- `describe_queue()` 由 `<` 改為 `<=`（同價位的錢算進「前面」）
- `format_rate()` 6 位 → 8 位小數
- 日誌新增「市場常態成交價」一行
- `positions_closed()` 補上實際借出時長／提前還款或到期／利息毛估
- `minimum_rate` 0.0001 → 0.00021918（**年化 8.00%**，使用者指定的絕對地板）

### 實作過程中自己踩到、靠實打才發現的兩個坑

1. **第一版用「時間分桶、每桶一票」算常態成交價，實測不可用**——
   死時段（1 筆 150 USD）與活躍時段（1211 筆 867 萬 USD）等權。同一時間點
   只要把窗從 20 分鐘拉到 43 分鐘，算出來就從年化 8.75% 掉到 5.47%。
   改用金額加權中位數後三種窗口都落在 9.27%～11.45%。
2. **`limit=1000` 只涵蓋 1.2 分鐘**，樣本不足會讓機器人整輪不掛單。
   改抓 10000 筆（端點上限），約涵蓋 40～48 分鐘。

### 驗收

用當下真實市場實跑，並把那道牆放回簿子重演事故：

```
事故重演（把 182 萬的牆放回）
  舊版（只看簿子）會掛：0.00014999  年化 5.47%   ← 今晚實際掛出去的價
  新版                ：本輪不掛單（算出來低於年化 8% 的地板）

同一時刻沒有牆的真實簿子
  新版會掛            ：0.00026395  年化 9.63%
```

兩道防線分工明確：成交價下限把價位從 5.47% 拉到 7.76%，絕對地板（年化 8%）
再擋掉 7.76%，於是整輪不掛。正常市場上兩者都不介入。
測試 469 → 479 項全綠，另含對 `/v2/trades/fUSD/hist` 的即時契約測試。

### 下一步

- **這次的錢還鎖著**（21:31 起最長 2 天，但隨時可能被提前還）。
  還回來時就會用新策略重新定價。
- 驗收時注意到：排隊規則算出年化 11.61%，而常態成交價是 9.27%
  ——**掛單價高於一半的錢實際成交的價位**。這是 `target_queue_usd` 的調校問題，
  正是 D032（P1-5）要用期望值取代人工旋鈕的那一項。
- D031（P1-4，重掛要看排隊位置）仍未做；本次把 `describe_queue()` 修對，
  等於補上了它的前提——在此之前那個數字在有牆時會低估 1,775 倍。

## 2026-08-16（夜間第三段）——查證推翻了 P1-4 的原規劃，重掛判準改用推導式（D034）

分支 `fix/requeue-queue-position-guard`。這一段的主軸不是寫程式，是**先把 D031 要求
查清楚的疑點查清楚**——結果那個疑點的答案直接否定了 D031 開出來的處方。

### 疑點查清了：「前方 0 USD」是假象，而且真相相反

D031 點名的三個可能原因逐一查：`len=250` 截斷（**不影響**，累積到 100 萬只要 49 檔，
我們抓 250 檔涵蓋 497 萬）、P0 聚合精度（**不影響**，同利率多列全部都是不同天期）、
舊版 `<` 的比較（**就是它**）。

證出一條定理並以真實簿子的 36 個子集驗證無反例：

> 舊版報「前方 0 USD」⟺ 算出來的價位正好落在簿子**最低**那一檔。

而落在最低檔時，真實的前方金額是那一檔的全部金額。把牆放回去重演：
**舊版報 0 USD，新版報 200 萬 USD——完全相反。**

還發現第二個誤讀：那兩個排隊數字的主詞一直是**候選價位**（`plans[0].rate`），
不是場上那張單。順帶推回 19:31 那一輪重掛的真正方向是**把價格往下調**
（候選價位必定 < 0.000245），與 D031 寫的「想掛更高的利率」相反——
它與 21:31 的半價事故是同一個機制，只是被日誌假象掩蓋了。

### 原處方實測不成立

D031 的修法是「前方排隊金額低於門檻就不動單」。排隊金額對利率是**單調**的，
所以「前方少」幾乎等同「這張單掛得比市場便宜」——固定門檻鎖住的正好是最該往上
調價的那些。實測：2% 容差擋不住的 64 個往上調價位，重掛期望值**全部為正**。

中途還推翻過自己的一個中間版本（「利率更差、隊伍又更長就不動」）：因為單調性，
那種情況根本不可能發生，判準是空的。**重掛永遠是取捨，沒有免費的判斷。**

### 完成

- **往下調價的重掛要先證明划得來**（`_cheaper_repost_is_not_worth_it`）：
  用 `利息 ÷ (等待 + 借出期間)` 比較兩條路。**只管往下這個方向**——那個方向放棄的
  利息是確定的、換來的速度是估的，而「估的」那半邊目前只有一個校準樣本
- **取消生效確認**：等待後再查一次場上掛單，仍有單就整輪不重掛（D031 的第二個缺口）。
  原本用餘額回推，而 19:31 證明餘額與「單子還在不在」會分岔，處置卻完全相反
- `describe_queue()` 加上 `period` 參數；日誌分出「候選價位」與「場上掛單」兩個排隊位置
- 新增設定 `engine.queue_clear_usd_per_hour`（540000，取自唯一一筆真實成交的實測）
- 測試 479 → 493 項

### 驗收（真實市場）

19:31 重演：修正前重掛、修正後不動（利率 -40% 換等待省 3.9 小時，在 48 小時的天期
面前補不回來）。當下真實簿子掃過 223 個可能的場上利率：82 個行為改變、全部落在
往下調的方向；往上調價 82 個一個都沒誤擋。

### 附帶發現

驗收當下的簿子**底端又有一道低價牆**（純看簿子會算出年化 5.44%），被 D033 的成交價
下限與年化 8% 地板擋下，策略本輪不掛單。那道防線上線不到一天就第二次出手，
**低價牆不是偶發事件**。

### 下一步

- P1-5／D032 的範圍因此更清楚：本次證明沒有不需模型的捷徑，D032 要補的是天期選擇
  與等待時間的即時估計，而 `queue_clear_usd_per_hour` 正是它要吃掉的第一個旋鈕
- **往上調價的方向目前完全沒有把關**（刻意的，實測支持），但那份實測只有一份快照
- 資金仍鎖在 21:31 那筆年化 5.47%（最長 2 天，隨時可能被提前還）

## 2026-08-17 —— 空轉一整天，查證推翻「市場跌了」的第一印象（D035）

分支 `fix/market-floor-goes-stale`。這一天沒有任何程式碼變更，機器人**一筆單都沒掛**。
這一段的價值全部來自查證：**第一個結論是錯的，第二個才是真的。**

### 這 21 小時實際發生的事：什麼都沒有

PR #30 於 2026-08-16 23:33 部署，容器 `active (running)` 21 小時、healthy。
但當天的 493 行日誌**全部**是同一句「可放貸金額不足，略過本輪」，
DB 裡 2026-08-17 一筆掛單都沒有，融資錢包只剩 0.016 USD。

原因不是故障：**344.3 USD 仍鎖在 08-16 21:30 那筆年化 5.47% 的部位**
（`funding_positions.closed_at` 仍是 `None`），2 天期，最晚 2026-08-18 21:30 到期。
機器人整天無事可做是正確行為。

### 推演：資金回來的那一刻，會整輪不掛單

用專案自己的 `OrderBookDepthStrategy` 對當下的真實市場跑 `build_offer_plan(344.3)`：

```
排隊定價（前方 ≤ 100 萬）：0.00014996/日（年化 5.47%）
成交價下限（0.85 × 常態）：0.00013779/日（年化 5.03%）
絕對地板 minimum_rate：    0.00021918/日（年化 8.00%）
  → 低於地板，整輪不掛單 → 0 筆
```

簿子最前面是一道 **445 萬 USD、掛在 0.00015、2 天期**的牆——D033 那道 182 萬的牆
不但沒散，還長大了 2.4 倍。當下 30 分鐘內的成交**年化 8% 以上佔 0.0%**，
金額加權中位數年化 5.47%。

### ❌ 第一個結論（錯的）：「市場跌到 5.5%，8% 地板過期了」

這個結論的證據全部取自**當下這一個時間切片**，而它與 D030 記過的統計陷阱是同一類錯誤
——**用一段太短的窗去代表市場**。

### ✅ 查歷史 K 線之後：市場沒有跌，它是在每小時之內劇烈震盪

抓 `/v2/candles/trade:1h:fUSD:p2/hist`（1 小時 K、2 天期、5000 根，涵蓋 2026-01-21 起）：

| 窗 | 收盤 ≥ 年化 8% | **當根曾觸及 8%** | 收盤中位數 |
|---|---|---|---|
| 最近 7 天 | 46.7% | **89.3%** | 年化 7.75% |
| 最近 30 天 | 44.7% | **90.0%** | 年化 7.63% |

**每小時的振幅大得離譜**，隨便挑幾根 2026-08-17 的：

```
時間        開盤    收盤    最高    最低      成交量
08-17 19:00  5.51%   7.26%   9.78%   4.46%   5,720,072
08-17 20:00  7.26%   5.47%   9.78%   4.92%   5,726,224
```

也就是說：**「年化 5.47%」不是市場價，那只是最後一筆成交剛好落在區間的底部。**
同一個小時裡，需求掃到 9.78%。而 08-16 那兩筆成交正是這件事的兩面——
19:31 以 9.12% 成交（該小時最高 11.68%）、21:31 以 5.47% 成交（**該小時最高 11.77%**）。
**那筆「半價事故」是在一個曾經漲到 11.77% 的小時裡賣在底部的。**

### 回測：掛得越高，實質年化越高——一路到年化 10% 都還在漲

以「某根 K 的最高價 ≥ 掛單利率」判定會被掃到，實質年化用 D034 的式子
`r × 48 ÷ (等待 + 48)`（2 天期 = 48 小時）：

| 掛單年化 | 中位等待 | 平均等待 | 實質年化（7 天） | 實質年化（30 天） |
|---|---|---|---|---|
| 5.50% | 0.5h | 0.5h | 5.44% | 5.44% |
| 8.00% | 0.5h | 0.6h | 7.90% | 7.90% |
| 9.00% | 0.5h | 1.3h | 8.76% | 8.81% |
| 9.75% | 0.5h | 2.7h | **9.23%** | 9.40% |
| 10.50% | 0.5h | 11.7h | 8.45% | **9.61%** |

**中位等待一路都是 0.5 小時**——因為九成的小時都會掃到 8% 以上。
等待成本要到年化 10% 以上才開始咬人。

### 🔴 真正的結論：壞掉的旋鈕是 `target_queue_usd`，不是 `minimum_rate`

- **年化 8% 地板一直是對的**，而且是目前唯一在保護我們的東西。
  它擋掉的正是「賣在區間底部」。保留它的代價接近零（8% 的平均等待 0.6 小時）。
- **壞的是排隊定價**。`target_queue_usd = 1_000_000` 的意思是「排在前 100 萬以內」，
  而簿子底端被 445 萬的牆佔住時，那個條件會**強制**把我們押到 5.47%。
  排隊模型假設「排越前面越快成交」，但這個市場的成交是**陣發掃單**：
  需求來的時候一路掃到 9~10%，**站在最前面只保證你用最低價賣掉**。
- **D033 對那道牆的定性要修正**。當時寫「那代表某一個人願意賤賣，不是市場的價格」
  ——牆的存在是事實，但它不是偶發事件，而是這個市場的常態結構；
  真正的錯誤不是被牆騙到，而是**用「排隊位置」當定價基準**這件事本身。

### 這正是 D032（P1-5）預言的事，只是主角換了

D032 說「人手算出來填進設定檔的數字，市場一變就過期，而程式無從察覺」。
過期的不是它點名的 `queue_clear_usd_per_hour`，是 `target_queue_usd`——
它在 2026-08-16 簿子還薄的時候校準，一天之後簿子結構變了就失效了。
**P1-5 從「該做」升級為「擋在收益前面的唯一一件事」**：回測顯示現行策略
把年化 5.47% 當答案，而同一份資料下的期望值最佳解是 9.2~9.6%——**差距約 4 個百分點。**

### 下一步

- 定價改用期望值：候選利率 × 被掃到的機率，取 `r × 48 ÷ (等待 + 48)` 最大者（P1-5／D032）
- `minimum_rate` 年化 8% **維持不動**
- 等待時間的估計要有資料源：新增 1 小時 K 查詢，不能再靠人手填常數

### 同日實作：期望值定價上線（D035 的修正）

分支 `fix/market-floor-goes-stale`，commit `474b166`。

- 新增 `strategies/expected_value.py`（繼承 `OrderBookDepthStrategy`，只換掉定價那一步）
- 新增 `api.get_rate_candles()`；`strategies/base.py` 加 `requires_candles` 旗標與
  `candles` 參數；`core/bot_engine.py` 加 `_fetch_candles()`
- `config.yaml` 的 `strategy.mode` 改為 `expected_value`，
  **`minimum_rate` 年化 8% 與 `market_floor_pct` 原封不動**
- 測試 493 → 512 項

**驗收（同一份真實市場資料）**：舊策略 **0 筆**（排隊定價算出年化 5.47%，被 8% 地板
擋下）；新策略 **1 筆、年化 9.96%**，平均等待 3.1 小時、窗內命中 40 次、
**實質年化 9.35%**。另以 dry-run 走過 `build_strategy()` → `_fetch_candles()` →
`build_offer_plan()` 整條接線。

**寫測試時被自己的測試資料打臉、因而看清楚的一件事**：`r × 48 ÷ (等待 + 48)`
對等待非常寬容——48 小時的借出期間是分母大宗，**等 8 小時只讓實質年化打 86 折**。
原本以為「20% 但要等 8 小時」會輸給「9% 立刻成交」，實際上前者 17.1%、後者 8.9%。
這既是策略敢掛高價的理由，也正是 `ev_min_hits` 非要不可的理由——
少了它，期望值會爬到尾端那個只發生過一次、等不到的價位。

**沒做的部分：天期仍寫死 2 天。** 比較天期要一輪打三次 K 線端點（`p2`/`p7`/`p30`）
並各自估等待，是另一次改動的份量；資金到期前先讓「掛得出去」成立。列為 P1-5 的剩餘部分。

## 2026-08-17（收尾）——PR #31 合併後的盤查與路線圖重排（D036）

分支 `docs/audit-and-roadmap`。沒有程式碼變更，內容是盤查與規劃。

### 部署確認

PR #31（`fe0af92`）已合併，容器於 **21:22:15 重啟**，日誌第一行
`採用放貸策略：expected_value` ——新策略確實上線。資金仍鎖在 08-16 那筆
（餘額 0.016 USD），所以還在「可放貸金額不足，略過本輪」，行為正確。

### 盤查發現六項（三項程式、三項文件）

全部以實跑真實市場資料確認，詳見 TASKS.md 的「程式／文件盤查結果」。
**前三項都是 PR #31 自己帶進來、而且沒有任何測試蓋到的行為改變**
——因為它們的失效條件是「候選價位高過訂單簿可見範圍」，在舊策略下不可能發生：

- **A1**：`last_evaluation` 是死碼，期望值的計算過程完全沒進日誌。
  **這是 D033 的教訓在新定價鏈上原封不動重演。**
- **A2**：重掛守門檻（D034）退化成「永遠擋下往下調價」。候選價位年化 9.96%、
  簿子可見最高檔只有 7.21%，`_queue_ahead()` 對任何價位都回傳同一個截斷總額
  5,381,114 USD，分母約掉之後判準只剩比利率。實跑確認：往下調 10% → 擋下。
- **A3**：排隊位置日誌變成截斷值（數字正好等於簿子 250 檔總計）。
- **B7～B9**：README 還寫「現階段以 dry-run 為主」（自 08-15 起是真金）、
  ARCHITECTURE 沒有 `expected_value.py` 與 `get_rate_candles()`、
  兩處註解與現況矛盾。

### 路線圖重排（D036）

使用者提出「感覺沒有先規劃好就一直改不太好」。盤點兩天內的六個決策
（D030～D035），**後面的一再推翻前面的**，而共同成因是：
每個決策都用一個時間切片做出來，然後把結論寫成常數塞進設定檔，資料丟掉。
DB 有四張表，**沒有一張存過市場長什麼樣**。

所以路線圖把**量測基礎建設排在下一個策略決策之前**（第 1 期）：
市場資料落地、回測工具、成效量測。第 2 期以後的策略工作都做在那之上。
五個舊優先級的內容保留，只有排序被取代。

### 更正：CI 紅燈的成因是 GitHub 全域事故，不是這台機器（同日稍晚）

使用者找到 githubstatus.com 的公告，**推翻了先前對 C1 的成因判斷**。

事故建立於 **2026-08-17T13:40:03Z**（截至 15:10Z 仍在 `investigating`），
影響元件含 `Webhooks / API Requests / Issues / **Pull Requests** / Actions / Pages / Copilot`，
公告明寫 **「Archive downloads and raw repository content downloads are experiencing
an approximate 50% error rate」**——而 `codeload.github.com/.../tar.gz/...`
正是 archive download。

**今晚三個症狀因此是同一個根因**：CI 紅燈、「Merge status cannot be loaded」、
以及 PR 頁面載不進去（後兩者對應元件清單裡的 **Pull Requests**）。

### 🔴 這次的教訓：D036 的毛病，隔一天就自己犯了一次

先前把成因判定為「這台機器有 2 個 runner 共用對外 IP、`_work/_actions` 沒快取」。
那個說法**從頭到尾沒有直接證據**，是從「兩個 runner」這個事實推出來的合理故事。
`curl` 三次 429 同時符合兩種解釋，我卻只採用了自己那一個。

**D036 才剛寫完「每個決策都是用一個時間切片做出來的」，隔天就原封不動再犯一次。**
差別在於這次有人（使用者）去查了外部狀態頁——**而那正是我應該做而沒做的第一件事：
在歸咎自己的基礎設施之前，先確認上游是不是掛了。**

### 修正仍然保留，但理由改寫

自架 runner 要自己去公開的 codeload 下載 action，GitHub 託管的 runner 不走那條路。
所以 GitHub 的 archive download 一出問題，只有自架這邊會斷——
實測 3 比 0（同一段劣化期間 ubuntu-latest 三次全成功、自架兩次全滅）。
減少對公開 codeload 的依賴仍然正確，**只是沒有原本以為的那麼緊急**。

**連帶未解**：`deploy` 仍在自架 runner 且第一步就是 `actions/checkout`，
**GitHub 再出一次同樣的事故，部署就會斷**。已記進 C1。

## 2026-08-17（深夜）——A1：定價決策進日誌，並修掉一個講錯理由的出口

分支 `fix/log-expected-value-reasoning`（疊在 `docs/audit-and-roadmap` 上——
PR #32 卡在 GitHub 事故，不是內容有問題，所以不等它）。

### 完成 A1：期望值的推導寫進日誌

`ExpectedValueStrategy.describe_decision()` ＋ 迴圈層的 `_log_pricing_rationale()`。
`last_evaluation` 從死碼變成真的有人讀。真實市場實跑：

```
期望值定價：116 個候選價位，選中年化 9.96%（平均等待 3.1h、窗內命中 40 次、
實質年化 9.36%）；對照最快成交的候選 年化 5.47%（等待 0.5h、實質年化 5.42%）
```

**「對照最快成交的候選」是刻意加的**：那正是舊策略會選的價位，兩者並排才看得出
取捨換到了什麼。而 5.47% 剛好就是 08-16 那筆半價成交的價位——**日誌現在會把
「我們差點又賣在那裡」直接印出來。**

### 🔴 動手時才發現的更嚴重問題：不掛單的理由是寫死的，而且多半是錯的

`build_offer_plan()` 有**六個出口**回傳 `[]`，迴圈層一律寫「可放貸金額不足」，
**其中五個跟金額無關**。最糟的是「價格低於年化 8% 地板」：

```
舊：可放貸金額不足（目前 344.3 USD）        ← 帳上明明有 344 USD，自相矛盾
新：期望值算出年化 6.94%、成交價下限拉到年化 6.94%，仍低於地板年化 8.00%，本輪不賣
```

**而這正是市場走弱時最可能出現的情況**——也就是明天資金回來後很可能看到的畫面。
舊訊息會把人指向「錢為什麼不見了」，完全錯的方向。

**這是 D026「靜默失效」的第三次現身**：D026 壞了沒人知道、D030 成功了沒人知道、
這次是**決定不做，但講錯理由**。

修法刻意放在 `Strategy` 基底（`last_skip_reason` ＋ `_skip()`），
**三個策略的每個出口都要交代理由**——只修 `expected_value` 的話，
之後有人切回 `orderbook_depth` 做對照就會踩回同一個坑。
答不出來時退回中性的「未提供原因」：**講「不知道」遠比講一個具體但錯誤的原因好。**

### 測試

512 → 517 項。新增的那一組（`TestDecisionIsVisible`）逐一走過六個出口，
確認沒有任何一個是沉默的；另有一項專門釘住
「價格太低而不掛時，理由不可以說成沒錢」。

### 下一步

- A2（重掛守門檻退化）與 A3（排隊位置日誌變截斷值）**刻意留到下一條分支**：
  兩者牽涉「兩個等待估計器要統一成哪一個」，那是設計決策，不該順手夾帶
- PR #32 與這一條都等 GitHub 事故解除再合併（合併會觸發自架 runner 的 deploy）

## 2026-08-18 —— 🎉 期望值策略拿到第一份正面證據；PR #32 與 A1 合併上線

**這一天是這個專案第一次「策略贏了，而且贏在可以說清楚的地方」。**

### 事件時序（全部有日誌與 DB 佐證）

| 時間 | 事件 |
|---|---|
| 18:35:22 | 08-16 那筆年化 5.47% 的部位**被提前還款**，344.30 USD 回到融資錢包 |
| 18:35:28 | 同一輪重新掛單：344.36 USD、日利率 0.0002729（**年化 9.96%**）、2 天期 |
| 18:45～22:07 | 場上維持不動。市場常態價一路下滑 7.58% → 6.94% → **5.47%** |
| 22:11:22 | **成交**（部位 `464047005`），等待 3.6 小時 |
| 22:37～22:39 | PR #32 與 A1 合併進 main，CI 全綠，容器 22:39:02 重啟 |

### 為什麼這筆成交是「證據」而不只是「運氣好」

掛單期間市場常態價**跌到 5.47%**，我們卻掛在 9.96% 不動，最後被一波掃單吃掉：

- **含閒置時間的實質年化 9.27%**（3.6 小時閒置 ＋ 2 天借出）
- 對照當時立刻成交只能拿 **年化 5.47%**
- 而 5.47% **正是 08-16 那筆事故成交的價位**——同一個數字，這次沒有賣在那裡

**D035 的核心主張（成交是陣發掃單，撐住高價划得來）第一次被真實市場正面驗證。**
先前三筆成交裡，一筆 9.12%、一筆是 5.47% 的事故、一筆是這次。

### 🔴 但這筆的成因要誠實記下來：是策略的「不動」救的，不是策略的「判斷」救的

拆開來看，18:45～22:07 每一輪擋下重掛的都是 `_plans_match()` 的
**2% 利率容差**——候選價位始終落在 0.0002729 附近（`ev_window_hours=168`
把短期下跌平滑掉了），根本沒走到 D034 的守門檻。

也就是說：**A2（守門檻退化成永遠擋下往下調價）今天完全沒被觸發，
它的存在與否對結果沒有影響。今天的結果證明不了 A2 是對的。**
**這正是 D036 說的「用一個時間切片下結論」——要避免的就是把今天這筆讀成 A2 的背書。**

### 合併與部署（使用者指示直接處理）

機器上沒有 `gh` CLI 也沒有 token，改以本機合併後推 main；
GitHub 偵測到 head commit 已可從 main 到達，**PR #32 自動標示為 Merged**。

- 合併前先在 A1 分支跑完整測試（**491 ＋ 13 通過**，等於補上這條分支從沒跑過的 CI）
- `main`：`fe0af92` → `205a757`（兩個 merge commit：PR #32、A1）
- CI 四個 job 全綠，**部署階段成功**，容器 22:39:02 重啟

**時機是刻意挑的**：22:11 成交後資金已借出，**訂單簿上沒有我們的單**，
所以這次重啟不會取消任何掛單、不會損失排隊位置——**部署成本為零的視窗**。
（P1-3 保護的是純文件變更；這次含程式碼，本來就該部署。）

### A1 上線後第一行日誌就自己證明了價值

```
舊：本輪略過：可放貸金額低於最低門檻或單筆最小量，跳過本輪
新：本輪不掛單：可用餘額 0.01 USD 低於下限 150.00 USD
```

不必等到市場走弱那個情境，**重啟後的第一輪就看得出差別**。

### 目前狀態

- 部位 `464047005`：344.36 USD @ 年化 9.96%，**到期 2026-08-20 22:11**（可能提前還款）
- 累計三筆成交的毛利息約 **0.29 USD**，扣 15% 平台費後約 **0.25 USD**
  ——**而這個數字是手算的，`earnings_daily` 到現在還是空的**（見 PLAN 第 3 期 P2-2）

### 下一步的排序（使用者已認同，2026-08-18）

盤點後的三項急件，理由與取捨寫成 **D037**：

1. **A2 的最小誠實修法**——不做策略決策，只讓守門檻在算不出來時**棄權**而非偷偷否決
2. **M1 市場資料落地**——今天這筆是專案史上最有價值的一筆觀測，卻只存在於四行日誌裡
3. **P2-2 `earnings_daily` 接上資料源**——三筆部位跑完了，還是答不出「賺了多少」

## 2026-08-19 —— 等待估計問錯了問題；閒置時間第一次被量出來（D038）

**分支**：`fix/honest-wait-estimate-and-idle-tracking`

### 起點：使用者問「五點多被贖回、掛的單到現在還沒成交吧？」

核對日誌與 DB 的結果（時間點與使用者記憶差了半天，是**凌晨** 05:03 不是下午）：

- `05:03:19` 借款人**提前還款**，344.36 USD 收回。部位 `464047005` 原定 08-20 22:11
  到期，實際只借了 6 小時 52 分（08-18 22:11 → 08-19 05:03）
- `05:03:24` 重新掛單 `5084375241`：344.36 USD @ 0.000268（年化 9.78%）、2 天期
- 至 23:09 **已閒置 18.1 小時未成交**，期間 108 輪日誌每一輪都印同一句
  「維持不動以保住排隊位置」

### 兩份現場證據（都是當下抓的，不是事後推測）

1. **掃單發生在掛單之前**：03:00 那根 K 的 high 是 9.88%、04:00 是 9.96%，
   都掃得到 9.78%；05:00 之後 18 小時最高只到 9.12%。近 24 小時只有 2 根 K
   觸及 9.78%，兩根都在掛單前。
2. **掛單越出可見簿子**：當下 250 檔供給側總額 1,306,715 USD，
   **可見最高利率只有 9.04%**，而我們掛 9.78%——日誌印的「前方 2,289,677 USD」
   是截斷值（A3 現場重現）。順帶證實 B9：`bitfinex_client.py:146` 那句
   「250 檔對應約 500 萬 USD，足以蓋過整個供給側」在今天的簿子上是 130 萬，蓋不住。

### 做了什麼（兩層，都不動決策行為）

**第一層——把等待估計換成「從任意時刻進場」**（見 D038）

`estimate_wait_hours()` 的 docstring 宣稱處理了陣發性，但最後的 `fmean()` 把它
抹掉了：`[6,0,0]` 與 `[2,2,2]` 的平均都是 2。改成 `estimate_wait()`，
從每個小時各出發一次算等待，回傳 `WaitEstimate`（平均／中位數／p75／命中數／
右設限數）。右設限改為**計入而非丟棄**（丟掉的正是最長的那些）。

真實市場實跑（240 根 1h K）：

```
期望值定價：110 個候選價位，選中年化 9.78%（進場等待 平均 6.0h／中位數 3.5h／
四分之三在 9.5h 內、窗內命中 54 次、實質年化 8.70%、11% 的起點在窗內沒等到
「真實等待更長」）；對照最快成交的候選 年化 5.47%（平均等待 0.5h、實質年化 5.42%）
```

同一份資料舊算法選 9.96%、說「等 3.2h」，真實是 10.8h。

**第二層——閒置時間量測**（D037 順位 1 的那一項）

- `_parse_offers()` 補 `created_at_ms`（索引 2 = MTS_CREATE），**已實打驗證**：
  `'1787087004000'` → `2026-08-19 05:03:24 +0800`，與掛單當輪日誌一致
- 新表 `offer_wait_forecasts`：掛單當下的預估一張單一列
- 每輪印閒置時數、機會成本（金額）、與當初預估的對照
- 量測點放在所有「要不要動這張單」的判斷**之前**——閒置最久的輪次走的正是
  「維持不動」那條提早 return 的路徑

### 驗證

- 測試 493 → 509 項（單元＋功能），整合測試 13 項另外全過
- 測試替身一併校正：`make_offer_array()` 與 `live_offer()` 補上 MTS_CREATE
  （字串型別，與真實回應一致）；`FakeClient` 補上 `get_rate_candles()`
- 真實市場資料實跑確認日誌與落 DB 的內容

### 一個推論錯誤（留底，見 D038 最後一節）

第一次診斷寫的是「模型用均勻假設、命中率取倒數」，**那是錯的**——程式明確反對
倒數法。誤判的原因是 `168 ÷ 54 ≈ 3.1` 剛好對得上日誌，但那是數學恆等式而非證據。
真正的毛病不在用哪一種平均，而在**取平均這個動作本身**。與 C1 同一種錯誤：
數字對得上不等於機制猜對了。

### 下一步

- **A2-a／A3 仍未做**（D037 的順序不變）。A2-a 一放行就鬆開降價閘門，
  等這次的閒置資料累積出來再談
- 「等太久要不要降價」是策略決策，方向已算過：剩餘等待是重尾的
  （已等 6 小時後剩餘 15.1 小時、等 12 小時後仍是 15.0 小時），
  要用條件剩餘等待重跑期望值，**不要拍常數**
- 分批掛單算過不划算（最佳拆單 8.56% vs 最佳單點 8.77%），除非目標改成降低變異數

### 資金狀態

344.36 USD 仍掛在場上（`5084375241` @ 年化 9.78%），未成交。撐住的損益兩平點是
等待 38.6 小時（約 08-20 19:40），在那之前仍勝過「當初就用 5.47% 賣掉」。
**部署不會動到那張單**：新算法這一輪同樣選 9.78%，`_plans_match` 判定一致。

## 2026-08-19（收尾）——PR #33 合併部署，並補齊 B7／B8 文件對齊

**分支**：無（文件對齊部分依使用者指示直接在 `main` 更新，同 D037 的先例）

### 部署驗證

- PR #33 合併，main 在 `da546c2`。**兩個 commit 都以 `git merge-base --is-ancestor`
  實際比對過**，不是只看 PR 顯示已合併
- 容器 23:44:55 重啟、`Up (healthy)`，部署後無任何 WARNING／ERROR
- 新表 `offer_wait_forecasts` 已建立，目前 0 列——**符合預期**：
  場上那張單是 05:03 掛的，新表當時還不存在
- **場上那張已排隊 18.7 小時的掛單沒有被取消**，部署後第一輪就走
  「掛單條件與場上 1 筆一致，維持不動」，與部署前的實跑驗證一致

### 一個沒預期到的附帶效果

舊算法部署前那一輪選 9.96%，與場上那張 9.78% 差 **1.8%**——**卡在 2% 容差邊緣**。
新算法選出的價位與場上完全相同（0% 漂移）。
**降低等待估計的樂觀程度，連帶降低了重掛頻率**，動手前沒想到這一點。

### 文件對齊（B7／B8 清掉）

- **B7 `README.md`**：從「現階段以 dry-run 為主」改為「真金運作中」，
  補上「目前的定價策略」（白話講單位時間報酬與陣發掃單，含已知限制：
  天期仍寫死、市場資料未落地所以不能回測）與「部署」兩節
- **B8 `ARCHITECTURE.md`**：架構圖、目錄樹、元件說明三處補上 `expected_value.py`
  與 `get_rate_candles()`。**`orderbook_depth.py` 標明「已被取代但仍是父類別」**
  ——共用邏輯（金額拆分、風控上限、成交價下限、利率量化）住在那裡，它不是死碼
- **B9 未做**：兩處矛盾註解都在原始碼裡，當次指示不動程式。
  第一條（「250 檔對應約 500 萬 USD」）已在 08-19 拿到現場證據：實際只有 130 萬
- `PLAN.md` 新增「目前所在位置（2026-08-19）」：第 0 期剩 A2-a ＋ A3，
  並記下這一期為何比原訂的半天長很多——**兩天各冒出一個原本不在清單上、
  但比清單上任何一項都根本的問題（D037、D038），而且兩次都是動手修既有項目時
  讀程式本體才發現的**

### 下一步（順序有變，理由見 PLAN.md）

1. **等 D038 的量測收到第一組「預估 vs 實際」**——下一張掛單就會有
2. **A2-a ＋ A3**（要有上一步的資料才放行降價閘門）
3. **M1 市場資料落地**——D038 只落地了「掛單當下的預估」，
   那是 M3 的一半材料，**不是 M1**；市場長什麼樣仍然沒有任何一張表存過

### 資金狀態

344.36 USD 仍掛在場上（`5084375241` @ 年化 9.78%），已閒置 18.7 小時未成交。
損益兩平點在等待 38.6 小時（約 08-20 19:40）。

## 2026-08-20 —— 🎉 第二筆正常成交；A2-a／A3 完成（分支 `fix/honest-queue-position`）

**分支**：`fix/honest-queue-position`（收尾已跨到 08-21 凌晨）

### 今天的成交

| 時間 | 事情 |
|---|---|
| 00:00–15:05 | 場上仍是 08-19 05:03 那張年化 9.78% 的單，**已閒置 34.2 小時** |
| 10:12 | 期望值目標從 9.78% → **9.50%**（候選價位數 111 → 110，**是一根 K 滾出 168 小時窗**，不是市場變了：當時常態價與一小時前同為 8.00%） |
| 10:12–15:05 | **守門檻連續 30 輪擋下重掛** |
| 15:15:21 | 取消重掛：344.41 USD @ 0.00026027（年化 9.50%）、2 天期 |
| 19:10:59 | **成交**，等待 3.93 小時；19:17:50 偵測到並推播 |

全天 **0 WARNING／0 ERROR**，容器 `Up 23 hours (healthy)`。

### 三個數字要並排看

- **掛單當下的預估 vs 實際**：預估 平均 6.1h／中位數 3.5h／四分之三在 10.0h 內，
  **實際 3.93h**。這是 D038 的量測上線後**第一組校準資料**，落在中位數附近，
  沒有系統性偏差（**一個樣本**）
- **整個週期**：資金 08-19 05:03 就回來了，到成交空轉 **38.1 小時**。
  就算借滿 2 天，**週期實質年化只有 5.29%**；而 08-19 當時「立刻賣掉」的價位是
  5.47%（實質 5.42%）——**硬撐 38 小時，換到的比直接賣掉還少一點點**
- **首次成交至今（99.5 小時）**：真正借出去 57.6 小時，**資金使用率 57.9%**，
  累計毛利息約 0.145 USD，**整體實質年化 3.70%**

> 掛單的價格越來越漂亮，但「錢有多少時間在工作」還是輸家。

**成交的成因要誠實記**：市場常態價 12–14 點掉到 5.47%、19 點回到 9.12%，
我們掛 9.50% 就在市場漲上來的那一刻被掃到。**是市場漲上來找我們，不是降價換來的**
——降的那 2.9%（9.78 → 9.50）在這個波動面前是雜訊。這是 D035「撐住價格、
不要跟著跌」的第三次正面證據，但**不是**「今天那次降價是對的」的證據。

### A2-a ＋ A3：今天量到 30 個樣本，證明守門檻早就壞了

30 輪被擋下的日誌，每一輪的兩個排隊金額**完全相同**：

```
14:04 候選價位比場上那張單低，而排隊位置的改善補不回少收的利息
      （利率 0.00026800 → 0.00026027、前方 3,535,093 → 3,535,093 USD，
        單位時間報酬 0.0002358356 → 0.0002290333），維持不動。
```

30/30 命中率。**兩個數字一樣就是自白**：候選價位與場上那張單雙雙高過可見簿子，
`describe_queue()` 對兩者回同一個截斷值，分母約掉、判準退化成純比利率，
而前置條件已保證候選比較便宜——**答案恆定為「划不來」**。

**15:15 那唯一一次放行也不是判斷**：那一輪簿子剛好變深，兩個截斷值不再相同
（774,674 vs 1,817,452），閘門因此開了。**是資料的巧合。**

改法與驗收見 DECISIONS.md **D039**。要點：`describe_queue()` 多回 `truncated`
與 `visible_top_rate`；`_queue_ahead()` 越界回 `None`（棄權，不是否決）；
守門檻棄權時**要在日誌講出來**；兩行排隊位置日誌越界時改口說「至少」。
順帶清掉 B9 的兩處矛盾註解。

### 驗收（三層，都用真實資料）

1. **測試 509 → 520 項**（單元＋功能），整合 13 項（not live）全過
2. **真實簿子重演**：把當下簿子截到 2026-08-19 的可見上限（年化 9.04%）——
   舊版兩個數字相同（41,841 → 41,841）並否決、新版棄權。掃過所有候選價位，
   **30 個行為改變，全部落在越界那一側**；可見範圍內的 33 個一個都沒動
3. **以正式 `config.yaml` ＋ 真實市場資料實跑 `run_once()`**：

```
越界（重演 08-19／08-20）：
  掛單排隊位置估計：同天期前方 至少 119,774 USD、全天期前方 至少 126,180 USD
    ——候選價位年化 9.50% 已超出可見簿子（可見最高年化 9.04%），以上是下界
  往下重掛的守門檻棄權（…）：排隊金額只知道下界、比不出快慢，這一項不擋事
  → 取消 1 次、掛單 1 筆

可見範圍蓋得住（同一時刻、未截斷的真實簿子）：
  場上掛單排隊位置：前方 258,493 USD          ← 語氣不變，仍是量測值
  候選價位比場上那張單低，而排隊位置的改善補不回少收的利息（…），維持不動。
  → 取消 0 次、掛單 0 筆
```

**第 3 點的對照組是這次驗收的重點**：兩個價位一模一樣，只有簿子的可見範圍不同。
比得出來的時候，這條判準**照樣否決**——A2-a 修的是「算不出來時偷偷否決」，
不是把判準拿掉。

### 🔴 今天新發現的問題（都還沒做）

1. **期望值公式假設借滿 48 小時，但四筆有三筆提前還款**
   （`expected_value.py` 的 `hold_hours = offer_period * 24`）：
   實際持有 1.8h／45.1h／6.9h。而且**看起來與利率反向相關**——
   9.12% 借 1.8h、9.96% 借 6.9h、5.47% 借 45.1h（借款人跑去借更便宜的）。
   若成立，「撐住高價」的期望值被系統性高估。**4 個樣本，是假設不是結論**，
   而它正好是 M2 回測工具該回答的問題
2. **LINE 通知講錯話**：15:15 那次重掛推的是「啟動後首輪掛單已送出」，
   但容器已經跑了 15 小時。`_offers_live` 在「維持不動」那條路徑上永遠留著 `None`
3. **價格目標會因為一根 K 滾出視窗而自己跳一階**（10:12 的 111 → 110）。
   今天整條事件鏈的起點就是這個，而**我們無法直接證實**——市場資料沒有落地（M1）

### 資金狀態

344.41 USD 借出中（部位 `464168644` @ 年化 9.50%、2 天期，08-20 19:10:59 起），
最晚 08-22 19:10 到期。場上沒有我們的掛單——**部署成本為零的視窗**。

## 2026-08-21 —— PR #34 部署完成；合併後盤查抓到 D4（分支 `fix/abstain-reason-names-the-right-one`）

### 部署驗證

- PR #34 合併，main 在 `277620f`。**兩個 commit 都以 `git merge-base --is-ancestor`
  實際比對過**，不是只看 PR 顯示已合併
- 容器 **00:34:05 重啟、`Up (healthy)`**，systemd 接管正常，**部署後 0 WARNING／ERROR**
- **容器內的 `bot_engine.py`／`orderbook_depth.py`／`bitfinex_client.py` 與 main
  的 sha256 逐一比對一致**——跑的確實是新程式碼，不是舊映像

**但要誠實記：新程式碼的關鍵路徑到現在一次都沒被執行過。** 錢還借在外面
（餘額 0.01 USD < 150 下限），策略整輪不產生計畫，而排隊位置日誌與守門檻
都在「有計畫」之後才走得到。真正的上線驗證要等資金回來。

### 合併後盤查抓到 D4：棄權的理由指錯對象

**D039 自己帶進來的 bug**，是回頭讀程式碼＋實跑探測才發現的：

```
場上 0.000268 越界？ True      ← 真正答不出來的是這一張
候選 0.00026 越界？  False
日誌：往下重掛的守門檻棄權（候選價位年化 9.49% 已超出可見簿子（可見最高年化 9.67%））
```

**9.49 小於 9.67**，這句話自己就矛盾。棄權有**三個**成因（場上那張單越界、
候選價位越界、換算速率設成 0），而 D039 的第一版只看了候選價位。
換算速率被關掉時更離譜：當下沒有任何東西越界，它照樣寫「已超出可見簿子」。

而「可見上限落在舊價與新價之間」正是**市場走弱時最常見的形狀**——
場上那張是幾天前的高價、新算出來的比較低，簿子頂端剛好落在中間。不是角落案例。

**決策從頭到尾都是對的，錯的只有理由。** 與 A1 修過的病同一種
（D026 靜默失效的家族：這次是「決定不做，但講錯是哪裡不知道」）。

同批還修掉第四個角落：`not book` 原本混在第一道 guard 裡，**簿子抓不到時
整條判斷靜悄悄跳過**。現在的分界是——「沒有場上的單、沒有計畫」代表根本沒有這個
問題，安靜返回是對的；「拿不到簿子」是**有問題卻答不出來**，那是棄權，要出聲。

四種情境的實際輸出：

```
兩個都越界：  場上那張單（年化 9.78%）與候選價位（年化 9.49%）超出可見簿子（可見最高年化 8.03%）
只有場上越界：場上那張單（年化 9.78%）超出可見簿子（可見最高年化 9.67%）
換算速率關掉：queue_clear_usd_per_hour 設為 0，排隊金額換算不成等待時間
拿不到簿子：  拿不到訂單簿，排隊金額無從算起
```

### 驗收

- 測試 520 → **524 項**（單元＋功能），整合 13 項（not live）全過。
  四個新測試各釘住一種理由，其中兩個是**反向斷言**：
  「候選價位看得到時不可以被點名」、「沒有任何東西越界時不可以寫超出可見簿子」
- 真實市場資料端到端重演一次：越界時棄權並重掛、簿子蓋得住時照樣否決，
  **行為與 D039 完全一致——這次只動理由，沒動任何決策**

### 這件事本身值得記

修 D026 第四次現身的那個 PR，自己生出了 D026 的第六次現身。
**一個判斷式改成「會說不知道」之後，「不知道什麼」就成了新的說謊空間。**
下次再寫這類棄權路徑，理由要從一開始就按成因逐一列，不要先挑一個代表。

### 資金狀態

344.41 USD 借出中（部位 `464168644` @ 年化 9.50%），最晚 08-22 19:10 到期。
場上沒有我們的掛單——**部署成本仍是零**。

## 2026-08-21（續）—— PR #35 部署驗證

- PR #35 合併，main 在 `66e7d3c`。**兩個 commit 都以 `git merge-base --is-ancestor`
  實際比對過**
- 容器 **01:09:09 重啟、`Up (healthy)`**，`NRestarts=0`，**部署後 0 WARNING／ERROR**
- 容器內 `bot_engine.py`／`orderbook_depth.py` 與 main 的 sha256 一致
- 部署後第一輪日誌：`本輪不掛單：可用餘額 0.01 USD 低於下限 150.00 USD`——正常

### 🔴 一件要盯著的事：兩次部署都還沒真正驗證到新程式碼

D039（PR #34）與 D4（PR #35）改的是**排隊位置日誌**與**往下重掛的守門檻**，
而這兩段都在「本輪有掛單計畫」之後才走得到。資金 08-20 19:10 借出後一直沒回來，
所以自 00:34 起的每一輪都停在「餘額低於下限」那個出口——
**新程式碼一行都沒被執行過**。

**資金回來的那一輪才是真正的上線驗證**（部位 `464168644` 最晚 08-22 19:10 到期，
也可能提前還款）。屆時要確認三件事：

1. `掛單排隊位置估計` 與 `場上掛單排隊位置` 兩行的「至少／量測值」語氣是否正確
2. 若走到守門檻，棄權的理由有沒有點名正確的對象
3. 新掛單有沒有在 `offer_wait_forecasts` 留下預估（第二組「預估 vs 實際」）

### 文件流程備忘（這次確認過）

CI 的 `docs_only` 判斷：**變更全部落在 `.project-docs/` 才會跳過部署**，
只要有一個檔案在它之外就照常部署（fail-open，理由見 workflow 註解與 C2）。
所以純文件同步可以直接推 main，不會重啟容器、不會動到場上的掛單。
