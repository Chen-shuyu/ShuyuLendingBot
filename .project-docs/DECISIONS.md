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

## D009 — 修正 M1 過程中意外發現的 2 個隱藏 bug：`ccxt.bitfinex2` 與 funding 錢包查詢
- 日期：2026-07-26
- 決策：在修正 `get_frr()` 的同一個分支（`fix/m1-frr-and-loop`）內，一併修正兩個原本不在
  TASKS.md 清單上、但屬於同一類「讓現有雛型正確」的致命問題：
  1. `modules/exchange_client.py` 初始化交易所物件時呼叫 `ccxt.bitfinex2(...)`，但目前
     `requirements.txt` 釘選的 `ccxt>=4.2.0`（實測 4.5.64）已把 V1／V2 合併為單一
     `ccxt.bitfinex`，不再有 `bitfinex2` 屬性；因為初始化包在 `except Exception` 裡吞掉錯誤，
     此問題完全不會顯式報錯，只會讓 `self.exchange` 靜默維持 `None`。改為 `ccxt.bitfinex(...)`。
  2. `get_available_balance()` 呼叫 `fetch_balance()` 沒有帶 `type="funding"`，ccxt 預設查的
     是 `exchange`（交易）錢包；且原本 `balance.get("info", {}).get("funding", [])` 的解析
     方式，對照目前 ccxt `fetch_balance` 原始碼（`result = {'info': response}`，`response`
     為陣列非 dict），在實盤模式下會直接對 list 呼叫 `.get()` 拋 `AttributeError`。改為
     `fetch_balance({"type": "funding"})` 並讀取 ccxt 統一格式 `balance[currency]["free"]`。
- 原因：兩者都屬於「實盤模式下必定失敗／崩潰」的致命問題，且都是在驗證 `get_frr()` 修正時
  順手用同一支 `ccxt` 版本實際測試（`python3 -c "import ccxt; ccxt.bitfinex2(...)"`、閱讀
  `fetch_balance` 原始碼）才發現；由於目前 `main.py` 一直是 `dry_run=True` 硬編碼，這兩個
  bug 從未在既有測試或 CI 中被觸發過。與其另開一輪任務追蹤，不如與 `get_frr()` 一起修完，
  避免「FRR 修好了，但一啟用實盤照樣掛掉」的半吊子狀態。
- 考慮過的替代方案：只修 `get_frr()`，把另外兩個 bug 另外記錄到 TASKS.md 排到 M2 —— 放棄，
  因為這兩個 bug 影響的正是同一輪巡檢會呼叫到的餘額查詢，範疇高度重疊，分開修反而增加
  之後對照的成本。
- 影響範圍：`modules/exchange_client.py`（`__init__`、`get_available_balance`）；連帶把
  `main.py` 原本寫死的 `dry_run=True` 改為讀取 `config.yaml` 的 `engine.dry_run`（否則這兩個
  修正永遠測試不到實盤路徑）。
- 附帶調整：`.github/workflows/python-app.yml` 的 smoke test 原本直接呼叫 `main()`
  並預期它會返回；但 `main()` 現在是常駐 `while True` 迴圈，不會自己結束，因此 smoke test
  改為呼叫新拆出的 `run_once()` 強制 `dry_run=True` 跑單輪。

## D010 — ccxt 對 Bitfinex funding 統一改走 raw/implicit API；保留 ccxt 套件，不自行改寫 REST client
- 日期：2026-07-26
- 決策：
  1. **維持使用 ccxt，但 Bitfinex funding（放貸市場）相關操作一律只呼叫 ccxt 的
     raw/implicit 方法**（如 `private_post_auth_w_funding_offer_submit`），不使用、也不再
     嘗試尋找任何「統一（unified）」方法——因為調查確認 ccxt 對 Bitfinex 的 P2P funding
     從未實作過統一層，不是版本問題。詳細盤點見
     `.project-docs/CCXT_BITFINEX_API_INVESTIGATION.md`。
  2. 修正 `create_loan_offer()`：改呼叫 `private_post_auth_w_funding_offer_submit`，
     `type` 固定用 `"LIMIT"`（策略層算好絕對利率再掛出，延續 D004 現有邏輯，不採
     `FRRDELTAVAR` 讓利率自動跟隨 FRR 浮動的做法）。
  3. `cancel_active_offers()` 維持現有「先查詢清單、再逐筆呼叫
     `private_post_auth_w_funding_offer_cancel` 取消」的做法，不改用
     `private_post_auth_w_funding_offer_cancel_all`（一次全部取消）——保留逐筆取消的原因
     是能在取消當下就拿到每筆掛單明細，供 log／未來 LINE 通知使用；目前巡檢頻率不高，
     多次 API 呼叫不是效能瓶頸。
  4. `test_connection()` 的 `fetch_balance()` 補上 `type="funding"`，與
     `get_available_balance()` 查詢同一個錢包，語意一致，並能在啟動階段順便驗證 funding
     錢包權限。
- 原因：短時間內連續三次踩到的 ccxt 隱藏 bug（`ccxt.bitfinex2` 被移除、`fetch_balance`
  查錯錢包、`cancel_active_offers` 查錯訂單類型），逐一追查後全部發生在「統一方法」這層；
  已經改走 raw API 的 `get_frr()` 與 `cancel_active_offers()` 查詢/取消，從未出過問題。
  全 ccxt 套件搜尋確認 `create_funding_offer`／`fetch_funding_offers` 這類方法名稱在任何
  交易所實作裡都不存在，`bitfinex.py` 的 `has{}` 能力宣告也沒有列出這組能力——代表這不是
  「這個版本剛好沒有」，而是 ccxt 從未替 Bitfinex 的 P2P 放貸市場建過統一抽象層。
- 考慮過的替代方案：完全放棄 ccxt、自行實作簽章直接呼叫 Bitfinex REST API —— 使用者評估
  後放棄，因為過去的 bug 全部出在「統一方法」這層，raw API 呼叫本身沒有出過問題；自行實作
  HMAC-SHA384 簽章、nonce 管理、速率限制、例外分類，是重新解決一個「並未真正發生」的問題，
  同時新增一塊全新的、對安全性敏感的自製程式碼風險，且會失去 ccxt 社群持續維護的好處。
  `create_loan_offer()` 的 `type` 選 `FRRDELTAVAR`（讓利率自動跟 FRR 浮動）——考慮過，
  使用者評估後選擇先用改動最小的 `LIMIT`，`FRRDELTAVAR` 列入未來策略優化選項。
  `cancel_active_offers()` 改用 `cancel/all` 端點簡化——考慮過，使用者評估後選擇維持現狀，
  優先保留掛單明細。
- 影響範圍：`modules/exchange_client.py`（`create_loan_offer()`、`test_connection()`
  已依此決策修正並通過 mock 測試）；解除 TASKS.md「🔴 下一步・最高優先」的阻塞狀態，
  M2 其餘項目（差額補掛、spread、maxtolend）可繼續推進；日後任何新增的 Bitfinex funding
  相關操作，一律先查 `.project-docs/CCXT_BITFINEX_API_INVESTIGATION.md` 的官方端點清單，
  走 raw/implicit API，不嘗試尋找統一方法。
