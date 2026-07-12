# ShuyuLendingBot

這是一個以 Bitfinex 放貸為核心的 Python 機器人專案。其目標不是單純做一個簡單腳本，而是建立一個可持續演進、可部署於 Linux 主機、並支援後續正式上線的放貸機器人雛形。

本專案現階段以 dry-run 為主，先把流程跑通（設定、secrets、連線檢查、策略判定、掛單計畫），之後再逐步通到真實下單。

---

## Development Roadmap (依 PRD 優先順序)

**目標摘要**

依照 `PRD.md` 的策略與架構，將專案分階段從 dry-run 漸進到可上線的放貸機器人；每階段皆建立對應的單元與功能測試，並在合併至 `main` 前執行整合/系統測試（CI gate）。

### 分階段任務（優先順序）

1. 基礎建設與 CI/測試規格
   - 定義測試框架：`pytest`（可加 `tox`），建立 `tests/` 目錄結構（`unit`、`functional`、`integration`）。
   - 在 `.github/workflows/python-app.yml` 中加入 `pytest` 步驟，確保 PR 與 push 都會執行測試。

2. 核心模組實作（模組化，逐一上測）
   - `modules/exchange_client.py`：封裝 `ccxt`，提供查詢可用餘額、取消未成交舊單、建立掛單等介面。
   - `modules/lending_strategy.py`：實作 FRR 基準計算、拆單邏輯、2 天 vs 30 天切換判定。
   - `modules/line_notifier.py`：封裝通知介面（dry-run 模式下可模擬，正式上線使用 LINE Token）。
   - `utils/logger.py`：確保日誌依 run 產生帶 timestamp 的檔案（已具備），並加入 log rotation 建議。

3. 單元測試與功能測試
   - 為每個模組撰寫 `tests/unit/test_*.py`，模擬邊界條件（餘額不足、FRR 極端值、API 失敗等）。
   - 撰寫功能測試在 `tests/functional`，可用 fixtures 或 mock 模擬交易所回應。

4. 整合/系統測試（CI gate）
   - 新增 `integration` job（runs-on: self-hosted runner），在合併到 `main` 前必須通過。
   - 測試內容包含：容器化啟動、讀取 secrets、主要流程的 end-to-end dry-run、短時穩定性檢查。

5. 從 dry-run 過渡到真實下單（小額測試）
   - 確認 API Key 權限（嚴禁 withdraw），在沙盒或小額真金進行試跑與驗證。

### 分支與 PR 流程建議

- 分支命名：`feature/<short>`（例如 `feature/core-modules`、`feature/tests-integration`）。
- 每個 feature 完成後建立 Pull Request；PR 必須通過單元與功能測試，且整合測試為必須綠燈方可合併。
- 合併時使用 GitHub 的保護分支規則（Required checks）。

### 測試類型與目錄

- 單元測試：`tests/unit/`（測試獨立函式/類別）。
- 功能測試：`tests/functional/`（模擬 exchange 回應、測試模組整合）。
- 整合/系統測試：`tests/integration/`（在 runner 或本地 Podman 上以容器啟動進行 e2e dry-run）。

### CI 變更建議

- `python-app.yml` 的 `test` job 執行單元與功能測試（GitHub-hosted runner）。
- 新增 `integration` job，指定 `self-hosted` runner，在合併前執行整合測試作為 gate。
- `deploy` job 僅在 `main` 分支且 `integration` 成功後執行。

### 本地開發快速檢查命令

```bash
python -m pip install -r requirements.txt
python -m pip install pytest
pytest tests/unit -q
pytest tests/functional -q
pytest tests/integration -q  # 在支援容器的環境
```

---

## 下一步（我將執行）

1. 我已建立開發任務清單（todo）。
2. 現在建立 branch `feature/roadmap-and-tests`，並把本次 README 的變更推到該 branch（下一個指令步驟會處理）。
3. 請你確認 roadmap；確認後我會依序實作核心模組並撰寫測試。

