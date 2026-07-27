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
- 下一步：**M3 已全數完成**，進入 M4（架構重構、測試與部署）——依 ARCHITECTURE.md 完成
  `config/api/strategies/core/db/notify/utils` 分層搬遷、建立 `tests/` 三層測試、收斂
  Podman 部署、最後才做 LINE Messaging API（仍卡在使用者尚未申請 Channel 憑證）
