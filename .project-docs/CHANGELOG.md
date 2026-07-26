# CHANGELOG

## [Unreleased]
### Added
- `.project-docs/` 專案文件結構（PLAN/PROGRESS/DECISIONS/TASKS/CHANGELOG/ARCHITECTURE），
  取代原本散落根目錄的 `PRD.md`／`SHUYU_PROJECT_PLAN.md`（已歸檔至 `archive/`）
- dry-run 雛型：設定載入（`config/settings.py`）、策略骨架（`modules/lending_strategy.py`）、
  交易所封裝骨架（`modules/exchange_client.py`）、LINE 通知骨架（`modules/line_notifier.py`）
- CI workflow 骨架（`.github/workflows/python-app.yml`）：test / integration / deploy 三個 job
- spread 階梯利率：以 `frr + premium` 為最低階、每階乘 `(1 + spread_step_pct)` 遞增，金額均分、
  餘數併入最容易成交的第一筆，筆數依 `min_loan_size_usd` 自動降階，每筆各自判斷天期
- `maxtolend` / `maxpercenttolend` 放貸上限（單輪量控版）：觸及上限時縮量掛，預設 0 = 不限制
- `engine.cancel_settle_seconds`：取消舊掛單後等待餘額釋放的秒數（Bitfinex 取消為非同步）

### Fixed
- `get_frr()` 誤用 `fetch_funding_rate`（永續合約資金費率）的問題，改抓真正的放貸 FRR
- `main.py` 補上 `while True` 常駐主迴圈，不再僅單次執行
- `ccxt.bitfinex2` 於目前 ccxt 版本已移除的問題，改用合併後的 `ccxt.bitfinex`
- `cancel_active_offers()` 原本查錯訂單類型、從未真的取消掛單的問題
- `create_loan_offer()` 檢查不存在的統一方法、實盤模式下必定失敗的問題
- `cancel_active_offers()` 從未被主迴圈呼叫的問題：`run_once()` 改為每輪先取消舊掛單再重掛，
  避免利率落後市場的舊掛單卡住資金空轉

### Changed
- 移除 `strategy.split_threshold_usd`：原「餘額超過 300 才對半拆單」的語意已被 spread 的
  自動降階規則（餘額不足 `筆數 × min_loan_size_usd` 就降階）等價涵蓋

### Known Issues
- `line_notifier.py` 呼叫已停用的 LINE Notify 端點，通知永遠失敗（待使用者申請 LINE
  Developers 憑證後改寫為 Messaging API，見 TASKS.md）
- 尚無任何測試檔案，`tests/` 目錄未建立
- `maxtolend` 目前只管本輪掛出的總額，未計入已放貸出去的部位，尚非真實總曝險上限
  （見 DECISIONS.md D011、TASKS.md M3）

本專案尚未發版（無 git tag），暫不建立版本號段落；待 M1～M4（見 PLAN.md）完成、
可穩定 dry-run 常駐後，再開始標記版本。
