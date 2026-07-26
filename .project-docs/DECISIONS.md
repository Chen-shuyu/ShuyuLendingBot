# DECISIONS

## D001 — 放棄直接修改 MikaLendingBot，改以 Python 3 + ccxt V2 API 全新重寫
- 日期：2026-07-14（記錄於 `PRD.md`，討論早於此日期）
- 決策：不直接修改 MikaLendingBot，取其商業邏輯精華（無限循環、自動劃轉、FRR 底線、xDays
  天期），另開全新 Python 3 專案 ShuyuLendingBot，改用 `ccxt` 封裝對接 Bitfinex V2 API。
- 原因：MikaLendingBot 底層綁定已淘汰的 Python 2 語法，且核心通訊層使用舊版 Bitfinex V1 API，
  有隨時被交易所關閉的維護隱患；其原本依賴的 LINE Notify 也已於 2025-03 底停用。
- 考慮過的替代方案：直接 fork MikaLendingBot 並升級語法/API —— 放棄，因為改動範圍等同重寫，
  且會背負舊專案的全域狀態耦合與 Plugin 架構包袱。
- 影響範圍：整個專案的技術選型與目錄結構起點。

## D002 — 通知管道改用 LINE Messaging API push
- 日期：2026-07-14
- 決策：`notify/line_messaging.py`（現 `modules/line_notifier.py`）改用
  `POST https://api.line.me/v2/bot/message/push`，取代舊的 LINE Notify。
- 原因：LINE Notify 已於 2025-03 底被官方全面終止服務，現有程式呼叫
  `notify-api.line.me` 這條路徑實際上永遠失敗。
- 考慮過的替代方案：其他通知管道（Telegram、Email）—— 未特別評估，使用者已熟悉 LINE 生態，
  沿用 LINE 只是換一套官方仍在維護的 API。
- 影響範圍：`notify/` 模組、`config.yaml` 的 `line.*` 設定鍵、環境變數
  `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_TO_USER_ID`。

## D003 — 主迴圈採程式內 `while True` + `time.sleep`，非外部排程器
- 日期：2026-07-14
- 決策：主流程在程式內以 `while True` + `time.sleep(interval)` 常駐運作，交由部署層
  （見 D007）的 restart 機制在崩潰時重啟，而非依賴 cron 或外部排程器每次重新啟動整個程序。
- 原因：單帳戶單幣種場景下邏輯簡單，程式內迴圈可維持記憶體狀態（如上一輪 FRR、上一輪掛單），
  避免每次冷啟動重新建立交易所連線的開銷與延遲。
- 考慮過的替代方案：cron 排程每 10 分鐘啟動一次腳本 —— 放棄，因為無法维持跨輪狀態、且冷啟動
  開銷較大。
- 影響範圍：`core/bot_engine.py` 的 `run_forever`／`run_once` 介面設計、部署層的 restart 策略。

## D004 — 核心策略：FRR+ 雙發彈夾（動態利率底線 + 拆單 + xDays 動態天期）
- 日期：2026-07-14（策略構想更早，正式記錄於 `PRD.md`）
- 決策：目標利率 = `max(FRR + premium, minimum_rate)`；餘額 ≥ 300 美元平分兩筆掛出，
  150～300 美元單筆全下，< 150 美元跳過本輪；平時掛最短 2 天，年化利率突破 30%
  （日利率 0.00082）時改掛 30 天鎖利。
- 原因：對應初始資金規模（約 344 美元）與 Bitfinex 最低放貸門檻（150 美元），在資金效率、
  還款時間錯開、高利可及時鎖住之間取得平衡。改寫自 MikaLendingBot 的 FRR 覆寫邏輯與
  `spreadlend`／`xdaythreshold` 概念的簡化版。
- 考慮過的替代方案：完整移植 MikaLendingBot 的多階梯 spread 掛單 —— 現階段先做簡化版
  （單一利率、最多拆兩筆），多階梯列入 M2 待辦（見 TASKS.md），待策略跑穩再評估是否需要。
- 影響範圍：`strategies/frr_plus.py`、`config.yaml` 的 `strategy.*` 設定鍵。

## D005 — 分層架構採 `config/api/strategies/core/db/notify/utils`，排除 Plugin 生態與多執行緒
- 日期：2026-07-14
- 決策：專案採 Exchange Adapter（`api/`）／Strategy（`strategies/`）／Orchestration（`core/`）／
  Persistence（`db/`）／Observability（`utils/` + `notify/`）的分層解耦結構；不採用
  MikaLendingBot 的 Plugin 生態（`PluginsManager`/`Plugin` hooks）、多 Worker/`Manager`
  多執行緒架構、Web 前端頁面。
