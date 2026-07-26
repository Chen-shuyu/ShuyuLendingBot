# CHANGELOG

## [Unreleased]
### Added
- `.project-docs/` 專案文件結構（PLAN/PROGRESS/DECISIONS/TASKS/CHANGELOG/ARCHITECTURE），
  取代原本散落根目錄的 `PRD.md`／`SHUYU_PROJECT_PLAN.md`（已歸檔至 `archive/`）
- dry-run 雛型：設定載入（`config/settings.py`）、策略骨架（`modules/lending_strategy.py`）、
  交易所封裝骨架（`modules/exchange_client.py`）、LINE 通知骨架（`modules/line_notifier.py`）
- CI workflow 骨架（`.github/workflows/python-app.yml`）：test / integration / deploy 三個 job

### Known Issues
- `get_frr()` 誤用 `fetch_funding_rate`（永續合約資金費率），非真正的放貸 FRR
- `line_notifier.py` 呼叫已停用的 LINE Notify 端點，通知永遠失敗
- `main.py` 僅單次執行，無常駐主迴圈
- 尚無任何測試檔案，`tests/` 目錄未建立

本專案尚未發版（無 git tag），暫不建立版本號段落；待 M1～M4（見 PLAN.md）完成、
可穩定 dry-run 常駐後，再開始標記版本。
