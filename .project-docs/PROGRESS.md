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