- 原因：單帳戶單幣種場景不需要 MikaLendingBot 面向多使用者、多插件的複雜度；分層是為了讓
  策略層維持純函式、易於單元測試，且方便未來抽換交易所或策略。
- 考慮過的替代方案：沿用 MikaLendingBot 的 Plugin 架構以保留擴充性 —— 放棄，過度設計，
  目前需求不需要動態插件載入。
- 影響範圍：整個專案目錄結構（見 ARCHITECTURE.md）；`main.py` 精簡為 bootstrap。

## D006 — 資料持久化採 SQLite（WAL 模式），非外部 DB
- 日期：2026-07-14
- 決策：`db/repository.py` 使用 SQLite，開啟連線後執行 `PRAGMA journal_mode=WAL`，記錄
  `loan_offers`、`earnings_daily`、`bot_state` 三張表。
- 原因：單機部署、單一寫入者（主迴圈）+ 多唯讀查詢（未來報表/狀態頁）模型，SQLite WAL
  已足夠應付並避免寫入衝突，不需要額外維運一套外部資料庫服務。改良自 MikaLendingBot
  `AccountStats.py` 的 sqlite3 用法，但補上 WAL 與 transaction 收尾。
- 考慮過的替代方案：直接寫 JSON 檔（MikaLendingBot 原本作法）—— 放棄，易發生半寫損毀；
  外部 DB（PostgreSQL 等）—— 放棄，單機單帳戶場景過度設計。
- 影響範圍：`db/` 模組、`config.yaml` 的 `database.path`。

## D007 — 部署主線改為 Podman 容器化，取代 systemd bare-metal
- 日期：2026-07-26
- 決策：正式機部署走 Podman 容器化（CI 已有 `podman build` / `podman run` 的 deploy job），
  作為部署主線；現有 `systemd/bfx-lending-bot.service`（直接 `ExecStart` 跑
  `start.sh` → `python3 main.py`）保留供本機測試/備援用，不再視為正式路線。
- 原因：CI workflow 已經朝 Podman 容器化方向建置（build image、podman run、掛 secrets/logs
  volume），與其維護兩條互不整合的部署路徑（systemd 直接跑 python vs. CI 建置容器但沒交給
  systemd 管理），不如收斂成一條主線，降低維運心智負擔。
- 考慮過的替代方案：systemd 直接跑 Python 為主線，拿掉 Podman deploy job —— 使用者評估後
  選擇 Podman 容器化為主線；兩者並存暫不收斂 —— 也考慮過，但決定先收斂，避免長期技術債。
- 影響範圍：`.github/workflows/python-app.yml` 的 deploy job、`Dockerfile`、
  `docker-compose.yml`、`systemd/bfx-lending-bot.service`（角色改為備援/本機測試）。
  待補：容器的崩潰重啟策略（`podman run --restart` 或改用 `podman generate systemd` 產生
  systemd unit 來管理容器）目前尚未實作，列入 TASKS.md M4。

## D008 — 舊規劃文件內容遷移進 `.project-docs/` 後歸檔，不刪除
- 日期：2026-07-26
- 決策：`PRD.md`、`SHUYU_PROJECT_PLAN.md`（含根目錄 `LendingBot/PRD.md` 與
  `ShuyuLendingBot/PRD.md`、`ShuyuLendingBot/SHUYU_PROJECT_PLAN.md`）內容分類遷移進
  `.project-docs/` 六份文件後，原檔搬移至 `ShuyuLendingBot/archive/`，不刪除。
- 原因：這些文件記錄了完整的策略推導過程與 AI 協作實作指引（附錄 B 的介面簽章、驗收標準），
  即使內容已拆分進 `.project-docs/`，仍有歷史脈絡與備查價值；直接刪除會遺失推導過程。
- 考慮過的替代方案：保留原檔不動、`.project-docs/` 只是額外補充 —— 放棄，會造成兩份文件
  分別維護、內容漂移；直接刪除 —— 放棄，理由如上。
- 影響範圍：檔案位置變動；日後 `.project-docs/` 是唯一需要持續維護更新的正式文件來源，
  `archive/` 下的檔案視為凍結的歷史紀錄。
