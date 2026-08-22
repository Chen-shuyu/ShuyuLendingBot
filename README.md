# ShuyuLendingBot

這是一個以 Bitfinex 放貸為核心的 Python 機器人專案。其目標不是單純做一個簡單腳本，而是建立一個可持續演進、可容器化部署、並支援後續正式上線的放貸機器人。

**目前狀態：真金運作中**（自 2026-08-15 起，規模約 344 USD）。四個 milestone 都已完成——
自動重啟、健康檢查、失效告警、CI 自動部署、日誌輪替都經實測驗證。
以 Podman 容器 ＋ systemd（Quadlet）常駐，每 600 秒巡檢一輪。
dry-run 仍然保留（`config.yaml` 的 `engine.dry_run`），但不再是主要運行模式。

策略與架構源自 [MikaLendingBot](../MikaLendingBot)（經典開源放貸機器人）的精華，改以 Python 3 + `ccxt`（Bitfinex V2 API）重寫。

## 目前的定價策略

預設策略是 `expected_value`（見 [D035](.project-docs/DECISIONS.md)、[D038](.project-docs/DECISIONS.md)），
主張只有一句：

> **掛在哪個價位，由「利率 × 借出期間 ÷ (等待時間 + 借出期間)」最大的那一個決定。**

白話是：沒成交的時間年化是 **0%**，所以利率差要拿閒置時間去換。掛太高會等到把利差
吃光，掛太低則是把錢賤賣——策略每輪從 1 小時 K 線重新估「掛在這個價位要等多久」，
再挑單位時間報酬最高的那一檔。

這個市場的成交是**陣發掃單**（需求來的時候一口氣掃到 9~10%，沒來的時候簿子前端不動），
所以等待估計問的是「**我在任意時刻進場要等多久**」而不是「命中間隔平均多長」——
兩者在陣發市場差好幾倍（D038）。

**目前已知的限制**：

- **公式假設每筆都借滿天期，但實測不是**——借款人可以隨時還款，量測到的平均完成率
  只有 **32.1%**（六筆裡五筆提前還款，其中一筆只借了 2.33 小時）。分子被高估時，
  等待成本的權重被壓縮，選出的價位會偏高。**已知但刻意先不改**：要換成什麼值本身
  就是策略問題，得在回測工具上跑過（見 [D040](.project-docs/DECISIONS.md)）。
  隨時可查：`python3 scripts/hold_report.py`
- **天期仍寫死 2 天**（`offer_period`），還沒納入同一套期望值計算
- **市場資料尚未落地**，所以策略改動只能用即時快照驗證，不能回測（路線圖第 1 期）

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

## 部署

正式部署走 `systemd --user` 管理的 Quadlet 單元 `systemd/shuyu-lending-bot.container`
（見 [D007](.project-docs/DECISIONS.md)、[D017](.project-docs/DECISIONS.md)）；
`docker-compose.yml` 只供本機測試。推上 `main` 會由 GitHub Actions 自動重建映像並重啟服務，
**純文件變更不會觸發部署**（比對變更路徑，見 D017 的 2026-08-16 補充）——
重啟的代價不是斷幾秒，而是場上的掛單被取消重掛，時間優先權歸零。

金鑰放在容器外的 `~/.config/bfx-lending-bot/secrets.env`，以唯讀方式**只掛檔案本身、
不掛目錄**（D022）。
