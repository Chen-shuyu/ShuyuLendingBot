# ShuyuLendingBot

這是一個以 Bitfinex 放貸為核心的 Python 機器人專案。其目標不是單純做一個簡單腳本，而是建立一個可持續演進、可容器化部署、並支援後續正式上線的放貸機器人。

本專案現階段以 dry-run 為主，先把流程跑通（設定、secrets、連線檢查、策略判定、掛單計畫），之後再逐步通到真實下單。

策略與架構源自 [MikaLendingBot](../MikaLendingBot)（經典開源放貸機器人）的精華，改以 Python 3 + `ccxt`（Bitfinex V2 API）重寫。

## 專案文件

本專案採用文件化管理，所有規劃、進度、決策與待辦都放在 [`.project-docs/`](.project-docs/)，不靠對話記憶延續：

| 檔案 | 用途 |
| --- | --- |
| [`.project-docs/PLAN.md`](.project-docs/PLAN.md) | 專案目標與分階段 Roadmap |
| [`.project-docs/PROGRESS.md`](.project-docs/PROGRESS.md) | 工作進度日誌 |
| [`.project-docs/DECISIONS.md`](.project-docs/DECISIONS.md) | 設計決策與原因（ADR 格式） |
| [`.project-docs/TASKS.md`](.project-docs/TASKS.md) | 待辦事項清單 |
| [`.project-docs/CHANGELOG.md`](.project-docs/CHANGELOG.md) | 版本變更紀錄 |
| [`.project-docs/ARCHITECTURE.md`](.project-docs/ARCHITECTURE.md) | 系統架構與設計說明 |

早期的規劃書（`PRD.md`、`SHUYU_PROJECT_PLAN.md`）已歸檔至 [`archive/`](archive/)，內容已分類遷移進上述文件，僅保留作為歷史脈絡備查。

## 本地開發快速檢查命令

```bash
python -m pip install -r requirements.txt
python -m pip install pytest
pytest tests/unit -q
pytest tests/functional -q
pytest tests/integration -q  # 在支援容器的環境
```
