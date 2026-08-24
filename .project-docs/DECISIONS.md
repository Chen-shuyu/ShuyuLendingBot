# DECISIONS

> **這份是 L2「為什麼變成這樣」。** 現在的狀態看 [STATUS.md](STATUS.md)。
>
> **這份文件刻意不拆檔、不瘦身**——程式碼註解裡有**上百處 `D0xx`** 指過來，
> 拆了就會把這些指標指向不存在的地方。
> ADR 是唯一「完整性比長度重要」的文件：它不該瘦身，該加索引。以下就是索引。

## 索引（42 條）

**狀態說明**：🟢 有效 ／ 🟡 成立但已被後續修正或只完成一半 ／ 🔴 已被推翻或取代。
**🔴 不代表當時是錯的**——它記錄的是「我們曾經這樣想，以及為什麼改」，
那正是 D036 存在的理由。

| # | 一句話 | 狀態 |
|---|---|---|
| D001 | 放棄改 MikaLendingBot，改以 Python 3 + ccxt V2 全新重寫 | 🟢 |
| D002 | 通知走 LINE Messaging API push（LINE Notify 已於 2025-03 停用） | 🟢 見 D024 |
| D003 | 主迴圈用程式內 `while True` + `sleep`，不用外部排程器 | 🟢 |
| D004 | 核心策略 FRR+ 雙發彈夾 | 🔴 被 D030→D035 取代，`frr_plus` 僅留作對照 |
| D005 | 分層架構 `config/api/strategies/core/db/notify/utils` | 🟢 |
| D006 | 資料持久化用 SQLite（WAL） | 🟢 |
| D007 | 部署主線改 Podman 容器化 | 🟢 生命週期見 D017 |
| D008 | 舊規劃文件遷移後歸檔，不刪除 | 🟢 本次重整沿用同一原則 |
| D009 | 修掉 `ccxt.bitfinex2` 與 funding 錢包查詢兩個隱藏 bug | 🟢 |
| D010 | **funding 操作一律走 ccxt raw/implicit API** | 🟢 |
| D011 | 掛單更新採「每輪全取消重掛」 | 🟡 後來加上「條件沒變就不重掛」（D030／D031／D034） |
| D012 | 每個 milestone 一條分支，完成即合併 | 🟡 合併方式已由 D014 改為走 PR |
| D013 | M3 可觀測四項：檔名輪替、掛單不重試、收益表先建不填、告警去重 | 🟢 |
| D014 | 合併一律走 GitHub PR，不在本地直接併 main | 🟢 |
| D015 | M4 拆子分支、測試先於重構 | 🟢 |
| D016 | 容器可靠性四項 | 🟡 其中重啟與日誌兩項實測沒生效，由 D017 補完 |
| D017 | **容器生命週期改由 systemd（Quadlet）管理** | 🟢 現行部署 |
| D018 | CI 日誌斷言改合併 stderr、以 cgroup 判斷 systemd 接管 | 🟢 |
| D019 | 退出路徑落帳不得改變離開碼；DB 路徑一律以專案根目錄解析 | 🟢 |
| D020 | systemd 失效告警 `OnFailure=` + `HealthOnFailure=kill` | 🟢 |
| D021 | 分層搬遷：介面的價值在例外契約 | 🟢 |
| D022 | 金鑰放家目錄、只掛單一檔案、不走環境變數 | 🟢 |
| D023 | 失效告警三分法（假警報比漏報更難修） | 🟢 |
| D024 | LINE 額度決定「什麼事件才配得上一則訊息」 | 🟢 每月 200 則 |
| D025 | 首次實單：掛單金額四捨五入超出餘額 | 🟢 |
| D026 | **取消掛單的 id 型別，與「靜默失效」比崩潰更危險** | 🟢 家族至今現身 8 次 |
| D027 | 測試替身一律取自真實回應，不得自己編「乾淨」版本 | 🟢 D041 兩個 bug 都栽在這 |
| D028 | 時區是應用程式屬性，不是容器環境的副作用 | 🟢 |
| D029 | 通知統一格式；**交易面推的是狀態轉換，不是狀態** | 🟢 |
| D030 | 定價基準改訂單簿排隊位置 | 🔴 **被 D035 推翻**（自變數選錯） |
| D031 | 重掛要看排隊位置守門檻 | 🔴 **處方被 D034 推翻**（方向相反） |
| D032 | 等待時間該由程式自己算，不是人手算後填設定檔 | 🟡 成立，但點名的旋鈕認錯了 |
| D033 | 只看訂單簿會被低價大單牽著走 → 成交價下限 | 🟡 下限仍在用；定性被 D035 修正 |
| D034 | 往下調價要先證明划得來（單位時間報酬） | 🟡 成立，但守門檻已退化，見 D037／D039 |
| D035 | **陣發掃單，改用期望值定價** | 🟢 **現行策略** |
| D036 | **六個決策兩天內互相推翻，根因是沒有量測基礎** | 🟢 方法論，仍在約束每個決策 |
| D037 | A2 拆成「修掉說謊」與「決定政策」兩件事 | 🟡 A2-a 已由 D039 做完；**A2-b 待 M2 回測工具** |
| D038 | 等待估計要問「我進場要等多久」 | 🟢 |
| D039 | 越界的數字要標示，判斷不出來就棄權（並出聲） | 🟡 第一版理由指錯對象，由 PR #35 修 |
| D040 | 實際持有時間量測（完成率 43.6% vs 假設 48h） | 🟢 **量測完成並已在正式環境跑過；改公式那一半待 M2** |
| D041 | 跨輪殘留的狀態被當成本輪的事實報出去 | 🟢 **正式環境驗收通過（08-23 23:04，130 輪無殘留）** |
| D042 | 市場資料落地拆成兩張表；**這一批只存觀測，不存決策** | 🟢 M1-a |
| D043 | 決策落地：`pricing_decisions` 每評估一輪一列，寫在日誌那一行的旁邊 | 🟡 **已部署（08-24 22:48）；待 08-25 部位收回那一輪驗收** |

### 幾條串起來看才有意義

- **定價的演化**：D004（FRR+）→ D030（排隊位置）→ D033（成交價下限）→
  D035（期望值）。**D036 解釋的正是這串為什麼互相推翻。**
- **重掛判準**：D031（排隊守門檻）→ D034（推翻，改單位時間報酬）→
  D037（發現已退化）→ D039（A2-a 改棄權）→ **A2-b 仍待決**
- **靜默失效家族（D026）**：D026 → D031 → D039／D4 → **D041（第七、第八次）**
- **部署可靠性**：D007 → D016（兩項沒生效）→ D017（systemd 接管）→ D018 → D020
- **量測基礎建設**：D036（診斷：沒有量測，決策互相推翻）→ D038（等待預估落地）→
  D040（實際持有時間）→ **D042（市場長相落地）** → M2 回測工具

---

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

## D011 — 掛單更新採「每輪全取消重掛」；spread 用百分比遞增；maxtolend 先做單輪量控版
- 日期：2026-07-26
- 背景釐清：原規劃書把這項需求寫成「只補掛差額，避免重複掛出已成交部分」，但該前提有誤——
  Bitfinex funding 錢包的 `free`（可用餘額）本來就已扣除掛單中與已放貸出去的金額，
  `get_available_balance()` 取的就是 `free`，因此「重複掛出已成交部分」的風險並不存在。
  這項需求的實質問題是另一個：**未成交舊掛單的利率會落後市場**（掛 0.05% 的單子在市場
  跌到 0.02% 後永遠不會成交，資金空轉）。決策即針對此問題。
- 決策：
  1. **掛單更新採「每輪全取消重掛」**（附錄 B.3 偽碼原本的做法，亦即 MikaLendingBot
     `cancel_all()` + `lend_all()` 的模式）：每輪先取消所有未成交掛單，等餘額釋放後用全部
     可用餘額重算掛單。`run_once()` 流程改為 cancel → settle 等待 → balance → frr →
     plan → offer → notify。
  2. **取消後等待餘額釋放再查餘額**：Bitfinex 取消掛單為非同步處理，回應 SUCCESS 只代表
     請求被接受、不代表餘額已釋放，因此新增 `engine.cancel_settle_seconds`（預設 3 秒），
     且僅在真的有取消到掛單時才等待。不自行把取消金額加回 `free` 計算，避免取消實際失敗
     時超額掛單。
  3. **spread 階梯利率採百分比遞增**：以 `max(frr + premium_rate, minimum_rate)` 為最低階，
     每往上一階乘上 `(1 + spread_step_pct)`（預設 0.15），金額均分、除不盡的餘數併入利率
     最低（最容易成交）的第一筆。不採 MikaLendingBot 的 order book 深度分析
     （`get_gap_mode_rates`），因為那需要額外抓取整本掛單簿。
  4. **spread 筆數自動降階**：Bitfinex 單筆放貸有最小金額限制（`min_loan_size_usd`，
     USD 為 150），金額不足 `筆數 × 最小單量` 時逐階降回，最低降到 1 筆全下。
  5. **每筆掛單各自判斷天期**：spread 各階利率不同，逐筆比對 `long_duration_threshold`，
     突破暴利閾值的高階掛 30 天鎖住高利、未突破的低階仍掛 2 天保持靈活（同
     MikaLendingBot `create_lend_offer()` 逐筆算 days 的做法）。
  6. **maxtolend 先做單輪量控版**：`max_to_lend_usd`（絕對值）與 `max_percent_to_lend`
     （佔可用餘額百分比，0~100），兩者皆設 0 = 不限制，同時設定時取較嚴格者；觸及上限時
     **縮量掛到剛好到上限**，不整輪跳過（同 MikaLendingBot `amount_to_lend()`）。此版本
     只管「本輪掛出去的總額」，不查詢 `/funding/credits`、`/funding/loans` 計算真實總曝險。
  7. **移除 `strategy.split_threshold_usd`**：原本「餘額超過 300 才對半拆單」的語意，已被
     spread 的自動降階規則（餘額不足 `筆數 × 150` 就降階）完全涵蓋且等價，不需要維護兩套
     參數。
- 原因：
  - 選「全取消重掛」而非「偏離容忍值才重掛」的混合方案：巡檢間隔 10 分鐘、每輪僅數次 API
    呼叫，遠低於 Bitfinex 每分鐘 90 次的速率限制，取消與重掛皆不收手續費，取消到重掛之間
    的數秒空窗對收益影響可忽略——「代價」實質為零。混合方案省下的少量 API 呼叫，換來額外的
    判斷邏輯與一個需要調校的容忍值參數，不划算。日後若真的觀察到問題再優化為混合方案。
  - spread 選百分比遞增而非固定增量：固定增量（如每階 +0.00003）在市場低利時相對幅度過大
    （底價 0.00015 時第三階比底價高 40%），高階根本不可能成交；百分比遞增可讓階梯隨利率
    水準自動縮放。
  - maxtolend 選單輪量控版：使用者目前錢包資金 100% 用於 USD 放貸、無其他用途，真實總曝險
    版本每輪要多打兩個端點，而該功能對現階段並無實益；先把設定介面與縮量邏輯做好，日後要
    升級成真實曝險版時只需替換基數來源。
- 考慮過的替代方案：「純補差額」（不動舊掛單，只掛新增餘額）—— 放棄，因為利率落後的舊單會
  永久卡住資金；「偏離容忍值才重掛」的混合方案 —— 放棄，理由見上；spread 固定增量 —— 放棄，
  理由見上；maxtolend 含已放貸真實曝險版 —— 延後，待 M3 建好 DB 與部位查詢後再評估升級。
- 影響範圍：`modules/lending_strategy.py`（`build_offer_plan()` 重寫，新增
  `_apply_lend_limit()`／`_resolve_spread_count()`／`_split_amount()`／`_resolve_duration()`）、
  `main.py`（`run_once()` 新增取消步驟與 `cancel_settle_seconds` 參數）、`config.yaml`
  （新增 `min_loan_size_usd`／`spread_count`／`spread_step_pct`／`max_to_lend_usd`／
  `max_percent_to_lend`／`engine.cancel_settle_seconds`，移除 `split_threshold_usd`）、
  `.github/workflows/python-app.yml`（smoke test 的 `run_once()` 呼叫補
  `cancel_settle_seconds=0`）。完成 M2 全部項目，`cancel_active_offers()` 從此被主迴圈呼叫，
  解除 CHANGELOG「未被呼叫」的 Known Issue。

## D012 — 每個 milestone 一條獨立分支，完成即合併進 main
- 日期：2026-07-26
- 決策：
  1. **每個 milestone（M1／M2／M3／M4）開一條獨立分支**，命名慣例
     `feature/m<N>-<主題>`（如 `feature/m2-strategy-and-risk`）；純文件同步用
     `docs/<主題>`。
  2. **milestone 完成且驗證通過後立刻合併進 main**，不在舊 milestone 的分支上繼續做下一個
     milestone 的工作。下一個 milestone 一律從最新的 main 開新分支。
  3. 合併採 `--no-ff`，保留分支結構，讓 `git log --graph` 能一眼看出每個 milestone 的範圍。

  > **2026-07-27 更正（見 D014）**：第 2 點的「合併」方式改為 **push 分支 → 開 GitHub PR →
  > 由 PR 合併進 main**，不再在本地直接合併 main 後推送。下方「踩坑紀錄」的成因也一併更正。
- 原因：M1 與 M2 的工作原本混在同一條分支 `fix/m1-frr-and-loop` 上（該分支除了 M1 的
  `get_frr`／主迴圈，還累積了 `cancel_active_offers`、`create_loan_offer` 兩個屬於 M2 的
  commit），造成無法分辨哪個 commit 屬於哪個 milestone，回頭追查與 code review 都困難。
  使用者明確要求改採「一個 milestone 一條分支、完成即合併」的流程。
- 踩坑紀錄（本次實際遇到，日後務必注意）：PR #5 合併 `fix/m1-frr-and-loop` 時只帶進
  `9bb7027`，`479a6e2` 與 `e942310` 都留在分支上沒進 main。因此**合併後要用
  `git log <舊main>..<新main>` 或 `git merge-base --is-ancestor` 實際比對遠端 main 是否真的
  包含所有預期的 commit**，不能只看 PR 顯示「已合併」。

  > **2026-07-27 更正**：原本把成因寫成「GitHub PR 的合併範圍只涵蓋建立 PR 當時分支上的
  > commit，事後 push 的不會被納入」，這個說法不正確。GitHub PR 追蹤的是 head 分支的最新
  > 狀態，PR 開啟期間再 push 的 commit **會**出現在 PR 裡並被一併合併。PR #5 少帶 commit
  > 的真正成因，是那兩個 commit 在 PR 被合併的時間點還沒推到遠端分支上。
  > **正確的預防做法**：確認所有 commit 都已 `git push` 到分支之後，才建立／合併 PR；
  > 合併後仍照上述方式實際比對。
- 附帶做法：若某條分支尚未推送過，重整（`git rebase --onto`）是安全的，可用來把分支移到
  正確的基底上；重整後必須用 `git diff <重整前> <重整後>` 確認內容零差異，並重跑驗證。
- 考慮過的替代方案：全部工作都在一條長命分支上做完再一次合併 —— 放棄，milestone 邊界會完全
  消失；每個 milestone 都走 GitHub PR 流程 —— 未排除，但需注意上述「PR 只帶部分 commit」的
  陷阱，本次改為本地 `--no-ff` 合併後直接推送。
- 影響範圍：日後所有開發流程；M3 起一律從 main 開
  `feature/m3-data-and-observability` 之類的新分支。`fix/m1-frr-and-loop` 已是完成後的殘留
  分支，可刪除。

## D013 — M3 可觀測性四項設計：固定檔名輪替、掛單不重試、收益表先建不填、告警去重
- 日期：2026-07-27
- 決策：
  1. **日誌改固定檔名 + `RotatingFileHandler`**，移除 `utils/logger.py` 與 `start.sh` 兩處
     在檔名附加啟動時間戳的邏輯。
  2. **`with_retry` 攔的是我們自己的 `RetryableError`，不是 ccxt 原始例外**；且
     **`create_loan_offer()` 刻意不套用重試**，只有 `get_available_balance()`／`get_frr()`／
     `cancel_active_offers()` 套用。
  3. **`earnings_daily` 本輪只建表與備妥 `upsert_daily_earning()` 介面，不接資料來源。**
  4. **連續失敗告警只在「剛跨過門檻」與「剛恢復」各送一次**；`SkipCycleError` 視為成功，
     不累計失敗；失敗次數寫進 `bot_state.consecutive_failures` 而非只存記憶體。
- 原因：
  1. 時間戳命名是「跑一次就結束」時代的產物。M1 之後程式已是 `while True` 常駐，若每次
     重啟都另起一串新檔案，`backup_count` 只管得住本次啟動那一串，長期下來等於沒有上限——
     跟導入 rotation 的目的直接矛盾。
  2. `exchange_client.py` 各方法早已把 ccxt 例外分類成 `RetryableError`／`FatalError`
     （見 D009／D010），decorator 只要攔分類後的結果，就能一行套用而不動內部邏輯；
     `FatalError`（金鑰無效、權限不足）重試沒有意義，直接往外拋。
     **掛單不套重試是風控考量**：掛單不是冪等操作，若請求其實已送達 Bitfinex、只是回應
     逾時，重試就會重複掛單，實盤下是真的多借出去。失敗改由下一輪的「全取消重掛」
     （D011）自然補回，最多損失一輪的掛單機會，代價遠低於重複放貸。
  3. 收益資料在 `exchange_client.py` 裡沒有任何來源——需另走 Bitfinex
     `/v2/auth/r/ledgers/{ccy}/hist` 查利息入帳，且 dry-run 模式下無從驗證正確性。
     先備妥 schema 與介面，避免 M3 範圍膨脹成半套的實盤功能。
  4. 交易所若長時間異常，每輪都送告警會把通知管道洗版，反而讓人忽略。失敗次數落 DB
     是為了讓未來的容器 healthcheck 不必啟動 Python 就能判斷健康狀態。
     `SkipCycleError` 不算失敗，是因為能走到那個判斷，代表交易所 API 本身是通的。
- 考慮過的替代方案：
  - `TimedRotatingFileHandler`（每日切檔）—— 未採用，單日暴量時檔案大小仍無上限；
    真正要防的是磁碟被塞爆，依大小切更直接。
  - 掛單失敗時先查詢 funding offers 確認沒成功再重試 —— 最安全但最複雜，且 dry-run 下
    驗證不到，留待實盤前再評估。
  - 失敗計數只存記憶體 —— 較簡單，但重啟後歸零，且外部無從觀測。
- 影響範圍：`utils/logger.py`、`start.sh`、`api/rate_limiter.py`（新增）、
  `modules/exchange_client.py`、`db/`（新增）、`main.py`、`config.yaml`、`.gitignore`、
  CI workflow 與 `docker-compose.yml`（新增 `/app/data` volume）。

## D014 — 合併方式改走 GitHub PR，不在本地直接合併 main
- 日期：2026-07-27
- 決策：milestone 分支完成後，流程固定為 **push 分支 → 在 GitHub 開 PR → 由 PR 合併進
  main → 本地 `git pull` 同步**，取代 D012 原本的「本地 `--no-ff` 合併 main 後推送」。
  D012 的其餘內容（一個 milestone 一條分支、命名慣例、合併後實際比對 commit）維持不變。
- 原因：使用者明確要求走 PR 流程。PR 留下可回顧的審查紀錄與討論串，且合併前會先跑 CI 的
  `test` 與 `integration` 兩個 job（`pull_request` 事件會觸發；`deploy` 不會，因為它的條件
  是 `github.ref == 'refs/heads/main'`）——等於部署前多一道自動關卡，本地直接合併則會
  完全跳過這道檢查。
- 執行順序上的注意事項：**所有 commit 必須先 push 到分支，才建立／合併 PR**
  （見 D012 更正後的踩坑紀錄）。
- **2026-08-02 補充（使用者指示，兩條）**：
  1. **絕對不直接改 main**。任何新功能、修正、甚至純文件更新，都要先從最新的 main
     開一條新分支再動手；動手前先確認自己站在哪條分支。
  2. **PR 沒問題且已順利合併進 main 之後，一律把本地切回 main 並同步**
     （`git checkout main && git merge --ff-only origin/main`），不要繼續停在已合併的
     分支上，下一條分支一律從最新的 main 開。

  兩條的共同原因是同一個：停在舊分支或直接站在 main 上，都很容易在下一段工作時改錯
  地方——D014 的踩坑紀錄裡已經發生過一次「沒確認自己站在哪條分支就直接編輯 main 工作區」。
  切回 main 前仍照本條與 D012 的要求，先實際比對 commit 是否真的都進了 main。
  這兩條慣例同時寫入 `.ai-brain/CORE.md` 的「程式慣例 / Git / PR 流程」，跨專案適用。
- 踩坑紀錄（本次實際遇到）：M3 一度已依 D012 在本地完成 `--no-ff` 合併，經使用者指正後改走
  PR 流程。因該合併尚未推送，以 `git reset --hard origin/main` 退回即可，分支上的 commit
  完好無損。**退回後務必確認自己站在哪條分支**——當下 HEAD 停在 main，若直接編輯文件會改到
  main 的工作區而非分支（本次即發生，已還原後切回分支重做）。
- 考慮過的替代方案：維持本地合併（較快、少一次來回）—— 放棄，會跳過 PR 的 CI 關卡，
  也沒有審查紀錄。
- 影響範圍：M3 起所有 milestone 的合併流程；D012 第 2 點作廢並改以本條為準。

## D015 — M4 拆成子分支、測試先於重構、整合測試可打公開唯讀端點
- 日期：2026-08-01
- 決策：
  1. **M4 不套用 D012 的「一個 milestone 一條分支」，改拆成 3~4 條子分支**，各自開 PR：
     `test/m4-test-suite`（測試）→ `refactor/m4-layering`（分層搬遷）→
     `deploy/m4-podman`（容器化收斂）→ `feature/m4-line-messaging`（LINE 改寫）。
  2. **順序上先補測試、再做搬遷**。
  3. **整合測試可以打 Bitfinex 公開唯讀端點**（`GET /v2/ticker/f{CCY}`），
     連不上時 `pytest.skip` 而非 fail；**絕不觸及任何需要簽章的端點**，
     不查帳戶、不掛單、不取消掛單。
  4. **CI 的測試步驟拿掉 `|| true`**，測試失敗必須擋下合併。
- 原因：
  1. M4 涵蓋重構、測試、部署、LINE 四大塊，全放同一條分支會讓 PR 大到無法審查，
     milestone 邊界反而更模糊——這與 D012 想解決的問題其實是同一個。更關鍵的是
     LINE 那塊被「使用者尚未申請 LINE Developers Channel 憑證」卡住，綁在一起會
     讓已完成的三塊也跟著無法合併。
  2. 搬遷是大範圍的機械式改動，最怕搬到一半才發現行為變了。先有測試，搬完重跑一次
     就能證明沒搬壞；反過來做則整段過程沒有回歸保護。代價是搬遷時 import 路徑要
     連測試一起改，但那是機械式的、且有測試立刻驗證。
  3. 這個專案最大的已知風險就是「ccxt 對 Bitfinex funding 的支援不可靠」（見 D010 與
     `.project-docs/CCXT_BITFINEX_API_INVESTIGATION.md`）。`get_frr()` 走的是 implicit API
     加陣列索引取值，ccxt 或 Bitfinex 任一端改了回應格式，離線測試完全看不出來，
     只會在實盤那一刻爆掉。公開端點唯讀、不需金鑰、不碰資金，是成本最低的守門方式。
     連不上就 skip 是為了不讓 CI 因外部服務抖動變紅燈——紅燈若常態化，真正的失敗
     就會被忽略。
  4. 有測試卻用 `|| true` 吞掉結果，等於白寫：CI 永遠綠燈，壞掉的程式碼照樣合併。
- 考慮過的替代方案：
  - 維持單一 `feature/m4-...` 分支 —— 放棄，PR 過大且會被 LINE 憑證卡住。
  - 整合測試全離線、一律用假物件 —— 放棄，CI 最穩定但看不出 ccxt／Bitfinex 端點變更，
    等於把這個專案最大的風險留到實盤才發現。
  - 用環境變數（如 `BFX_LIVE_TESTS=1`）控制是否打真實 API —— 未採用，多一層設定要維護；
    改以 pytest marker（`-m "not live"`）達到同樣的離線執行效果，不必動環境。
  - 先搬遷再補測試 —— 放棄，測試檔的 import 只要寫一次，但搬遷過程完全沒有回歸保護。
- 影響範圍：M4 的分支與 PR 流程（D012 第 1 點在 M4 例外處理，第 2 點仍依 D014 走 PR）、
  `.github/workflows/python-app.yml`、新增 `tests/`、`pytest.ini`、`requirements-dev.txt`。

## D016 — 容器可靠性四項：重啟次數上限、離開碼語意化、日誌改讀掛載檔、健康檢查只看心跳
- 日期：2026-08-02
- 背景：M3 起機器人已能常駐運行，但等於沒有安全網——`podman run` 完全沒有 `--restart`
  參數（崩了就永遠躺平）、`docker-compose.yml` 卻寫 `restart: unless-stopped`（兩邊不一致）、
  `podman logs` 一直取不到內容、沒有任何機制能看出「行程活著但已經不巡檢」。
  這四件事彼此牽動，拆開做會做出互相打架的設計，因此一次收斂。
- 決策：
  1. **重啟策略採 `--restart=on-failure:3`**，正式部署與 `docker-compose.yml` 都改成
     `on-failure` 系列，不再用 `unless-stopped`。
  2. **`main.py` 的離開碼語意化為三種**：`EXIT_OK = 0`（收到中斷訊號的正常結束）、
     `EXIT_UNEXPECTED = 1`（未分類的例外）、`EXIT_FATAL = 2`（金鑰無效這類人不介入
     就不會好的錯）。並且**退出前一律把原因寫進 `bot_state.last_action`**，
     連未預期的例外也在最外層攔一次，寫日誌與 DB 後才結束。
  3. **容器日誌驅動改 `k8s-file`（搭配 `--log-opt max-size=10mb`）**，CI 的「取得最近
     容器日誌」改成讀掛載出來的 `logs/bfx_lending_bot.log`，`podman logs` 降為備援。
  4. **新增 `scripts/healthcheck.py` 作為容器 healthcheck**，只讀 `bot_state.last_run_at`
     判斷心跳是否過期（預設門檻為巡檢間隔的 3 倍 + 60 秒，可用
     `engine.health_max_silence_seconds` 覆寫），**刻意不看 `consecutive_failures`**，
     且**這一輪先不加 `--health-on-failure=restart`**。
- 原因：
  1. `unless-stopped` 與 `always` 會和「致命錯誤直接退出」打架：API 金鑰無效時變成
     啟動→退出→啟動的無限迴圈，日誌被洗版，真正的原因反而更難找。完全不設 restart
     則是另一個極端——一次偶發崩潰就讓機器人靜靜躺平到有人發現為止。次數上限是這兩者
     之間唯一站得住的位置：能自行恢復的問題三次內大多會過，過不了的問題重開再多次也沒用。
  2. restart policy 只看離開碼是不是 0，分不出上面那三種，所以**節流靠次數、不靠離開碼**；
     離開碼的價值在給人看——`podman inspect` 的 `.State.ExitCode` 是 2 就直接去查設定與金鑰，
     是 1 就去翻 traceback。退出前落帳則是因為容器收掉後日誌不一定拿得到（見第 3 點），
     DB 掛在主機上，是唯一一定留得下來的地方。
  3. 預設的 `journald` 在這台 rootless 環境實際取不到內容（2026-08-02 確認），CI 那步
     等於空跑了好幾個月。改用 `k8s-file` 讓 `podman logs` 恢復可用，但真正該讀的是程式
     自己寫的日誌檔：它有輪替、格式完整，而且**容器被收掉之後檔案還在**——容器崩潰那一刻
     的現場，恰好就是最需要日誌的時候。`max-size` 是順手補的，免得為了修日誌又製造出
     一個無限長大的檔案。
  4. `consecutive_failures` 高代表交易所連線或金鑰有問題，機器人本身正在正常工作，
     **重啟容器不會讓它變好**，那條路已經由 `FailureTracker` 的告警負責；健康檢查要回答的
     是另一個問題：「這個行程還在動嗎」。門檻取 3 輪是為了讓單輪的網路延遲、取消掛單的
     等待、交易所偶發變慢都不會誤判。先不開自動重啟，是因為誤判的代價（重啟一個好好的
     容器）目前沒有實測資料可判斷發生率——先讓 `podman ps` 顯示 healthy/unhealthy 累積
     一段觀察期，確認判斷準確再開，已列入 TASKS.md。
- 考慮過的替代方案：
  - 維持 `restart: unless-stopped` —— 放棄，就是它造成無限重啟迴圈的疑慮。
  - 致命錯誤改成離開碼 0，讓 `on-failure` 自然不重啟 —— 放棄。語意上騙人，
    未來任何看離開碼的監控都會把「金鑰無效停機」當成正常結束。
  - 改用 `podman generate systemd` + `StartLimitBurst` 做節流 —— 放棄（至少這一輪）。
    效果與 `on-failure:3` 相同，卻多一層部署元件要維護，也讓 CI 的部署步驟不再是
    「一行 podman run 就重現得出來」。`systemd/bfx-lending-bot.service` 因此維持
    本機測試用途，不進正式路線。
  - healthcheck 把 `consecutive_failures` 也算進去 —— 放棄，理由同上，那是外部問題。
  - healthcheck 直接執行一次真的巡檢來確認活著 —— 放棄，健康檢查有副作用是大忌，
    而且會真的去打交易所 API。讀 DB 是唯讀、零副作用、也不需要金鑰。
- 影響範圍：`.github/workflows/python-app.yml` 的 deploy job、`docker-compose.yml`、
  `main.py` 的離開碼與退出路徑、新增 `scripts/healthcheck.py` 與
  `tests/unit/test_healthcheck.py`、`tests/functional/test_main_exit_codes.py`。
  `config.yaml` 未新增鍵；`engine.health_max_silence_seconds` 是可選的覆寫，不設就用預設。

### ⚠️ 2026-08-02 驗收後更正（PR #10 合併後實測）

**本條決策的第 3 點根因判斷是錯的，第 1 點的效果沒有真正生效。** 更正如下，
細節與修法排序見 TASKS.md 的「2026-08-02 部署盤查發現的問題」A1～A6。

- **錯在哪**：原文把「`podman logs` 取不到內容」歸因為「預設的 `journald` 在這台
  rootless 環境實際取不到內容」。實測後確認**真正原因是容器的 conmon 行程不存在**——
  conmon 才是負責把容器 stdout/stderr 寫成日誌、並在容器退出時執行 restart policy 的角色。
  它被 CI 的 deploy job 收尾時一併清掉了（容器建立於 17:35:35，job 於 17:35:42 完成）。
  換成 `k8s-file` 之後 `podman logs` 依然是空的，因為根本沒有人在寫。
- **連帶影響第 1 點**：`--restart=on-failure:3` 參數確實有正確設定在容器上
  （`podman inspect` 看得到），但 **conmon 不在就沒有人觸發重啟**，所以自動重啟
  從頭到尾沒有生效過。以對照實驗證實：同樣參數的兩個測試容器，conmon 活著的
  退出後重啟（RestartCount=1），conmon 被 `kill -9` 的完全不重啟（RestartCount=0），
  而且 `podman ps` 還會顯示已死的容器為 `running`。
- **仍然成立的部分**：
  - 第 2 點（離開碼語意化 + 退出前落帳）與其理由完全不受影響。
  - 第 3 點的後半段——**CI 改讀掛載出來的 `logs/bfx_lending_bot.log`**——不但成立，
    而且事後看正是唯一真的有效的那一半：程式自己寫的日誌檔跟 conmon 無關，一直正常。
  - 第 4 點（healthcheck 只看心跳、唯讀、不自動重啟）不受影響。實測 healthcheck
    由獨立的 systemd timer 執行 `podman healthcheck run`，**不依賴 conmon**，
    每 60 秒正常執行、離開碼 0。
  - 「放棄 `podman generate systemd`」這個判斷則需要重新考慮：當時的理由是
    「效果與 `on-failure:3` 相同、卻多一層部署元件」，但現在已知在這個 CI 部署方式下
    `on-failure:3` 效果是零，前提不成立。修法方向見 TASKS.md A1。
- **一個被推翻的擔憂**（記下來免得下次又繞回去）：曾懷疑「conmon 不在，沒人讀
  stdout pipe，寫滿 64KB 後 Python 會阻塞、機器人會卡死」。**實測不成立**——
  測試容器灌了 200KB 輸出仍正常跑完並以離開碼 0 結束。機器人不會因此卡死。
- **教訓**：這次犯的錯是「看到症狀就近取一個聽起來合理的解釋（rootless + journald），
  改了設定、測試容器看起來好了，就當作修好」。當時的驗證用的是**自己手動起的容器**，
  而問題只在 **CI 起的容器**上發生，等於驗證環境與故障環境根本不同。
  往後驗證部署層的修正，要在真正的部署路徑上驗收，或至少確認驗證環境與實際環境的差異。

## D017 — 容器生命週期改由 systemd（Quadlet）管理，不再由 CI job 直接 `podman run`
- 日期：2026-08-02
- 背景：D016 補上的四項可靠性措施，合併後驗收發現其中兩項（自動重啟、容器日誌）
  **實際上從不生效**。根因不在程式碼也不在參數，而在部署方式：CI 的 deploy job
  用 `podman run -d` 起容器，job 收尾時 runner 會清掉自己的行程樹，容器的 conmon
  一併被殺。conmon 是 podman 為每個容器配的看門人，負責寫容器日誌、以及在容器退出時
  依 `--restart` 規則重新拉起——它不在，這兩件事就都不會發生。
  問題自 M3 起就存在（PR #8 那版同樣沒有 conmon），只是到 PR #10 才查清楚。
- 決策：
  1. **容器由 systemd --user 的 Quadlet 單元啟動**，單元檔
     `systemd/shuyu-lending-bot.container` 納入版控，CI 每次部署複製到
     `~/.config/containers/systemd/` 後 `daemon-reload`。主機上那份是產物，不要手改。
  2. **CI 的 deploy job 只做三件事**：`podman build`、更新單元檔、
     `systemctl --user restart`。不再自己 `podman run`，conmon 因此落在
     `user@1000.service` 的 cgroup 底下，與 job 的生命週期脫鉤。
  3. **開啟 linger**（`loginctl enable-linger shuyu`）。`systemd --user` 原本只在使用者
     還有登入 session 時存在，沒有 linger 的話所有 session 結束後容器會一起消失。
     這是第 1 點成立的前提。
  4. **重啟節流改用 systemd 語意**：`Restart=on-failure` + `StartLimitIntervalSec=1800`
     + `StartLimitBurst=4`（30 分鐘內最多 4 次啟動），並**移除 podman 端的
     `--restart=on-failure:3`**——兩者會打架。順帶解掉 D016 留下的疑點：
     podman 的 `on-failure:N` 計數何時重置沒有明確定義，systemd 的「時間窗內幾次」清楚得多。
  5. **`RestartPreventExitStatus=2`**：D016 當時寫「restart policy 看不到離開碼，
     只能靠次數上限節流」。改由 systemd 管理後這個限制消失了——**systemd 看得到離開碼**，
     可以直接表達「`EXIT_FATAL=2` 就不要重啟」。這是換過來額外拿到的好處。
  6. **掛載目錄的 `mkdir -p` 從 CI 移進單元的 `ExecStartPre`**：開機自動啟動與任何
     非 CI 觸發的重啟也才會成立，不必依賴「一定有跑過一次 CI」。
  7. **CI 新增「驗證容器生命週期真的由 systemd 接管」步驟**，斷言三件事：服務為 active、
     conmon 行程存在、`podman logs` 取得到內容。任一項不成立就讓部署紅燈。
- 理由：方向 B（想辦法讓 conmon 在 job 結束後存活，例如清掉 runner 追蹤子行程用的環境變數）
  改動只有一行，但屬於繞過 runner 的既定行為，runner 改版就可能再壞一次，
  而且不解決「主機重開機後容器不會自己起來」。Quadlet 是 podman 官方現行做法
  （`podman generate systemd` 已標為 deprecated），一次把常駐、開機自動啟動、
  重啟節流、離開碼語意都放進同一個地方表達。
- 驗證（改用對照實驗，而不是只看設定檔——這是 D016 的教訓）：
  - 以測試用 Quadlet 單元跑「印一行 → 睡 5 秒 → 以指定離開碼結束」：
    離開碼 1 → `ExecMainStatus=1`、重啟 4 次後觸及 StartLimitBurst 停在 failed；
    離開碼 2 → `ExecMainStatus=2`、`NRestarts=0`，**完全不重啟**。
    這同時證實了離開碼確實會透過 `--sdnotify=conmon` 傳回 systemd。
  - **直接針對根因的對照實驗**：用 `systemd-run --user --scope` 建一個模擬 CI job 的
    scope，在裡面 `systemctl --user start` 服務，然後把整個 scope 的行程樹 SIGKILL 掉。
    結果 conmon 存活，cgroup 為
    `user@1000.service/app.slice/shuyu-lending-bot.service/runtime`，容器續跑。
  - 正式容器實際接管後：服務 active、conmon 存在、**`podman logs` 終於有內容**
    （自 M3 以來第一次）、`podman inspect` 的重啟策略為 `no`（已交給 systemd）、
    健康狀態 healthy、DB 心跳與掛單累計正常。
- 影響：`docker-compose.yml` 僅存本機測試用途，其註解同步說明「次數節流與離開碼判斷
  只在正式部署那側由 systemd 表達」，compose 兩者都做不到。
  `systemd/bfx-lending-bot.service`（非容器、直接跑 `start.sh` 的舊單元）維持原狀，
  用途仍是本機測試，去留待確認。

### ⚠️ 2026-08-02 PR #12 合併後驗收補充

**先講結論**：D017 的核心修法（容器改由 systemd 管理）**在真正的部署路徑上驗證通過**，
沒有需要更正的地方。以下補充兩點，一點是驗收證據、一點是自我修正。

**1. 正式部署路徑的驗收結果（這次有做對）**

PR #12 合併後由 CI 重新部署（容器建立於 21:25:27，非手動啟動），待 deploy job 完全結束
之後再檢查——**conmon 仍然存活**，cgroup 為
`user@1000.service/app.slice/shuyu-lending-bot.service/runtime`。這是根因解除的直接證據：
舊做法下 conmon 正是在 job 收尾這一刻被清掉的。同時確認 `podman logs` 有內容、
服務 `active`／`Result=success`、容器 `Up (healthy)`、podman 端重啟策略為 `no`、
主機上的單元檔與 repo 內容一致、`loan_offers` 由 274 累積到 280（DB 跨部署保留）、
`default.target.wants/` 的開機自動啟動連結存在。

**2. 自我修正：D017 第 7 點的 CI 驗證步驟，比當初宣稱的弱**

原文寫「CI 新增『驗證容器生命週期真的由 systemd 接管』步驟……任一項不成立就讓部署紅燈」，
並把它當成防止迴歸的保險。**這個宣稱過頭了**：該步驟斷言的是「conmon 行程存在」與
「`podman logs` 取得到內容」，而這兩件事**在舊的壞掉做法下同樣會通過**——舊做法的 conmon
是在 job 收尾那一刻才被清掉，而檢查跑在 job 執行期間，那時它還活著。

也就是說，這道檢查擋得住「服務起不來、映像不存在、log driver 壞掉」，
但**擋不住「有人把部署改回 `podman run`」**，而那正是它被加進來要防的事。

修法很小（比對 conmon 的 cgroup 是否屬於 `shuyu-lending-bot.service`，這個差異在 job
執行期間就看得出來），細節與可直接照抄的程式碼片段記在 **TASKS.md B1**，
排在分支 `fix/m4-audit-findings`。在那之前，**不要把這道檢查當成迴歸保險看待**。

**教訓（與 D016 那條同一類，但這次早了兩個 milestone 發現）**：D016 的錯是「驗證環境
與故障環境不同」，這次的錯是「**驗證時機與故障時機不同**」——檢查跑在故障發生之前的時間點，
所以永遠看不到故障。設計自動化檢查時，除了問「這個檢查會不會通過」，
還要問「**如果故障真的發生了，這個檢查會不會失敗**」。

**3. 一併記下的既有缺口**

`StartLimitBurst` 用盡、systemd 放棄重啟之後，單元停在 `failed` 而**沒有任何通知**。
這不是 D017 造成的（舊的 `--restart=on-failure:3` 同樣沒有通知，只是它從未真的執行過），
但 D017 讓重啟機制第一次真的會運作，這個缺口也就第一次變得有意義。
實單前應補上，見 **TASKS.md B2**（會與 A6「不健康就自動重啟」互相牽動，建議一起設計）。

### 2026-08-16 補充：純文件變更不觸發部署（TASKS.md P1-3）

D017 把 deploy job 收斂成「`podman build` → 更新單元 → `systemctl --user restart`」，
當時只在意「重啟要確實發生」，**沒有問過「哪些推送值得重啟」**。真金上線之後這個缺口
才有代價：`restart` 會讓機器人重新跑一輪完整流程，也就是**把交易所上的掛單取消掉、
再重掛一筆新的**。中間有一段訂單簿上沒有我們單子的空窗，同利率下的時間優先權也歸零。

而這個專案幾乎每天都在同步 `.project-docs/`。**用一次純文件 commit 去重置一張正在排隊
的單子**，在「我們這個價位的成交是陣發的」（3.7 小時的 23 個時段只有 3 個時段有成交）
這個前提下特別不划算——等於自己拉長 P1 的驗證期。

**做法**：新增 `changes` job 比對這次推送的變更路徑，全部落在 `.project-docs/` 就輸出
`docs_only=true`，`deploy` job 以 `needs.changes.outputs.docs_only != 'true'` 擋下。

**三個刻意的選擇**：

1. **擋在 job 層，不是 step 層**。GitHub 沒有 per-job 的路徑過濾，直覺做法是在 deploy
   的每個步驟加 `if:`——但那有六個以上的步驟，**漏掉任何一個就變成「部署做到一半」**
   （例如映像沒重建卻重啟了服務），比乾脆不部署更糟。job 層是全有全無的。
2. **不用 `on.push.paths-ignore`**。那會連 `test`／`integration` 一起跳掉。若分支保護
   設了必要檢查（required status check），**被跳過的檢查會永遠停在未完成而擋住合併**
   ——本來想省事，結果變成每次改文件都要手動繞過保護。現在測試照跑，只有部署被擋。
3. **判斷不出來一律照常部署（fail-open）**。`workflow_dispatch` 沒有「上一版」、
   force push 時 `github.event.before` 是全 0、淺層 clone 可能撈不到基準 commit——
   這些情況全部回傳 `false`。理由是兩種錯的代價不對稱：**多部署一次只是白重啟一輪，
   少部署一次卻是程式已經改了但機器人還在跑舊版，而且不會有任何人發現**。
   這與 D023「假警報比漏報更難修」是同一種取捨方向——選那個會被人察覺的錯。

**兩個實作上會踩的坑**（都已處理）：`actions/checkout@v4` 預設 `fetch-depth: 1`，
`HEAD~1` 根本不在本地，退路會失效，所以要 `fetch-depth: 2`；以及 `[skip ci]` 要加在
**GitHub 產生的合併 commit 訊息**上才有用，加在分支自己的 commit 上不會生效
（CI 判斷看的是被推上 main 的那個 commit）——這是這道改動落地前的暫時解。

**驗證**：把偵測邏輯抽出來以 `bash -e -o pipefail` 跑過九種情境（只改文件／只改程式／
混合／新增檔／刪除檔／`before` 全 0／`before` 撈不到／`workflow_dispatch`／
**GitHub 合併 commit**），輸出全部符合預期。最後一種是實際會發生的路徑，
先前寫過的 CI 斷言吃過「驗證時機與故障時機不同」的虧（見上方 D017 補充第 2 點），
所以這次特地把真正的合併情境也建出來測。

## D018 — CI 的容器日誌斷言改為合併 stderr，並以 cgroup 歸屬判斷 systemd 是否真的接管
- 日期：2026-08-09
- 背景：PR #13（純文件同步）合併後，deploy job 在「驗證容器生命週期真的由 systemd 接管」
  這一步紅燈，訊息是「30 秒內 podman logs 仍然沒有內容，conmon 或 log driver 有問題」。
  實際查證後，**這三件事全都是好的**：conmon 存在（PID 4185319）、cgroup 為
  `user@1000.service/app.slice/shuyu-lending-bot.service/runtime`、`podman logs` 有 11 行內容。
  壞的是檢查本身。
- 根因（三件事湊起來，缺一不可）：
  1. `utils/logger.py` 的 `logging.StreamHandler()` 不帶參數，**Python 的預設是 `sys.stderr`**，
     所以機器人所有日誌都走容器的 stderr。
  2. 程式碼裡沒有任何 `print()`，**容器的 stdout 從頭到尾是空的**。
  3. 檢查寫的是 `$(podman logs --tail=5 shuyu-lending-bot 2>/dev/null)`——`$( )` 只捕捉
     stdout，`2>/dev/null` 又把 stderr 丟掉，**等於親手扔掉自己要找的東西**。
- 影響範圍：這道檢查**從加進來的那一刻起就不可能通過**，也就是 deploy job 自 PR #12
  合併（2026-08-02）以來一路是紅的。當時的驗收之所以看起來正常，是因為在終端機下手動跑
  `podman logs`，stderr 會直接顯示在螢幕上，肉眼看得到內容。
  **機器人本身不受影響**——部署流程在這一步之前就已經把服務重啟完成，容器一直正常運行。
- 決策：
  1. **日誌斷言一律合併 stderr**：改用 `CONTAINER_LOGS=$(podman logs --tail=20 ... 2>&1)`。
     合併之後必須**另外確認 podman 本身的離開碼**，否則「no such container」這類錯誤訊息
     會被當成「有日誌」而誤放行——用 `if CONTAINER_LOGS=$(...) && [ -n "$CONTAINER_LOGS" ]`
     同時要求「指令成功」與「輸出非空」。
  2. **不動 `utils/logger.py`**：日誌走 stderr 是 Python logging 的預設行為，本身沒有錯，
     `podman logs` 與掛載出來的 `logs/bfx_lending_bot.log` 兩邊都收得到。
     為了讓一道寫錯的斷言通過而改動機器人的輸出行為，是把因果關係倒過來。
  3. **一併完成 TASKS.md B1**（同一個步驟，分開改沒有意義）：conmon 的判斷從「行程存不存在」
     改為「**cgroup 是否屬於 `shuyu-lending-bot.service`**」。原本印出 cgroup 卻沒拿去比對，
     現在補上 `case` 判斷。
- 驗證（先做對照實驗再合併，記取 D016／B1 的教訓）：
  | 情境 | 期望 | 實測 |
  |---|---|---|
  | 正式容器（systemd 啟動） | 通過 | 離開碼 0，日誌 11 行正常印出 |
  | 假容器（直接 `podman run` 起，模擬舊做法） | 紅燈 | 離開碼 1，被 cgroup 判斷擋下 |

  第二個情境的關鍵在於：**那個假容器的 `podman logs` 是有內容的**，所以它是被
  「啟動方式不對」擋下來的，不是碰巧因為沒日誌而失敗——這正是 B1 要的鑑別力。
- **教訓（同一系列的第三條）**：D016 是「驗證**環境**與故障環境不同」，
  B1 是「驗證**時機**與故障時機不同」，這條是「驗證**管道**與資料實際流經的管道不同」。
  三次都是同一個病：檢查沒有在檢查它以為在檢查的東西。
  往後寫自動化斷言，除了「它會不會通過」，一定要再問「**它讀的是不是真正那份資料**」，
  而且**要在故障情境下實際跑一次看它會不會失敗**，不能只在正常情境下看到綠燈就收工。

## D019 — 退出路徑的落帳不得改變離開碼；資料庫路徑一律以專案根目錄解析
- 日期：2026-08-09
- 背景：PR #10 盤查時在程式碼層發現、當時刻意延後的三項小缺陷（TASKS.md A3～A5）。
  三項都不擋小額實單，但兩項與「部署真實會發生的故障」直接相關，因此在
  `refactor/m4-layering` 之前先清掉。
- 決策一（A3）：**退出路徑上的落帳與收尾動作，一律不得影響離開碼與通知**。
  - 抽出 `main._record_exit_reason(logger, repository, reason)`，內部包 `try/except`，
    寫不進去就只記日誌。三條退出路徑（啟動檢查失敗、`FatalError`、未預期例外）共用。
  - `finally` 的 `repository.close()` 同樣包起來——`finally` 拋出的例外會**取代回傳值**，
    離開碼直接變成 1 並印出一份跟真正死因無關的 traceback。
  - **為什麼這件事變重要了**：D017 之前，離開碼只是給人看的；現在 systemd 用
    `RestartPreventExitStatus=2` 直接依離開碼決定要不要重啟。落帳失敗把 `EXIT_FATAL`
    變成 `EXIT_UNEXPECTED`，systemd 就會去重啟一台「人不介入就不會好」的機器人。
    `FatalError` 那條路徑最危險：新例外會被外層 `except Exception` 接住，
    被誤判成「未預期的例外」。
  - **觸發條件不是假設**：「volume 掛載掉了」正是 M3 起部署一路失敗的根因，
    而那正是最需要看到原始錯誤的時候。
- 決策二（A4）：**`database.path` 的相對路徑一律相對於專案根目錄**，不是當下工作目錄。
  - `db/repository.py` 新增 `PROJECT_ROOT` 與 `resolve_db_path()`，`Repository.__init__`
    改用它；`config.yaml` 對這個鍵的註解本來就寫「相對於專案根目錄」，這是讓程式追上文件。
  - 一併讓 `BFX_DB_PATH` 在主程式端也有最高優先權。原本只有 healthcheck 認得它，
    設了就會兩邊分家——**是同一個缺陷的另一面**，不補等於只修一半。
  - **刻意不共用同一個函式**：`scripts/healthcheck.py` 要維持零專案相依、零副作用
    （`Repository` 一建立就會 mkdir 並建表，健康檢查絕不能有這種副作用）。
    改用「兩邊各自實作、但以測試釘住兩者結果必須相同」，兩支檔案的 docstring
    都寫明改一邊就要改另一邊。
  - **症狀為什麼值得防**：兩邊算出不同位置時，健康檢查會永遠回報「尚未寫入任何心跳」，
    而機器人其實跑得好好的，只是把 DB 建在別處。這種錯誤幾乎不可能聯想到路徑。
  - 容器內行為不變：`PROJECT_ROOT` 就是 `/app`，與原本的 `WORKDIR=/app` 結果相同。
- 決策三（A5）：`config.yaml` 的 `engine:` 補上註解掉的 `health_max_silence_seconds`
  與說明。可覆寫健康檢查門檻的選項只有程式碼知道，等於藏起來的設定。
- 驗證（延續 D018 的教訓，每一項都在「故障情境」下實跑過）：
  - A3：實際 `git stash` 掉 `main.py` 的修正後重跑，4 條新測試**全部失敗**
    （其中一條原封不動重現了「`finally` 拋例外把離開碼蓋掉」）；還原後全過。
  - A4：以 cwd=`/tmp` 實跑對照——修正前主程式算出 `/tmp/data/lending.sqlite3`、
    健康檢查算出專案目錄下的路徑（不一致）；修正後兩邊相同。
  - A5：以 `yaml.safe_load` 讀 config.yaml，確認註解狀態下門檻為預設的 1860 秒，
    取消註解設 1200 後覆寫生效。
  - 測試 255 → 265 項，全數通過。
- **順帶更正**：`main.py` 的模組 docstring 原本寫「重啟次數的節流交給
  `--restart=on-failure:N`」，這是 D017 之前的說法，該參數已移除。改為說明
  離開碼現在由 systemd 直接解讀，以及為什麼退出路徑不能改變它。

## D020 — systemd 失效告警（B2）與「不健康就處理」（A6）：以 `OnFailure=` + `HealthOnFailure=kill` 組合
- 日期：2026-08-09
- 背景：兩輪盤查剩下的最後一項。`Restart=on-failure` + `StartLimitBurst=4` 讓 systemd
  在「30 分鐘內 4 次啟動」後停手（刻意的——金鑰無效這類問題重開幾次都不會好），
  但停手之後單元停在 `failed` 而**不會有任何人知道**。A6 則是 D016 留下的觀察期決定。
- 觀察期結論（A6）：容器 healthcheck 自 2026-08-02 起每 60 秒執行一次、連續 7 天
  **沒有任何一次誤判**（`FailingStreak=0`，容器狀態一路 `healthy`）。據此決定開啟。
- 決策一（A6）：Quadlet 加 **`HealthOnFailure=kill`**，不是 `restart`。
  - `restart` 由 podman 自己把容器拉起來，會變成 podman 與 systemd 兩套重啟機制並存，
    各自計數、互相打架（TASKS.md A6 早就點出這個風險）。
  - `kill` 只負責「把不健康的容器殺掉」，殺完容器以非 0 離開碼結束，
    接手的是 systemd 的 `Restart=on-failure`——**重啟權威仍然只有 systemd 一個**，
    `StartLimitBurst` 的節流與 `OnFailure=` 的告警自動涵蓋這條路徑。
    podman 官方文件對 `kill` 的說明正是「與 systemd 整合最好」。
  - **實測確認離開碼是 137（SIGKILL）而不是 2**，所以 `RestartPreventExitStatus=2`
    不會誤擋這條路徑。這點很重要：若健康檢查觸發的退出剛好是 2，A6 會被 D017 的設定
    直接廢掉，而且不會有任何徵兆。
- 決策二（B2）：主單元 `[Unit]` 加 `OnFailure=shuyu-lending-bot-alert.service`，
  新增一般 systemd 單元（非 Quadlet）與主機端腳本 `scripts/notify_failure.py`。
  - **腳本在容器外執行**：容器可能正是壞掉的那一個，不能靠它來報告自己死了。
    因此只用標準函式庫、不 import 專案任何模組（與 `scripts/healthcheck.py` 同一原則）。
  - **絕不寫 `bot_state.last_run_at`**：那是心跳，機器人已經死了還更新它，
    等於偽造它還活著、騙過健康檢查。只更新 `last_action`。
  - **DB 以 `mode=rw` 開啟，檔案不存在就失敗、不建立**：DB 掛載掉正是可能觸發告警的
    原因之一，順手把它補回來只會蓋掉真正的問題。
  - **每個管道各自 try/except**，一個失敗不影響其他；一個都沒送成才回非 0
    （「以為有人會被通知、其實沒有」正是 B2 本身的問題，不能在告警機制裡再犯一次）。
  - LINE 推播位置已留好（`send_line_push`），憑證到位後填上即可。
- **⚠️ 實驗推翻的假設**：原本設計時認為「`OnFailure=` 只在單元真正進入 `failed` 時觸發，
  重試中途屬於 `auto-restart` 狀態不會誤觸發」，並據此把訊息寫死成「不會再自動重啟」。
  **實測證明是錯的**：`StartLimitBurst=3` 的單元一路失敗，告警被觸發 **4 次**
  （已重啟 0／1／2 次時各一次，最後放棄時一次）。中途那三次的訊息完全是錯的。
  - 修法：腳本自己查單元狀態分辨兩種情況——`SubState=auto-restart` 是重試中（ERROR），
    `ActiveState=failed` 是已放棄（CRITICAL）；查不到狀態時**一律當成已放棄**。
  - 查詢前先等 `BFX_ALERT_SETTLE_SECONDS`（預設 2 秒）讓狀態轉換走完，
    否則可能問到轉換前的舊狀態，把「正在重試」誤判成「已經放棄」。
    正式部署 `RestartSec=30`，這幾秒完全來得及。
  - **刻意不做靜音**：兩種代價不對稱——多送一則「正在重試」只是稍微吵，
    漏掉那則「已經放棄」等於整個 B2 白做。
- 驗證（兩個實機對照實驗，做完已清除所有殘留，正式服務全程未受影響）：
  | 實驗 | 驗的是什麼 | 結果 |
  |---|---|---|
  | 1. 一定失敗的測試單元 + `OnFailure=` | 告警鏈通不通、訊息誠不誠實 | 觸發 4 次：3 次 ERROR「重試中」+ 1 次 CRITICAL「已放棄」，日誌與 DB 都寫入，`last_run_at` 未被更動 |
  | 2. 健康檢查一定失敗的測試容器 + `HealthOnFailure=kill` | A6 與 systemd 的串接 | 容器被殺（離開碼 137）→ systemd 重啟 2 次 → 用盡次數停在 failed → 告警照常觸發 |

  第二個實驗等於把 A6 與 B2 串成一條完整的鏈驗過一次：**不健康 → 殺掉 → 重啟 →
  放棄 → 告警**，中間沒有斷點。
- CI 另加「驗證失效告警已接上」步驟：斷言主單元的 `OnFailure=` 真的指到告警單元、
  告警單元 systemd 讀得到、腳本檔存在。三個都問「systemd 眼中的實際狀態」而不是
  「repo 裡寫了什麼」——少複製一個檔或 `OnFailure=` 被刪掉都會當場紅燈。
  理由與 B1／B3 一樣：告警最糟的失敗方式是「以為接上了、其實沒有」。

## D021 — 分層搬遷：介面的價值在例外契約；名實不符的檔案以 docstring 標明
- 日期：2026-08-15
- 背景：M4 最後一條技術性分支。`modules/` 三個檔案搬到 `api/`／`strategies/`／`notify/`，
  並補上兩層抽象介面與 `core/bot_engine.py`。搬遷本身沒有懸念，有懸念的是下面四點。
- 決策一：**`api/base.py` 的 `ExchangeClient` 真正約束的是例外契約，不是方法簽章**。
  介面只列五個方法沒什麼價值（本來就只有一個實作），值得寫進介面文件的是：實作必須把
  底層套件的例外轉換成 `RetryableError` / `FatalError` 再往外拋。
  - 理由：主迴圈完全靠這個分類決定「下一輪重試」還是「直接停止」。漏一個 ccxt 例外
    出去，它會被 `run_forever()` 最外層的 `except Exception` 接住，離開碼變成
    `EXIT_UNEXPECTED`，systemd 的 `RestartPreventExitStatus=2`（D017）就會做出相反的
    重啟決定——**而且完全沒有徵兆**。這正是換交易所時最容易漏掉的一件事，
    所以要寫在介面上而不是留在實作裡。
  - `create_loan_offer()` 的「不得自行重試」（D013）同理，一併寫進介面。
- 決策二：**`LendingStrategy` 更名為 `FrrPlusStrategy`**。
  - 理由：`strategies/` 目錄成形、`strategies/base.Strategy` 出現之後，「LendingStrategy」
    這個名字已經指認不出是哪一種策略——泛稱的位置被 `Strategy` 佔走了。
    檔名是 `frr_plus.py`，類別名沒跟上只會讓兩邊對不起來。
  - 代價：所有引用點要改。實際上只有 `main.py` 與兩個測試檔，由測試當場擋住漏改。
- 決策三：**`notify/line_messaging.py` 只搬位置、不改內容**，接受暫時的名實不符。
  - 現況是檔名叫 `line_messaging`、內容打的卻是 2025-03 已停用的 LINE Notify 端點。
  - 為什麼不乾脆先叫 `line_notifier.py`：目標架構（ARCHITECTURE.md、TASKS.md）早就把
    路徑定為 `notify/line_messaging.py`，改寫分支 `feature/m4-line-messaging` 被使用者
    尚未申請的 Channel 憑證卡住、無限期待命。先用舊名等於保證之後還要再搬一次，
    而搬遷的成本剛好落在最不該有意外的那條分支上。
  - 代價的抵銷方式：模組 docstring 第一段就明寫「目前仍打已停用的 LINE Notify、
    `send()` 永遠回傳 False」，並列出改寫時要一併更名的環境變數
    （`LINE_NOTIFY_TOKEN` → `LINE_CHANNEL_ACCESS_TOKEN` 等）。
    **檔名會誤導人，docstring 不會**——會去讀這個檔的人一定會看到第一行。
- 決策四：**離開碼常數移到 `core/bot_engine.py` 定義，但 `main.py` 匯入後維持同名存取**，
  測試也繼續斷言 `main.EXIT_OK` / `main.EXIT_FATAL`。
  - 理由：常數該跟決定它的程式碼放在一起（現在是 `run_forever()`），但**實際交給
    作業系統的是 `main.py` 回傳的那一份**，systemd 認的也是它。測試斷言的位置要對齊
    「真正生效的地方」，而不是「定義的地方」——D018 的教訓就是斷言問錯對象，
    結果一道檢查從加入起就不可能通過，還一路沒人發現。
- 方法論（值得記下來）：**這次搬遷的「行為沒變」是由測試本體幾乎沒動來證明的**。
  283 項測試裡，改的只有 import 路徑、`monkeypatch` 的目標模組，以及
  `tests/functional/test_run_once.py` 裡一個薄的 `run_once()` 輔助函式（包住 `BotEngine`
  的建構）。測試邏輯與斷言一行沒碰——如果為了讓測試通過而動到斷言，就等於把
  迴歸保護網自己拆掉，那才是重構最常見的翻車方式。
- 驗證：283 項測試全過（含 6 項實際連 Bitfinex 的 live 測試）、`py_compile` 全過、
  另以暫存 DB／log 實跑 `python main.py` 一輪，確認 bootstrap 接線正確
  （啟動檢查 → 進入主迴圈 → 取消 → 查餘額與 FRR → 掛兩筆 dry-run 單 → 進入睡眠）。
- 影響範圍：`main.py`、`api/`（新增 `base.py`、`bitfinex_client.py`）、
  `strategies/`（新增）、`core/`（新增）、`notify/`（新增）、`modules/`（移除）、
  `tests/` 全部、`.github/workflows/python-app.yml` 的 `py_compile` 清單。

## D022 — 金鑰檔的位置與掛載方式：家目錄唯一真實來源、只掛單一檔案、一律走檔案不走環境變數

- 日期：2026-08-15
- 背景：實單前要備妥 `secrets.env`。盤點時發現兩件事——家目錄那份樣板其實
  早就存在（2026-07-12 建立，四個鍵都是空值），而 Quadlet 掛的是**整個部署目錄**。
- 前提：先界定這台機器的實際威脅面。`uid >= 1000` 的一般使用者只有 `shuyu` 一個，
  而 root 本來就讀得到一切——**「同機他人偷讀」實質上不存在**。真正該防的是
  誤入版控被推上 GitHub、容器被入侵後的橫向取得、備份工具誤打包。
  檔案權限要收緊（目錄 700、檔案 600），但它不是這則決策的重點。
- 決策一：**唯一真實來源是 `~/.config/bfx-lending-bot/secrets.env`**，不放
  `/workspace/deploy/active-bots/ShuyuLendingBot/`。
  - 位置在 `/workspace` 之外，git、CI、部署腳本在**結構上**就碰不到它。
    這比「靠 `.gitignore` 記得擋」可靠——後者只要有人 `git add -f` 就破功。
  - 而且 `config/settings.py` 的預設路徑正是它，本機直接跑 `main.py` 與容器內
    讀的是同一份，不會兩邊分家維護兩份金鑰。
  - 舊位置的其他缺點：目錄權限 755、SELinux 標籤是 `unlabeled_t`、
    且該目錄同時是 `data/` 與 `logs/` 的家。
- 決策二：**Quadlet 只掛那一個檔案，不掛整個目錄**。
  - 原本是 `Volume=/workspace/.../ShuyuLendingBot:/run/secrets:ro`。實測容器內
    `/run/secrets` 底下看得到 `data/`（完整 SQLite 交易紀錄）與 `logs/`——
    而這兩個目錄本來就另外掛在 `/app/data` 與 `/app/logs`，**重複掛載毫無作用，
    只是在容器被入侵時多送對方一份完整交易紀錄**。
  - 附帶加上 `ExecStartPre=/usr/bin/test -f <來源檔>` 守門：掛單一檔案時，
    來源不存在的話 podman 會**自己建一個同名目錄頂替**，程式開檔噴
    `IsADirectoryError`，錯誤訊息離真正的原因（金鑰檔不見了）非常遠。
    寧可在啟動前當場失敗，理由與 `Pull=never`（D017）相同。
- 決策三：**金鑰一律以檔案傳遞，不得改用 `Environment=BFX_API_KEY=...`**。
  - 用環境變數會讓金鑰同時出現在四個地方：Quadlet 單元檔本身（**而它在版控裡**）、
    `podman inspect`、`systemctl show`、`/proc/<pid>/environ`。
  - 這條寫進單元檔的註解，避免日後被當成「多此一舉的間接層」順手簡化掉。
- 不採用 `podman secret`：會多出**第二個真實來源**（本機跑 `main.py` 讀不到，
  得維護兩份）、更新要 `secret rm` + `create` + 重啟，而預設驅動只是把檔案存在
  `~/.local/share/containers/storage` 底下——**一樣是 uid 1000 讀得到，實質保護
  並沒有比 600 的檔案更好**。等日後有多台機器或多個服務共用同一組金鑰再回頭評估。
- 不採用「以 root 建立金鑰檔」：rootless podman 以 `shuyu` 身分執行，容器內的 root
  對映到主機 uid 1000。檔案若由主機 root 擁有且權限 600，**容器會直接讀不到而啟動失敗**。
  安全性也沒有提升——`600 + owner shuyu` 已經是「只有你和 root 讀得到」，
  改成 root 擁有只是把使用者自己也擋在門外，能讀的人並沒有變少。
- SELinux 備查：目前是 **Permissive**，家目錄的 `config_home_t` 掛進容器不會被擋。
  若日後改為 `Enforcing`，這個掛載需要加 `,z`（會重新標記該檔）或調整對應布林值。
  記在這裡是因為屆時的症狀（容器讀不到金鑰）與原因（SELinux）距離很遠。
- 驗證：`quadlet -dryrun` 確認產生的 `podman run` 帶的是單一檔案的 `-v`；
  重啟後服務 `active`、容器 `healthy`、容器內 `/run/secrets` 只剩 `secrets.env`
  （另有 podman 在 RHEL 上**預設注入**的訂閱憑證 `rhsm/`、`redhat.repo`、
  `etc-pki-entitlement/`，與本專案無關，非本次掛載帶進去的）；
  日誌全文搜尋金鑰樣式 0 筆；283 項測試維持全過。

## D023 — 失效告警改為三分法：假警報比漏報更難修，因為它會讓人不再相信這個管道

- 日期：2026-08-15
- 背景：D022 的驗證重啟跳出一則 ERROR「機器人啟動失敗，systemd 正在自動重試」，
  但同一行附帶的六個單元欄位全都說它是好的（`success`／離開碼 0／重啟 0 次／
  `active`／`running`）。翻日誌發現同樣的訊息在 08-09 22:57 與 08-15 17:26 也各一筆
  ——**三次都正好是重啟服務的時刻**，所以是既有缺陷，不是 D022 改壞的（TASKS.md B4）。
- 根因：`OnFailure=` 在重啟停掉舊容器那一刻會被短暫觸發，而 `notify_failure.py`
  只分辨兩種狀態：`SubState=auto-restart` → 重試中、`ActiveState=failed` → 已放棄。
  等 2 秒再查時單元已回到 `active/running`——**這是第三種狀態，而它沒有分支**，
  於是落進「重試中」的 else，送出一則內容與事實相反的 ERROR。
- 決策：**改成三分法**（新增 `classify()`，回傳
  `STATE_GAVE_UP` / `STATE_RETRYING` / `STATE_RUNNING_NOW`），第三種依 `NRestarts`
  給等級：0 次 → INFO（部署重啟造成的觸發）、>0 次 → WARNING（確實失敗過但已自動恢復）。
  - **判斷順序不能顛倒**：先問 `auto-restart`，再問 `active/running`，最後才落到
    `failed`。反過來寫的話，重啟途中短暫的 `active` 會被誤判成「已恢復」。
  - **仍然寫進日誌與 DB，只降等級、不靜音**——D020 的「不做靜音」原則不變。
- 為什麼值得專門修：這是**假警報**，不是漏報，直覺上比較無害。但它每次部署都發生，
  而 `feature/m4-line-messaging` 一接上就會變成「每次部署推一則『機器人啟動失敗』到手機」。
  這正是訓練人忽略告警的典型模式——等哪天推的是真正的「已放棄」，那則訊息看起來
  會跟前面幾十則假警報一模一樣。**B2 的價值不在於訊息送得出去，而在於收到的人還會不會當真。**
- 已知的取捨：`NRestarts` 是累計值，只有 `reset-failed` 會清零（CI 每次部署前會清）。
  所以「昨天崩過、今天手動重啟」會被歸到 WARNING 那一支。訊息內容仍然誠實
  （它確實重啟過 N 次），只是稍微保守，接受。
- 驗證：292 項測試全過（新增 9 項）；以舊邏輯對同一份狀態跑反證，確認它確實會判成
  ERROR「啟動失敗」，證明新測試不是套套邏輯；**實機重啟正式服務**，日誌那一行從
  `ERROR 啟動失敗` 變成 `INFO 告警被觸發，但單元目前正常運作中`，服務與容器全程正常。
- **驗證範圍的已知缺口**：沒有像 D020 那樣起拋棄式單元、實測「重試中 → 已放棄」
  兩條路徑（使用者當下不希望在 `~/.config/systemd/user/` 放實驗檔）。判斷風險可接受的
  依據是：那兩條分支的判斷順序與訊息字串**一字未改**，且各自有單元測試涵蓋。
  若日後要補這個實驗，做法見 D020 的兩個對照實驗。

## D024 — LINE Messaging API 接上：額度決定了「什麼事件才配得上一則訊息」

- 日期：2026-08-15
- 背景：使用者申請好 LINE Developers Channel 並填入憑證，M4 最後一條分支
  `feature/m4-line-messaging` 的阻塞解除。憑證先以三個唯讀端點驗過：token 有效
  （官方帳號「Bitfinex貸款機器人」）、user ID 有效且已是好友、額度
  `{"type": "limited", "value": 200}`。
- 決策一：**這個管道只送事件，不送例行**。`BotEngine.run_once()` 結尾原本每輪
  `notifier.send("已完成一輪巡檢")`，改為只寫日誌。
  - 算式很直接：巡檢間隔 600 秒 = 一天 144 輪，而免費方案是**每月 200 則**。
    照原樣接上去，**不到兩天就把整個月的額度用光**，之後真正的故障告警一則都送不出去。
  - 這不是「調參數」能解的：任何合理的巡檢間隔都遠超過每月 200 則的預算。
    要有例行摘要的話，正確做法是每日彙總一則（約 30 則/月），而那要等
    `earnings_daily` 有資料來源才有意義（TASKS.md 既有項目）。
  - `FailureTracker` 的「只在跨門檻與恢復時各送一次」因此從「避免洗版」升級為硬性需求：
    持續失敗若每輪推一則，額度會在故障期間被自己燒光——**恰好在最需要通知的時候**。
- 決策二：**維持兩份獨立實作，刻意不共用程式碼**。容器內 `notify/line_messaging.py`
  用 `requests`；主機端 `scripts/notify_failure.py` 用標準函式庫的 `urllib`。
  - 理由與 D020 相同：`notify_failure.py` 執行的時機正是機器人壞掉的時候，
    它要報告的往往就是「容器本身已經不在了」，不能 import 專案模組或依賴第三方套件。
  - 代價是兩邊要一起改，兩份 docstring 都寫了這件事。
  - 附帶：`notify_failure.py` 自己讀 `secrets.env`（告警單元不會帶憑證進來）。
    **刻意不用 systemd 的 `EnvironmentFile=`**——`secrets.env` 每行都有 `export ` 前綴，
    systemd 會把 `export LINE_CHANNEL_ACCESS_TOKEN` 整串當成鍵名而解析失敗，
    而那種失敗是安靜的。
- 決策三：**INFO 等級不推 LINE**。D023 剛把「部署重啟送假 ERROR」修掉，
  若又從 LINE 這個管道把同樣的東西推到手機，等於換個管道再犯一次。日誌與 DB 照常留痕。
- 決策四：**舊的 `LINE_NOTIFY_TOKEN` / `LINE_NOTIFY_CHANNEL` 不做向後相容**，直接改名為
  `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_TO_USER_ID`（設定鍵 `channel` → `to_user_id`）。
  留著舊名只會讓人以為設了就有用，而 LINE Notify 的 token 對新端點必定是 401。
- `send()` 永遠不拋例外（承 D019）：它出現在致命錯誤的退出路徑上，拋例外會蓋掉原始錯誤
  與離開碼。所有失敗一律回傳 False 並記日誌，且**刻意不重試**——事件本身早已寫進日誌與 DB，
  重試只會拖慢機器人結束的時間。HTTP 錯誤碼一律翻成人看得懂的原因（403 最常見的其實是
  「對方不是好友」而不是權限設定）。
- **踩到的坑：測試套件真的把訊息送出去了**。接上 Messaging API 後第一次跑 `pytest`，
  `scripts/notify_failure.py` 的測試從 `~/.config/bfx-lending-bot/secrets.env` 讀到真金鑰，
  **實際推了 6 則訊息到使用者手機**，也吃掉當月額度的 6 則。
  - 失敗方式很安靜：測試照樣綠燈，只有手機會響。
  - 修法寫在 `tests/conftest.py` 的 autouse fixture：所有測試一律清掉兩個 LINE 環境變數、
    把 `BFX_SECRETS_FILE` 指到不存在的路徑，沒有憑證時兩邊都會在發出請求前回傳 False。
    `test_notify_failure.py` 另外把 `urlopen` 換成「一呼叫就 AssertionError」當第二道保險。
  - **刻意不做全域封鎖網路**：`tests/integration` 有 6 項刻意連 Bitfinex 公開 API 的
    live 測試，那是它們的價值所在。
- 驗證：312 項測試全過（283 → 312，新增 `tests/unit/test_line_messaging.py` 13 項與
  告警腳本的 LINE／secrets 測試）；**兩條管道各實際送出一則測試訊息並確認送達**
  （主程式路徑走 `load_secrets_from_disk` + `config.yaml` 的真實接線，
  告警腳本路徑走主機端獨立實作），INFO 等級確認略過。

## D025 — 首次實單：掛單金額四捨五入超出餘額；dry-run 驗證不了「只有交易所會驗的東西」

- 日期：2026-08-15
- 經過：`dry_run: false` 部署後第一輪巡檢，連線、取消（0 筆）、查餘額（160.00861413）、
  抓 FRR（0.00032288767）全部正常，掛單卻被 Bitfinex 拒絕：
  `Invalid offer: not enough USD balance available in deposit wallet`。
  機器人依例外分類判為 `FatalError` → 離開碼 2 → systemd 的
  `RestartPreventExitStatus=2` 不重啟 → 停在 `failed` → `OnFailure=` 送出 CRITICAL 告警。
  **整條可靠性鏈按設計運作，資金零損失**（事後查證：0 筆掛單、0 筆已借出、餘額分毫未動）。
- 根因：`_split_amount()` 先把每筆金額 `math.floor` 到分位（註解也寫明用意是
  「確保加總不會超過可用餘額」），**但緊接著用 `round()` 處理餘數**——
  `round(0.00861413, 2)` 進位成 `0.01`，加回第一筆後總額變成 160.01，
  比可用餘額多了 0.00138587。**後一行把前一行的用意整個抵銷掉。**
- 修法：改用**整數分**運算。`int(Decimal(str(x)) * 100)` 取得總分數（截斷即向下取分位），
  再 `divmod` 分配，餘數以分為單位併入第一筆。
  - 為什麼不是「把 `round` 換成 `floor`」：純浮點下 `500.0 - 166.66 * 3` 實際算出
    `0.019999999999953`，向下取分位會**少掉一分錢**——第一版就是這樣改的，
    當場弄壞三條既有測試（它們斷言總額等於餘額）。金額運算不該碰浮點誤差。
- **這則決策真正的教訓是測試設計，不是那行 `round`**：
  - 既有測試 `test_total_never_exceeds_balance` **斷言的正是這個性質**，而且一直是綠的。
    問題在輸入——`150.0 / 344.12 / 500.0 / 777.77 / 1000.01 / 12345.67` 全是
    小數點後至多兩位的「漂亮數字」，**那種輸入在數學上不可能違反這條性質**，
    因為 `floor` 與 `round` 的結果必然相同。真實的 Bitfinex 餘額有 8 位小數。
  - 一條斷言正確、輸入卻挑不出反例的測試，比沒有測試更危險：它會讓人以為這件事被守住了。
  - 已補：把真實餘額（含 `160.00861413`）加進該測試的輸入集，另加一條指名這次事故的
    迴歸測試。改完先把舊實作還原、確認兩條新測試確實失敗，才算數。
- **dry-run 的能力邊界**：dry-run 下 `create_loan_offer()` 直接回傳假的成功結果，
  **沒有任何人驗證金額合不合法**。凡是「只有交易所才會驗的規則」（最小單量、
  金額不得超過餘額、利率精度、天期範圍），dry-run 全部驗不到。
  這類問題只會在第一筆真單暴露——所以第一次實單的金額要小到「賠光也無所謂」，
  而這次的做法（把多餘資金移出融資錢包，用錢包餘額而不是設定參數鎖住曝險）是對的。
- 附帶發現（未修，記為 TASKS.md B5）：ccxt 把這個**餘額不足**的錯誤歸類成
  `AuthenticationError`，於是日誌寫的是「建立放貸掛單認證失敗」。
  訊息會把人引去查 API 金鑰，而真正的問題在金額。


## D026 — 取消掛單的 id 型別，與「靜默失效」比崩潰更危險

- 日期：2026-08-15
- 經過：D025 的金額修正上線後，第一筆真單順利掛出（`5081103121`，160 USD @ 0.000523）。
  但接下來每一輪都出現 `取消掛單 5081103121 失敗：bitfinex id: invalid`，
  連續兩輪無人察覺，是靠盯日誌的監看才發現。
- 根因一（直接原因）：**ccxt 對這個 implicit 端點回傳的每個欄位都是字串**
  （實測 `offer[0] == '5081103121'`、`offer[4] == '160'`），而 Bitfinex 的
  `auth/w/funding/offer/cancel` 只收整數 id，收到字串一律回 `id: invalid`。
  程式對 `amount` / `rate` / `period` 都有轉型，**唯獨要送回 API 的 id 沒有**。
- 根因二（為什麼測試沒抓到）：測試替身 `make_offer_array()` 產生的是**原生型別**
  （int id、float 金額），比真實 API「乾淨」。於是
  `test_cancels_every_open_offer` 斷言 `{"id": 101}` 一直是綠的——
  **它驗證的是另一個世界的行為**。與 D025 是同一種病：D025 是輸入挑得太乾淨，
  這次是替身做得太乾淨。已把替身改成回傳字串，並補一條「送回 API 的 id 必須是 int」
  的型別斷言；拿掉 `int()` 反證，4 條測試會失敗。
- **真正嚴重的是失效方式，不是那個型別**：原本的程式碼在單筆取消失敗時
  只記一行 ERROR 就 `continue`，最後照樣印「已取消 0 筆」並讓本輪正常結束。後果是
  ——連續失敗計數不動、不會告警、心跳照常更新、容器健康檢查一路綠燈。
  **機器人看起來完全正常，實際上「每輪全取消重掛」這個核心策略已經停擺**，
  掛單利率從此不再跟著市場走。
  - 對照 D025 那次：程式直接崩掉、送出 CRITICAL 告警、systemd 停在 failed，
    **五分鐘內就被發現**。這次沒有任何一道防線響過。
  - **會叫的失敗遠比安靜的失效好處理。** 這條要記住。
- 決策：`cancel_active_offers()` 在「查到掛單卻一筆都取消不掉」時改拋 `RetryableError`，
  讓主迴圈記為失敗、由 `FailureTracker` 在連續達門檻時告警。
  - 用 `RetryableError` 而非 `FatalError`：取消失敗多半是暫時性的，下一輪重試合理。
  - **部分成功不算失敗**：取消掉幾筆就回報幾筆，剩下的下一輪再處理——
    否則偶發的單筆失敗會讓整個機器人停擺，反應過度。
- 未竟事項：`create_loan_offer()` 回傳的 id 仍是交易所給的字串（DB 的 `offer_id`
  欄位本來就是 `TEXT`）。只有取消端點需要整數，不強求全專案統一型別。

## D027 — 測試替身與測試資料一律取自真實回應，不得自己編「乾淨」的版本

- 日期：2026-08-15
- 背景：實單第一天的兩個 bug（D025、D026）**都通過了完整的測試套件**，而且兩者各自
  都有一條測試「正在守護那個性質」。它們漏掉的原因是同一個：**測試看到的世界比真實世界乾淨**。
  - D025：`test_total_never_exceeds_balance` 斷言「總額不得超過餘額」——完全正確，
    但輸入是 `150.0 / 344.12 / 500.0 / 777.77 …`，全是小數點後至多兩位的手打數字。
    **那種輸入在數學上不可能違反該性質**（`floor` 與 `round` 必然相同）。
    真實 Bitfinex 餘額是 `160.00861413`。
  - D026：`make_offer_array()` 產生原生型別（int id、float 金額），
    於是 `test_cancels_every_open_offer` 斷言 `{"id": 101}` 一直是綠的。
    真實 ccxt 對該端點回傳的**每個欄位都是字串**（`'5081103121'`），
    而取消端點只收整數——測試驗證的是另一個世界的行為。
- 決策：**凡是模擬外部系統回應的測試替身與測試資料，一律以實際抓到的回應為準**。
  1. 新增或修改替身時，先用唯讀 API 實際打一次，把**型別與格式**照抄進替身
     （字串就是字串，不要「順手」轉成數字）。
  2. 涉及金額、利率、餘額的測試，輸入至少要有一組**真實精度**的值
     （Bitfinex 餘額 8 位小數、利率 6 位以上），不能只有手打的整數與兩位小數。
  3. 替身的 docstring 要註明「這些型別取自真實回應」，避免後人為了讓測試好寫而「整理」它。
- 為什麼值得單獨立一條：這兩個 bug 的成本不是修它們的時間，而是**它們只能靠花真錢才會浮現**。
  dry-run 驗不到、單元測試也驗不到的話，下一個同類問題還是得用真金去換。
  接 `earnings_daily` 的 ledger 端點、升級 `maxtolend` 時會再碰到同一類回應解析，
  這條準則要先立起來。
- 不採用「改成整合測試打真實 API」：私鑰端點的測試會下真單、動到真錢，
  且 CI 環境不該持有實單金鑰。折衷就是上面的第 1 點——**人去打一次，把結果固化進替身**。

## D028 — 時區是應用程式屬性，不是容器環境的副作用

**日期**：2026-08-16
**狀態**：已採用

### 背景

同一個日誌檔裡混了兩個時區，相鄰兩行差 8 小時：

```
2026-08-16 05:20:41,023 INFO 開始執行 Bitfinex 放貸機器人      ← 容器寫的，UTC
2026-08-16 13:20:42,583 INFO 告警被觸發，但單元目前正常運作中   ← 主機寫的，CST
```

兩邊用的是**同一行程式碼風格**——`datetime.now()` 與 `logging` 的 `%(asctime)s`，
兩者都取「行程的本地時區」。機器人跑在 `python:3.11-slim` 容器裡（沒設 `TZ`，預設 UTC），
`scripts/notify_failure.py` 由 systemd 在主機上執行（CST）。程式碼看起來一致，
行為卻由**它剛好跑在哪裡**決定。

`notify_failure.py` 的 `timestamp()` docstring 當時寫著「與機器人日誌同格式的時間戳，
讓兩邊的行可以一起看」——**意圖完全正確，而它從第一天起就是假的**。

實際代價：對帳時看到日誌停在 `04:23` 會以為機器人掛了，其實那是 12:23 CST，機器人正常。
本次盤查就差點誤判一次。

### 決策

**時區改由程式明確決定，預設 `Asia/Taipei`，且每一行時間戳都附上 UTC 偏移。**

- 新增 `utils/clock.py` 作為唯一時區來源（`DEFAULT_TIMEZONE` + `BFX_TIMEZONE` 環境變數）
- `utils/logger.py` 新增 `ZonedFormatter`，時間戳格式變成 `2026-08-16 14:17:32,843 +0800`
- `db/repository.py` 的 `utc_now()` 改名 `now_iso()`，寫入 `2026-08-16T14:17:47+08:00`
- `scripts/notify_failure.py` 複製一份最小的時區解析（維持 D024 的獨立實作原則）

### 為什麼不用 `TZ` 環境變數或在 Dockerfile 裝 tzdata

那是最常見的做法，但它把時區留在**環境**裡，而環境正是這次出錯的地方——
Quadlet 單元、docker-compose、CI、開發者的本機各有各的環境，漏掉任何一個就再度分岔。
放進程式碼則是「一處決定、處處一致」，而且可以寫測試釘住
（`test_renders_in_taipei_regardless_of_process_timezone` 直接把 `TZ` 設成 UTC 再驗）。

實測 `python:3.11-slim` 本來就帶 tzdata，`ZoneInfo("Asia/Taipei")` 在容器內可用，
所以連 Dockerfile 都不必動。

### 為什麼要在每行附上 `+0800`

多六個字元，換到的是**每一行日誌自己說得清楚它是什麼時區**。
這次的教訓不是「UTC 不好」——UTC 沒有錯，錯的是**看不出來是哪一個**。
附上偏移之後，即使哪天時區解析失敗退回 UTC，日誌上也會直接顯示 `+0000` 而不是無聲地錯 8 小時。

### 舊資料不遷移

DB 舊列帶 `+00:00`、新列帶 `+08:00`，兩者都是 timezone-aware，
`scripts/healthcheck.py` 拿去相減得到的秒數完全正確——時區偏移不同不影響時間點比較。
已用新舊兩種格式各驗過一次健康檢查的判定結果（正常／過期都正確）。
硬要遷移反而是拿一個沒有問題的東西去冒風險。

### 影響

- 測試 315 → 327 項
- 唯一的行為變更是「顯示」與「寫入格式」，策略、風控、掛單邏輯一律未動

## D029 — 通知訊息的統一格式，以及「交易面推的是狀態轉換，不是狀態」

- 日期：2026-08-16
- 分支：`feature/notify-format-and-trade-events`（TASKS.md P2-3、P2-4）
- 背景：使用者的兩個需求——「只有系統壞掉才通知，我也想知道交易面的事」與
  「訊息格式很亂，幫我分一下是系統面還是交易面」。

### 訊息為什麼會亂：沒有任何地方負責「組訊息」

不是措辭沒統一，是**結構上就沒有組訊息這一層**。六則訊息全是散在程式裡的裸字串
——`core/bot_engine.py` 三條退出路徑各一句、`FailureTracker` 的告警與恢復各一句、
`scripts/notify_failure.py` 四種單元狀態各一段——每處自己拼句子，
`LineNotifier.send()` 只管送、不管內容。所以句型、要不要附狀態欄位、
要不要寫「需不需要人工介入」全看當時寫的人。

修法是新增 `notify/messages.py` 專責組裝，`send()` 維持只負責送。

### 格式：三段式

第一行 圖示 ＋`【分類】`＋**一句話結論**；中間 `欄位：值`（第一個固定是時間，帶 `+0800`）；
最後一行**「需人工介入」或「無需處理」二選一**。

- **結論放第一行**是因為手機通知列往往只看得到那一行。
- **最後一行只有兩種**是 D023 的延伸：那次的教訓是「看起來像故障、其實不用管」的訊息
  會訓練人忽略整個管道。與其讓每則訊息自己用不同的話術暗示，不如**強制每則都表態**。

### 圖示規則：正常看分類、異常看等級（實作時修正過一次）

規劃時寫的是「圖示與等級綁定，不要一個事件一個圖示」，但同一份規格的範例又給成交
配了 💰——**自己就矛盾了**。定案為：正常事件用分類的圖示（🔵系統／💰交易／📊收益／
🛡風控），WARNING 以上一律用等級燈號（🟡／🟠／🔴）。共五個。
這樣「有沒有事」在通知列上一眼分得出來，分類則回答「是哪一面的事」。

### 日誌單行、推播三段式：同一個事件，兩種讀者

實作時才浮現的問題：把三段式訊息直接寫進日誌，**後續幾行看起來就不像日誌**，
而 `grep ERROR` 只會抓到第一行。日誌是一筆一行的格式，這個約定不能為了共用字串而破壞。
所以兩邊分開：日誌維持既有的單行措辭，推播才用三段式。
`scripts/notify_failure.py` 同樣拆成 `build_message()`（日誌／DB）與
`build_push_message()`（LINE）。

### 交易面通知：推的是**狀態轉換**，不是狀態

這是這次最重要的一個決定，因為額度是硬的：每月 200 則 ≈ 每天 6.6 則，
而巡檢間隔 600 秒等於一天 144 輪。

規劃時寫的是「掛單內容與上一輪不同才推」。**實作時發現那個門檻擋不住 FRR 漂移**
——利率每輪都會有小數點後幾位的差異，比對「內容有沒有變」等於每輪都變，
又回到一天 144 則。加一個「變動超過 5% 才推」的門檻也只是把它降到一天幾則，
仍然吃掉整個額度。

所以改成只追蹤一件事：**場上有沒有我們的單**（`True` / `False` / `None` 還不知道）。
只有這個值變了才推：

- `None → True`：啟動後首輪掛單（部署完最想確認的事）
- `True → False`：掛單從場上消失
- `False → True`：掛單重新上線
- 掛單被交易所拒絕：每次都推（實單至今只發生過一次，見 D025）

利率的日常微調只寫日誌。實際頻率一天通常 0～2 則。

### 「掛單已不在場上」刻意不寫成「成交了」

這則訊息是目前**唯一能察覺「錢可能借出去了」的訊號**——等於在 P2-1（成交偵測）
還沒做之前，先拿到了它一部分的價值。但機器人還沒有查詢已借出部位的能力，
餘額歸零也可能是資金被搬到別的錢包，所以訊息只講看得到的事實、把推測寫成「可能原因」。

**寫死成「成交」而事後發現是轉帳，這個管道就再也不會被相信**——這與 D023
是同一個判斷：通知管道的可信度是一次性的，毀掉之後修不回來。

### 狀態只放記憶體，不落 DB

`_offers_live` 重啟後回到 `None`，下一次掛單成功會推一則「啟動後首輪」。
落 DB 需要動 `bot_state` 的結構，而現有的 schema 只有 `CREATE TABLE IF NOT EXISTS`、
沒有任何遷移機制——為了省下一則訊息去對正在跑真金的資料庫做結構變更，不划算。
而且那一則訊息本身有價值：部署完最想確認的就是機器人回來了、單也掛上去了。

### `push_trade_events` 開關

`config.yaml` 的 `line.push_trade_events`（預設 true）是留給額度的安全閥。
**關掉的是通知，不是紀錄**——事件照樣寫進日誌，只是不推播。
放在 `line:` 而不是 `engine:` 底下：它管的是要不要推播，不是機器人怎麼跑。

### 影響

- 測試 308 → 347 項（新增 `tests/unit/test_messages.py` 22 項、
  交易面轉換 9 項、推播格式 8 項）
- 既有測試改了兩條，都是行為**刻意**改變：`test_routine_cycle_does_not_push_to_line`
  改成從第二輪開始數（第一輪現在會推「啟動後首輪」），
  `test_failed_round_sends_no_success_notification` 改成斷言「推的是被拒絕、不是上線」
- 策略、風控、掛單邏輯一律未動

## D030 — 定價基準改為訂單簿排隊位置；天期溢價的長期證據；以及資金規模如何重排優先級

- 日期：2026-08-16
- 分支：`feature/orderbook-pricing-and-fill-detection`（TASKS.md P1-1、P2-1、P3-1 的一部分）
- 背景：機器人自 2026-08-15 真金上線以來**一筆都沒成交**。D027 之後兩天的權宜手段
  （把 `premium_rate` 壓成負值）證實只是把問題推遲：它綁在 FRR 上，FRR 一漂移就跑掉。

### 一、定價：問題不是「訂多高」，是「站第幾位」

市場的成交價帶極窄（當日年化 8.7%～10.0%），**訂價權不在我們手上**——借款人不肯付
更高，掛 19% 不是比較貪心，是沒有買家。所以定價的真正變數是排隊位置。

訂單簿直接回答了這件事，演算法只有一句：
**在「排在我們前面的錢不超過 `target_queue_usd`」的前提下，挑利率最高的那一檔。**

`target_queue_usd` 是唯一的旋鈕，語意是「我願意排在多少錢後面」，可直接換算成等待時間
（除以該天期每小時的成交金額）。實測 2 天期每小時流過約 415 萬 USD，所以 100 萬 ≈ 等 15 分鐘。

**為什麼不用「最近成交的百分位」**（原本 P1-1 的規劃）：`/v2/trades` 的百分位會被
**爆發桶汙染**。2026-08-16 的實測裡，7 天期 1711 筆成交有 1357 筆擠在 12:50 那一個
10 分鐘桶；剔除後中位數從 0.000270 掉到 0.000250。爆發當下算出的 base_rate 會偏高，
掛出去必定掛空——**那是 FRR 落後問題換個來源重演一次**。訂單簿是當下狀態，沒有這個問題。

驗收（2026-08-16 用真實簿子跑過）：新策略掛 0.000250（年化 9.12%），前方排隊 73 萬 USD；
同一時刻舊策略掛 0.000272，正好貼在簿子頂端，也就是排在整個供給側最後面。

### 二、`minimum_rate` 的語意從「拉高」改成「不賣」

舊策略寫 `max(frr + premium, minimum_rate)`——算出來太低就把價格拉到底線。問題是
**拉上去的價位可能整個超出簿子**，結果是掛一張永遠不會成交的單：帳面體面，實際等於沒放貸。

改成：算出來的價位低於 `minimum_rate` 就**整輪不掛**。低於底線代表市場現在不值得借，
那就等下一輪，而不是掛一個假裝有在放貸的價格。

### 三、不再每輪無條件取消重掛

`run_once()` 原本開場就 `cancel_active_offers()`。但**同利率下是時間優先（先掛先成交）**，
以 600 秒巡檢一輪計，等於一天把自己送回隊伍末端 144 次——而這個價位的成交本來就是陣發的，
每次歸零都可能正好錯過那一波。P1-3 才剛花力氣阻止「文件 commit 造成的重啟重掛」，
機器人自己每天做 144 次，嚴重兩個數量級。

改為：先查場上現況（`get_active_offers()`，唯讀），與本輪計畫比對，**實質相同就什麼都不做**。

- **一定要有容差**（`rate_tolerance_pct`，預設 2%）：市場價位每輪都有小數點後幾位的漂移，
  逐位元比對等於每輪都判定「不一樣」，保護形同虛設。D029 已經在通知額度上踩過同一個坑。
- **可支配金額 = 可用餘額 ＋ 場上掛單金額**。只看可用餘額的話，單子一掛出去餘額就變 0，
  策略會以為沒錢可放，於是每輪都得「先取消才有錢算」——等於強迫自己每輪重掛。
- **計畫為空但場上有單時不撤單**：那張單是用更早、也就是更好的條件掛出去的。

### 四、成交偵測（P2-1）：機器人終於知道自己借出去了

新增 `funding_positions` 表與 `sync_positions()` 對帳。查 credits（借款人已用於持倉）
與 loans（借走但未使用）**兩個端點**——對放貸方而言兩者都是錢已經出去、正在生息，
只查一個會漏掉一半。

- **狀態必須落地**，不能只放記憶體：否則每次重啟都會把場上既有部位當成新成交，
  推一輪假通知。這個管道只要騙過人一次就不會再被相信（同 D023、D029）。
- **對帳要在取消掛單之前**：取消會改變場上狀態，先動手再對帳的話，
  「這一輪成交了嗎」就永遠答不出來。
- 偵測到成交時**不再推「掛單已不在場上」**——成交已經解釋了原因，同一件事講兩遍只是白燒額度。

**已知缺口**：credits／loans 的欄位索引取自官方文件，**尚未經真實回應核對**——
探測當下帳號一筆都沒成交，兩個端點都是空清單。所以解析寫成防禦式：欄位不足就跳過該筆
並把原始內容寫進日誌。**第一筆真實成交後要回來核對並更新註解**（B6／D027 的做法）。

### 五、天期：長期溢價真實存在，但當下被壓平

TASKS.md 原本的 P1-2 寫「7 天期利率比 2 天期高 0.5 個百分點，幾乎是白撿」。
**那個論據不成立**——它取自含爆發桶的窗，與 D027 記過的統計陷阱是同一個。

改用 998 天（2023-11～2026-08）的日 K 做滾動模擬（毛利年化）：

| 天期 | 全期間 | 最近 365 天 | 最近 90 天 |
|---|---|---|---|
| 2 天 | 6.47% | 6.37% | 5.87% |
| 7 天 | 9.45% | 9.81% | 8.08% |
| 30 天 | 10.47% | 8.71% | 8.35% |

長天期確實較優，原因是結構性的：**86% 的供給都擠在 2 天期**，競爭把價格壓下去。
但天期溢價會大幅變動（2023-Q4 為 +4.34 個百分點，2026-Q3 只剩 +0.20），
**所以寫死 2 天或寫死 7 天都是錯的架構**，正解是每輪比較各天期的實質年化再選。

條件式分析（依決策當下 2 天期利率的歷史水位分組）顯示：**利率處於高位時鎖長天期最划算**
——當下正是第 85 百分位，鎖 30 天有 94.8% 的機率優於滾動，平均多賺 5.34 個年化百分點。
原因是均值回歸：高位之後接下來 30 天的 2 天期平均會從 11.58% 掉到 7.17%。

**但這次仍然掛 2 天期**，理由與定價無關：**驗證階段不要把資金鎖住**。
「成交 → 記錄 → 通知」整條鏈一次都沒跑通過，先確認它會動，才有資格談天期最佳化。
2 天期流動性最好（占成交量 86%），最快拿到第一筆成交資料。

### 六、資金規模（344 USD）重排了整個優先級

把每項工作換算成實際金額之後，優先級跟原本排的不一樣：

| 工作 | 年收益（本金 344，扣 15% 手續費） |
|---|---|
| 讓單子掛進簿子裡 | **+18.92 USD** |
| 把現貨錢包 184 USD 也投入 | +14.39 USD |
| 動態天期選擇 | +7.97 USD |
| P3-1 spread 改百分位分佈 | **+0.00 USD** |
| P3-2 maxtolend 真實曝險版 | **+0.00 USD** |

**70% 的收益在第一項。** 由此得到這個規模下的定價鐵律：

> 空轉一天損失 0.074 USD，利率多爭 1 個百分點一天只多賺 0.008 USD。
> **空轉一天，要靠「利率高 1 個百分點」跑 9 天才補得回來。**
> 所以寧可掛低一點立刻成交，絕不為了多半個百分點多等。

**`spread_count` 由 3 改為 1**：單筆最低 150 USD，344 USD 最多只拆得出 2 筆，
而第 2 筆會被 `spread_step_pct` 乘到 0.000288——簿子頂端才 0.000270，
等於一半的錢掛成永遠不會成交的死單。**觸發條件正是「把資金全部投入」**。
拆單要到 500 USD 以上、而且改成百分位區間分佈才有意義，因此 P3-1、P3-2 一併降級。

### 影響

- 新增 `strategies/orderbook_depth.py`（預設策略）、`config.yaml` 的 `strategy.mode`。
  `frr_plus` 保留但**不是備援**——它已知會把單子掛到市場之上，
  自動退回它等於「失敗時切換到一個確定無效的策略」。拿不到市場深度時一律不掛。
- `api/base.py` 新增三個介面方法；`cancel_active_offers()` 與 `get_active_offers()`
  共用同一份查詢與解析，欄位索引只寫在一個地方。
- 測試 347 → 437 項。

## D031 — 重掛決策必須看排隊位置，不能只看利率差：我們差點砍掉第一筆成交的單子

- 日期：2026-08-16
- 分支：規劃階段（本次僅記錄，尚未實作）
- 狀態：**已確認的缺陷，待修**

### 背景：第一筆成交，以及它是怎麼險些沒發生的

2026-08-16 19:31:31，本專案上線以來**第一筆成交**：344.30 USD、日利率 0.000250
（年化 9.12%）、2 天期。距離 D030 的新策略首次掛單（18:10:24）1.35 小時。

但把日誌與 `funding_positions` 的時間戳對起來看，這筆成交是**在機器人送出取消之後**
才發生的：

| 時間 | 事件 |
|---|---|
| 19:31:01.586 | 對帳完成，當下確實還沒成交；排隊位置：**同天期前方 0 USD、全天期前方 0 USD** |
| 19:31:02.968 | **送出取消掛單** |
| 19:31:06.243 | 取消後餘額仍是 0.00861413（取消尚未生效），推「掛單已不在場上」 |
| **19:31:31** | **實際成交**（`funding_positions.opened_at`） |
| 19:41:07 | 下一輪對帳看到部位（`first_seen_at`），推「資金已借出（成交）」 |

**取消沒趕上成交，純屬運氣。** Bitfinex 的取消是非同步的（D011 已記過「餘額釋放等待」），
這次是市場先一步吃掉了單子；晚 30 秒成交，這筆就被我們自己取消掉了。

### 根因：兩個判斷各自正確，組合起來卻是最糟的決定

D030 為了保住時間優先權，加了「掛單條件與場上一致（利率容差 2%）就不動」的保護。
它在 18:20、19:20 兩輪都正確地維持不動。19:31 之所以決定重掛，是因為
**前方排隊金額掉到 0**——簿子前面沒人了，策略據此算出「可以掛更高的利率」，
新舊利率差超過 2% 容差，於是取消重掛。

單看定價，這個判斷是對的：沒人排在前面就該多要一點。
但**「前方 0 USD」同時也代表「下一個吃單的人一定吃到我們」**——
那正是整個排隊策略等待的那一刻，也是最不該把單子撤下來的一刻。

缺陷不在任何一段程式碼本身，而在於**重掛決策只看了「價格是否更好」，
沒看「現在是不是快成交了」**。策略把排隊位置算出來、寫進日誌，卻沒有把它餵回重掛判斷。

### 決策

**排隊位置要成為重掛決策的否決條件，而不只是日誌內容。**

- 前方排隊金額低於門檻（初擬：我們單筆金額的數倍，或直接取 0～數萬 USD 的區間）時，
  **一律不動單**，無論算出來的新利率有多好。
- 理由與 D030 的核心算式一致：這個規模下空轉一天要靠「利率高 1 個百分點」跑 9 天才補得回來。
  即將成交的單子，其期望值遠高於任何價差。
- 保護的方向是不對稱的：**少賺一點點價差 vs 把已經排到第一位的單子送回隊伍末端**，
  後者的代價大得多。判斷不出來時一律偏向「不動單」。

### 待驗證的疑點（修之前要先查清楚）

- **「前方 0 USD」是真實狀態，還是簿子讀取的假象？**19:20 那輪還有 402,169 USD，
  11 分鐘後歸零，接著就成交——需要確認這是真的被吃光，還是 `len=250` 截斷、
  或聚合精度造成的假象。**若是假象，那修的就是另一個 bug**，
  而且會影響 D030 整條定價鏈的可信度。
- 取消送出後、確認生效前的這段空窗，機器人的狀態機沒有明確表達。
  這次是「取消沒生效 → 成交」，反過來「取消生效 → 但我們以為還在場上」同樣可能發生。

### 附帶結論：D029 的措辭規則被實戰驗證了一次

19:31:06 推出的那則「掛單已不在場上」，內容是
「已排除：本輪沒有偵測到新的已借出部位，所以不是成交／可能原因：融資錢包餘額被移走，
或掛單在交易所端被取消」。**以當下的事實判斷，這則訊息完全正確**——那一刻確實還沒成交。

D029／TASKS.md P2-4 當初刻意決定「訊息不寫死成『成交』，猜錯一次這個管道就不會再被相信」。
如果當時圖方便寫成「成交」，19:31 就會推出一則錯的通知。
**這條規則的價值在第一次真實成交當天就兌現了，不要改掉它。**

## D032 — 定價旋鈕升級為期望值計算：等待時間該由程式自己算，不是由人手算後填進設定檔

- 日期：2026-08-16
- 分支：規劃階段（本次僅記錄，尚未實作）
- 狀態：**已確認的方向，待設計**

### 背景：一段長在對話裡、卻沒長在程式裡的推理

D030 把定價收斂成一個旋鈕 `target_queue_usd`（我願意排在多少錢後面），
並註明「除以每小時成交金額即可換算成等待時間」。

2026-08-16 晚間，使用者問「現在掛的這個利率掛得出去嗎？會不會等好幾天？」——
回答這個問題的過程是：打公開端點抓訂單簿與近期成交、剔除爆發桶算出常態流量速率、
把前方排隊金額除以流量得到預估等待時數、再把各個候選檔位的
「等待成本 vs 利率收益」列成表比較。結論是目前設定正確、不該再往前擠。

**問題是：這整段推理是人在對話裡做的，程式一無所知。**
程式只拿到最後那個數字 `1_000_000`。旋鈕是人手算的結果，
市場一變，這個數字就過期，而程式沒有任何辦法察覺。

### 決策

**把「時間成本／期望值」的計算搬進策略層，讓 `target_queue_usd` 這類固定旋鈕
從「輸入」變成「（可選的）上限」。**

策略每輪要能自己回答的問題：

1. **市場現在的利率水準在哪？**（已有：讀訂單簿）
2. **掛在候選價位 r，前面排多少錢？**（已有：`describe_queue()`）
3. **那些錢多久會被吃完？**（缺）——讀近期成交算流量速率，
   **必須剔除爆發桶**，否則就是 D030 記過的統計陷阱換個地方重演。
4. **等這段時間值不值得？**（缺）——用等待成本與利率收益比較，選期望值最高的檔位。

比較的算式在 D030 已經成形，只是還沒進程式：

> 空轉的年化是 0%。以 344 USD 計，空轉一天損失約 0.074 USD，
> 而利率多爭取 1 個百分點一天只多賺 0.008 USD——**空轉一天要跑 9 天才補得回來。**

同一套計算也應該回答**天期選擇**（D030 第二節已有長期證據：2 天 6.47%／7 天 9.45%／
30 天 10.47%，但溢價會大幅變動，所以**寫死任何天期都是錯的架構**，
正解是每輪比較各天期的實質年化再選）。天期與利率是同一個期望值問題的兩個維度，
應該在同一處計算，不該一個寫在程式裡、一個寫在設定檔裡。

### 為什麼現在記錄、但不現在做

- **本次僅記錄規劃**（使用者明確指示）。
- 實作前需要先有實測校準資料。目前只有一個樣本：預估 0.48～0.79 小時、
  **實際 1.35 小時**——方向對，但比保守估計還久 1.7 倍。
  一個樣本不足以定參數，這正是「估算要進程式並持續校準」的理由，
  而不是再手算一次填進去。
- **D031 排在這一項前面**：期望值算得再準，只要重掛邏輯還會把即將成交的單子撤掉，
  算出來的期望值就兌現不了。

### 施工窗口的附帶紀錄

第一筆成交鎖住 2 天期（19:31 起算），期間場上沒有掛單、融資錢包餘額 0.0086 USD。
**這段期間部署重啟不會損失任何排隊位置**——P1-3 之後一直存在的
「合併程式碼就會重置排隊中的單子」限制，在資金全部借出的期間自動解除。
未來規劃較大的改動時，可刻意選在這種窗口施工。

## D033 — 只看訂單簿會被一筆低價大單牽著走：用半價把 344 USD 借出去了

- 日期：2026-08-16
- 分支：`fix/pricing-market-floor`
- 狀態：**已修正**（事故已發生，資金已用錯誤價格借出）

### 事故經過

| 時間 | 事件 |
|---|---|
| 19:31:31 | 第一筆成交：344.30 USD、0.000250/日（年化 9.12%）、2 天期 |
| **21:21:52** | **借款人提前還款**，344.30 USD 回到融資錢包（實際只借了 1 小時 50 分） |
| 21:21:56 | 機器人重新掛單，算出 **0.000150/日（年化 5.47%）** |
| **21:31:57** | **成交**——344.30 USD 用大約市場一半的價格借出去，最長鎖 2 天 |

事故當下市場並沒有下跌：最近 60 分鐘 fUSD 成交 9,595 萬 USD，中位數 0.000291
（年化 10.62%），**89.4% 的成交在 0.000250 以上**。

### 根因一：訂單簿講「有人開價多少」，講不出「借款人實際付多少」

當時簿子最底端有一道 **182 萬 USD 掛在 0.00015** 的牆：

```
0.00014999        775.90 USD
0.000149995       250.00 USD
0.00015      1,821,212.68 USD   ← 牆
0.0001529999      281.47 USD
```

D030 的排隊規則是「在**排我前面的錢不超過 `target_queue_usd`（100 萬）**的前提下，
挑利率最高的那一檔」。有了這道牆，**任何高於 0.00015 的價位前面都排著 182 萬**
——條件在牆以上無解，於是規則一路跟著牆掉到牆的價格。

**演算法沒有錯，錯的是它的輸入不完整。** 訂單簿是「別人願意用什麼價錢賣」，
而一個人願意賤賣不代表市場價格。真正能證明某個價位賣得掉的是**成交紀錄**。

### 根因二：四捨五入把我們從牆前面推到牆後面

排隊規則算出的是 `0.000149995`，那個價位排在牆的**前面**。但送出前有一行
`round(base_rate, 6)`：

```
round(0.000149995, 6) = 0.00015   ← 正好等於牆的利率
```

同價位比時間優先，牆先到，**我們被送到 182 萬 USD 的後面**。
對放貸方而言利率越低排越前面，所以四捨五入有一半的機率把我們往後推。

### 根因三：日誌與通知都看不出異常

- `describe_queue()` 用的是 `rate <`（嚴格小於），把同價位的錢排除在「前面」之外
  ——與 `_price_from_depth()` 的算法互相矛盾（後者一直是把當檔金額算進去的）。
  當晚日誌報「前方 1,026 USD」，真實情況是 **182 萬**，差了 1,775 倍。
- `format_rate()` 用 6 位小數，把 `0.00014999` 顯示成 `0.000150`
  ——與那道牆看起來一模一樣。
- 日誌裡沒有任何一個數字代表「借款人現在實際付多少」，所以
  「掛出 344.30 USD，利率 0.000150」這一行看不出它是半價。

### 決策

**1. 新增成交價下限**：`api` 層新增 `get_recent_trades()`（公開端點
`/v2/trades/{symbol}/hist`），策略以「同天期成交的**金額加權中位數**」為常態成交價，
掛單利率不得低於 `常態成交價 × market_floor_pct`（預設 0.85）。
**下限只往上拉、不往下壓**：排隊規則算出的價位若已高於下限，那是市場給的好價錢。

這與 D030 「不要用 `max(base, minimum_rate)` 把價格拉高」**不衝突**，差別在下限的來源：
`minimum_rate` 是寫死的常數，拉上去可能整個超出簿子；而這個下限取自實際成交，
**某個價位有成交紀錄，就證明那個價位賣得掉**。

**2. 常態成交價要用金額加權，不能用筆數。** 這一項走過一次彎路，值得記下來：

- 第一版寫成「按時間分桶、每桶取中位數，再取各桶中位數的中位數」，
  想沿用 D030「剔除爆發桶」的思路。
- **實測不可用**：那會讓「1 筆 150 USD 的死時段」與「1211 筆、8,675,257 USD 的
  活躍時段」各算一票。同一個時間點，只要把取樣窗從 20 分鐘拉到 43 分鐘，
  算出來的常態價就從年化 8.75% 掉到 **5.47%**——**這種下限擋不住任何東西。**
- 改用金額加權中位數後，同一份資料在三種窗口下算出 9.27%／9.94%／11.45%，
  從不塌到牆價。原因是一筆大額借款會被拆成很多筆成交紀錄，
  **筆數衡量的是撮合的破碎程度，不是市場規模**——實測利率低於 0.00016 的成交
  佔筆數 11.5%、佔金額 29.9%。

**3. 只採計同天期成交。** 天期溢價很大（同一小時內 2 天期中位數 0.000261、
30 天期 0.000319、120 天期 0.000320），混在一起會把短天期的下限拉高而掛空
——那是 FRR 落後問題換個來源重演。

**4. 送出前一律無條件捨去**（`_quantize()`，預設 8 位小數），不再 `round()`。
少賺捨去的零頭，遠比排錯位置便宜。

**5. `describe_queue()` 改用 `<=`**，同價位的錢算進「前面」，與 `_price_from_depth()`
一致。這也是 P1-4（D031）能不能實作的前提——那項要拿排隊金額當否決條件，
而在此之前這個數字在有牆的時候會離譜地低估。

**6. `format_rate()` 改 8 位小數**，通知與日誌看得到真正有差別的位數。

**7. 每輪抓 10000 筆成交**（端點上限）。實測 1000 筆在活躍時段只涵蓋 **1.2 分鐘**，
樣本不足會讓策略整輪不掛單——這是實作過程中自己踩出來的坑，靠實打才發現。

**8. `minimum_rate` 由 0.0001 提高到 0.00021918**（**年化 8.00%**，使用者 2026-08-16 指定）。
語意是「年化 8% 以下我不借」，低於它的那一輪整輪不掛單。

**這條線會實際咬到，不只是防呆**：歷史成交帶是年化 8.68%～10.00%，8% 貼在下緣。
搭配 `market_floor_pct` 0.85 來看，常態成交價要在年化 9.41% 以上，成交價下限才會
高過這條線；低於 9.41% 時真正生效的是這條地板。所以在本次事故那種
「簿子被低價牆佔住」的情境下，新版的行為是**整輪不掛單**，而不是退而求其次掛
年化 7.88%——這正是使用者要的語意。代價是市場走軟時機器人會閒置
（空轉一天約損失 0.074 USD，以 344 USD 計）。

**9. 還款通知要講清楚**：`positions_closed()` 補上實際借出時長、是提前還款還是到期、
以及利息毛估。Bitfinex 的天期是**上限不是保證**，這次掛 2 天實際只借 1 小時 50 分，
而原本的訊息只寫「借出的資金已收回」，看不出那是一次提前還款。

### 驗收

用**當下的真實市場**跑修正後的策略，並把那道牆放回簿子重演事故
（常態成交價 0.00025000／年化 9.12%，成交價下限 0.00021250／年化 7.76%，
絕對地板 0.00021918／年化 8.00%）：

```
事故重演（把 182 萬的牆放回簿子最底端）
  舊版（只看簿子）會掛：0.00014999  年化 5.47%   ← 今晚實際掛出去的價
  新版                ：本輪不掛單（算出來低於年化 8% 的地板）

同一時刻沒有牆的真實簿子
  新版會掛            ：0.00026395  年化 9.63%
```

兩道防線的分工在這次驗收裡看得很清楚：**成交價下限**負責「別跟著牆賤賣」，
把價位從 5.47% 拉到 7.76%；**絕對地板**再負責「7.76% 我也不賣」，於是整輪不掛。
沒有牆的正常市場上兩者都不介入，排隊規則照常運作——**它們只在被賤賣時才出手**。

測試 469 → 479 項。

### 留給下一步的觀察

驗收當下的市場，排隊規則算出年化 11.61%，而金額加權的常態成交價是 9.27%
——**掛單價明顯高於一半的錢實際成交的價位**。這不是本次修的東西
（`target_queue_usd = 1_000_000` 是人手算的旋鈕），但它正是 D032 要處理的問題：
掛多高才划算，應該由程式用期望值算，而不是填一個常數。

## D034 — 重掛判準：D031 指定的「排隊位置守門檻」實測不成立，改用推導出的單位時間報酬

- 日期：2026-08-16
- 分支：`fix/requeue-queue-position-guard`
- 狀態：已實作
- 取代：D031 的「修法」一節（背景與缺陷描述仍然成立，**處方不成立**）

### 先回答 D031 留下的疑點：「前方 0 USD」是假象

D031 要求動手前先查清楚 19:31 那一輪日誌上的「同天期前方 0 USD、全天期前方 0 USD」
是真實狀態還是讀取假象。**查清楚了：是假象，而且真相與它相反。**

三件事各自查證：

1. **`len=250` 截斷**——不影響。實測當下的 fUSD 簿子，累積金額超過
   `target_queue_usd`（100 萬）只需 **49 檔**，而我們抓 250 檔、涵蓋 497 萬 USD。
   截斷只會砍掉利率最高的那一端，砍不到「排在我們前面」的部分。
2. **P0 聚合精度**——不影響。250 檔裡有 24 個利率出現多列，全部都是**同利率不同天期**
   （回應本來就是 `[RATE, PERIOD, COUNT, AMOUNT]`），不是精度造成的重複。
3. **舊版 `<` 的比較**——**就是這個**。事發當下的 `describe_queue()`（commit `c62dd8e`）
   用的是 `rate < 我們的價位`，而 `_price_from_depth()` 回傳的必定是**簿子上存在的某一檔**。
   兩者組合起來可以證明一條定理：

   > 舊版報「前方 0 USD」⟺ 算出來的價位正好落在簿子**最低**那一檔。

   以真實簿子的 36 個子集逐一驗證，無反例。而定價落在最低檔時，真實的前方金額
   等於那一檔的**全部金額**，且該檔＋次檔必定超過 100 萬（否則定價會往上走一檔）。
   把 19:31 的情境重演（在簿子底端放一道 120 萬／200 萬 USD 的牆）：
   **舊版報「前方 0 USD」，新版報「前方 120 萬／200 萬 USD」——完全相反。**

D033 已經把 `<` 改成 `<=`，所以這個數字現在是對的。但**它描述的對象仍然是錯的**，
見下一節。

### 第二個誤讀：那兩個數字的主詞從來就不是「場上那張單」

`_log_queue_position()` 傳給 `describe_queue()` 的是 `plans[0].rate`，也就是
**本輪新算出來的候選價位**。19:31 的日誌被讀成「我們那張單排到第一位了」，
但它講的其實是「新算出來的價位落在簿子最低檔」。

這個區別在市場變動時會指向**完全相反**的方向：低價牆一出現，候選價位被拉到簿子底端
（前方看起來很空），而場上那張既有的單反而是隊伍前段最快成交的那一張。

順帶可以推回 19:31 那一輪重掛的**真正方向**：候選價位＝簿子最低檔，而我們自己
0.000250 的單也在簿子裡，所以候選價位 ≤ 0.000250；又因為重掛被觸發代表差距超過 2%
容差，所以候選價位 **< 0.000245**。也就是說——

> **19:31 那一輪要做的是「把價格往下調」，不是 D031 寫的「掛更高的利率」。**

它與 21:31 的半價事故是**同一個機制**（低價牆把報價往下拖），只是當時被 `<` 的
日誌假象掩蓋，被誤讀成相反的故事。

### 為什麼不採用 D031 開的處方

D031 的修法是「前方排隊金額低於門檻時一律不動單」。**在真實簿子上實測，這個規則
的方向是錯的。**

排隊金額對利率是**單調**的：掛得越便宜，排在前面的錢越少。所以「前方金額少」
幾乎等同於「這張單掛得比市場便宜」——固定門檻鎖住的，正好是**最該往上調價**的那些單。

2026-08-16 深夜的真實簿子，以 344.30 USD、2 天期實測：2% 容差擋不住的 64 個往上調
價位，重掛的期望值**全部為正**；前方只剩 411 USD 的那一檔淨賺最多（+0.0418 USD）。
若採用「一個巡檢週期的成交量」當門檻（實測校準約 10 萬 USD），這 64 個全部會被否決掉。

**同時記下一個一併被推翻的中間版本**：曾考慮「利率更差、隊伍又更長就不動」這種
不需模型的支配判準。因為單調性，這種情況除了完全平手之外**不可能發生**，該判準是空的。
**重掛永遠是取捨，沒有免費的判斷。**

### 決策

**把價格往下調的重掛，要先證明划得來；往上調不受這條限制。**

判準用單位時間報酬（`利息 ÷ (等待 + 借出期間)`）比較兩條路。設 `r` 為利率、
`W` 為等待天數、`P` 為天期，重掛較好的條件是

    r_new / (W_new + P) > r_live / (W_live + P)

其中 `W = 前方金額 ÷ 隊列消化速率`。**關鍵性質是分母幾乎不動**：實測等待多在
0～6.4 小時之間，而 `P` 是 48 小時——所以利率那一項壓倒性地決定結果，
**結論對速率估得準不準並不敏感**。這正是這條式子現在就能用、而完整的 D032 還不能用的原因。

**為什麼只管往下這一個方向**（不是隨手選的，是不確定性的擺放位置決定的）：

- **往下調**：放棄的利息是**確定的**，換來的速度是**估的**
- **往上調**：多賺的利息是**確定的**，付出的速度是**估的**

「估的」那一半正是目前最不可靠的東西——把排隊金額換算成等待時間只有**一個校準樣本**，
而且實際比估計慢 1.7 倍（D031）。所以只在「不可靠的那半邊是行動的理由」時才要求它
先過關；反過來時讓確定的那半邊說了算。這是 D031「判斷不出來時偏向代價小的那一邊」
按方向拆開之後的樣子。

**金額變多時一律不否決**：那代表錢包裡有新的錢要投入，而 `spread_count = 1` 時
重掛是唯一的投入手段，少賺的價差遠小於讓那筆錢繼續空轉。

新增設定 `engine.queue_clear_usd_per_hour`（預設 540000）。**這個數字取自唯一一筆
真實成交**：前方排隊 73 萬 USD、1.35 小時後成交。注意它遠低於訂單簿的成交流量
（當日 2 天期約 415 萬 USD/小時）——**成交量不等於隊列消化速度**，用後者才對得上
實際等到的時間。

### 一併修掉的第二個缺口：取消送出後的空窗（D031 的「順帶處理」）

取消是非同步的，回應成功不代表單子已經離場。原本的程式在等待之後**用餘額回推**
狀態，而 19:31 證明這兩件事會分岔：那次餘額確實沒回來，但原因不是「還沒生效」，
而是**那張單根本沒被取消掉、25 秒後成交了**。兩種情況在餘額上長得一模一樣，
處置卻完全相反——單子還在場上時再掛一筆就是**雙倍曝險**。

改為等待後**再查一次場上掛單**：仍有單就整輪不重掛、寫 WARNING、下一輪重新判斷。
也因此不會再推出「掛單已不在場上」那種與事實相反的通知。

### 驗收（2026-08-16 深夜，真實市場）

```
情境 1：19:31 重演——把 182 萬 USD 的牆放回簿子底端
  場上 0.00025000（年化 9.12%）  前方 2,083,033 USD
  候選 0.00014999（年化 5.47%）  前方         0 USD   ← 當晚實際掛出去的價
  利率 -40%、等待由 3.9 小時降到 0
  → 修正前：重掛　　修正後：**不動（不划算）**
     48 小時的天期面前，省下 3.9 小時遠遠補不回四成利息

情境 2：當下的真實簿子，掃過 223 個可能的場上利率
  行為改變（原本會重掛，現在不動）：82 個，全部落在候選價位之上（往下調的方向）
  往上調價、行為不變：82 個（判準刻意不介入這個方向）
  其餘不變：59 個 → **這條判準會擋掉四成的降價重掛，不是全部**

情境 3：82 個比候選便宜的場上價位，被誤擋的：0 個
```

測試 479 → 493 項。

### 附帶發現

驗收當下（2026-08-16 深夜）的真實簿子**底端又有一道低價牆**：純看簿子會算出
0.000149（年化 5.44%），D033 的成交價下限把它拉到 0.00020959，再被年化 8% 的
絕對地板擋掉，**策略本輪不掛單**。這道防線上線不到一天就第二次出手，
表示那種牆不是 8/16 夜間的偶發事件。

### 對後續工作的影響

- **D032（P1-5）的範圍變大也變清楚了**：本次證明「重掛永遠是取捨」，沒有不需模型
  的捷徑。D032 要補的是**天期選擇**與**等待時間的即時估計**（含爆發桶剔除），
  而 `queue_clear_usd_per_hour` 這個只有一個樣本的常數正是它要吃掉的第一個旋鈕。
- **往上調價的方向目前完全沒有把關**，這是刻意的（實測期望值全為正），
  但那份實測只有一份簿子快照。市場結構改變時要重新量。

## D035 — 排隊位置是錯的定價基準：這個市場的成交是陣發掃單，站在最前面只保證賣最低價

- 日期：2026-08-17
- 分支：`fix/market-floor-goes-stale`
- 狀態：**已實作**（`strategies/expected_value.py`，2026-08-17）
- 取代：D030 的「排隊位置定價」為主要定價基準；修正 D033 對「低價牆」的定性
- 相關：D032（期望值計算）、D033（成交價下限）、D034（重掛判準）

### 背景：一天空轉之後，推演發現資金回來也掛不出去

2026-08-17 全天 0 筆掛單（344.3 USD 鎖在 08-16 21:30 那筆年化 5.47% 的部位裡）。
用專案自己的策略對當下市場推演，得到 `build_offer_plan(344.3) → 0 筆`：
排隊定價算出年化 5.47%，被年化 8% 的 `minimum_rate` 擋下。
簿子最前面是一道 **445 萬 USD、0.00015、2 天期**的牆（D033 那道 182 萬的 2.4 倍）。

### 第一個結論是錯的，記下來當教訓

當下 30 分鐘內「年化 8% 以上成交佔 0.0%」、金額加權中位數年化 5.47%，
據此得到「市場跌到 5.5%，8% 地板過期了」。**這個結論用一段太短的窗代表市場，
與 D030 記過的爆發桶陷阱是同一類錯誤**，只是這次窗太短而不是太偏。

### 查證：市場沒有跌，它在每小時之內劇烈震盪

1 小時 K（`/v2/candles/trade:1h:fUSD:p2/hist`，5000 根，2026-01-21 起）：

- 最近 7 天：收盤 ≥ 年化 8% 佔 46.7%，**當根曾觸及 8% 佔 89.3%**
- 最近 30 天：收盤 ≥ 年化 8% 佔 44.7%，**當根曾觸及 8% 佔 90.0%**

單根振幅動輒 5 個百分點以上（08-17 20:00 那根：開 7.26%、收 5.47%、
**高 9.78%**、低 4.92%）。所以「年化 5.47%」不是市場價，
**那只是最後一筆成交剛好落在區間底部**。

這同時解釋了 08-16 的兩筆成交：19:31 以 9.12% 成交（該小時最高 11.68%）、
21:31 以 5.47% 成交（**該小時最高 11.77%**）。
**D033 稱之為「事故」的那筆，是在一個曾漲到 11.77% 的小時裡賣在底部。**

### 決策一：排隊位置不再當主要定價基準

`_price_from_depth()` 的模型是「排越前面越快成交」，前提是需求會**穩定地**
從簿子前端一路吃過來。實測不成立：**這個市場的成交是陣發掃單**，
需求來的時候一口氣掃到 9~10%，沒來的時候前端也不動。在這種結構下——

> **站在隊伍最前面，不會讓你更快成交，只會保證你用最低價成交。**

`target_queue_usd = 1_000_000` 是 2026-08-16 簿子還薄的時候校準的；
簿子底端一旦被大額低價單佔住，那個條件就會**強制**把報價押到牆價上。
這不是參數調得不好，是**模型的自變數選錯了**。

### 決策二：改用期望值選價（即 D032／P1-5，本決策把它從「該做」升級為「唯一擋路的事」）

以「某根 1 小時 K 的最高價 ≥ 掛單利率」判定會被掃到，
實質年化沿用 D034 的式子 `r × 48 ÷ (等待 + 48)`：

| 掛單年化 | 中位等待 | 平均等待 | 實質年化（7 天） | 實質年化（30 天） |
|---|---|---|---|---|
| 5.50% | 0.5h | 0.5h | 5.44% | 5.44% |
| 8.00% | 0.5h | 0.6h | 7.90% | 7.90% |
| 9.00% | 0.5h | 1.3h | 8.76% | 8.81% |
| 9.75% | 0.5h | 2.7h | **9.23%** | 9.40% |
| 10.50% | 0.5h | 11.7h | 8.45% | **9.61%** |

**現行策略給出 5.47%，同一份資料的最佳解是 9.2~9.6%——差約 4 個百分點。**
等待成本要到年化 10% 以上才開始咬人，因為九成的小時都會掃到 8% 以上。

### 決策三：`minimum_rate` 年化 8% 維持不動

它是目前唯一在保護我們的東西，擋掉的正是「賣在區間底部」。
保留成本接近零（8% 的平均等待 0.6 小時）。
**一度打算調低它，那個念頭來自上面那個錯誤結論。**

### 決策四：修正 D033 對「低價牆」的定性

D033 寫「那道牆代表的只是某一個人願意賤賣，不是市場的價格」。
**牆是事實，但它不是偶發事件，而是這個市場的常態結構**（一天之內從 182 萬長到 445 萬）。
D033 補的成交價下限仍然有效且必要，但它處理的是症狀；
**真正的病因是拿排隊位置當定價基準**。

### 附帶發現：`get_funding_book()` 的 `len=250` 註解已經過期

註解寫「250 檔對應約 500 萬 USD，足以蓋過整個供給側」。實測當下可見的 250 檔
總計 570 萬 USD、**最高只到年化 8.33%**——簿子在 8% 以上的部分我們完全看不到。
D034 驗證過的是「累積到 100 萬只要 49 檔」，那個結論對排隊定價仍成立，
但**對「市場高端長什麼樣」是盲的**。改用期望值定價後，價位會落在 9% 以上，
屆時簿子本身就不再是主要資料源，這個盲區的影響隨之改變——實作時要重新評估。

### 實作（2026-08-17，同分支）

新增 `strategies/expected_value.py`，**繼承 `OrderBookDepthStrategy`**：金額拆分、
風控上限、成交價下限、利率量化、排隊位置描述全部共用，
**只有「怎麼決定 `base_rate`」這一步不同**。這樣兩個策略的差異就是一個可以單獨
檢視的方法，不是兩份平行演化的程式碼。

- **`api.get_rate_candles()`**（新）：`/v2/candles/trade:{tf}:f{ccy}:p{period}/hist`。
  **`p{period}` 不能省**——不指定天期會把所有天期混在一起，而 2 天期佔 86% 的供給。
- **`estimate_wait_hours()`**：逐根走訪算連續落空的長度，**不是命中率取倒數**。
  倒數法會把「平均 3 小時一次」與「六小時空手、接著連中三次」算成同一件事，
  而這個市場正是後者。尾端沒等到的那一段**不計入**（右設限資料，計入會系統性低估）。
- **`choose_rate()`**：候選價位直接取自窗內出現過的 `high`——沒有掃到過的價位不該
  成為候選，這同時就是天然的上限，不必另外設一個「最高不准超過多少」的旋鈕。
- **`ev_min_hits`（預設 5）**：窗內最高的那一兩根 K 永遠只命中 1 次，
  不擋的話期望值會一路爬到一個只發生過一次的價位，然後掛在那裡等一個不會再來的掃單。
- `strategies/base.py` 新增 `requires_candles` 旗標，迴圈層據此決定要不要打端點
  （沿用 `requires_book` / `requires_trades` 的既有做法）。

### 實作時才看清楚的一件事：這條算式對等待非常寬容

`r × 48 ÷ (等待 + 48)`——借出期間 48 小時是分母的大宗，**等 8 小時只讓實質年化打 86 折**。
所以利率高兩成的價位就算要多等 8 小時仍然勝出；年化 12% 要輸給 9.5%，平均得等上約 48 小時。

這是寫測試時被自己的測試資料打臉才看清楚的（原本以為「20% 但要等 8 小時」會輸給
「9% 立刻成交」，實際上前者實質年化 17.1%、後者 8.9%）。

**這個性質有兩面**：它是策略敢掛高價的全部理由，但也意味著**沒有 `ev_min_hits` 的話，
期望值會一路爬到尾端那個不會再來的價位**。兩者是同一件事的兩面，已用測試釘住
（`test_借出期間夠長時等待幾小時幾乎不影響選擇`）。

### 驗收（真實市場，2026-08-17 20:5x）

同一份市場資料餵給新舊兩個策略：

| | 掛單計畫 | 利率 | 說明 |
|---|---|---|---|
| `orderbook_depth`（舊） | **0 筆** | —— | 排隊定價算出年化 5.47%，被 8% 地板擋下 |
| `expected_value`（新） | **1 筆** | **年化 9.96%** | 平均等待 3.1h、窗內命中 40 次、**實質年化 9.35%** |

單元測試另以「低價牆」情境把兩者的相反行為釘成迴歸測試。測試 493 → 512 項。

### 尚未做的部分：天期仍然寫死 2 天

D032 與 P1-2 都指出**天期與利率是同一個期望值問題的兩個維度**，應該在同一處算。
本次**只做了利率那一維**，`offer_period` 仍是設定檔裡的 2。

理由是資料形狀不同：K 線端點的天期是**參數**（`p2` / `p7` / `p30`），要比較天期就得
一輪打三次、而且三條序列的 `high` 分佈要各自估等待。那是另一次改動的份量，
而目前資金鎖在 08-16 那筆、到期前必須先讓「掛得出去」這件事成立。
**列為 P1-5 的剩餘部分。**

## D036 — 六個決策兩天內互相推翻：問題不在判斷力，在於沒有量測基礎

- 日期：2026-08-17
- 分支：`docs/audit-and-roadmap`
- 狀態：已決定（規劃層決策，改動見 PLAN.md 的分期路線圖）
- 相關：D030～D035（本決策解釋的正是這串決策自我推翻的成因）

### 觀察到的現象

2026-08-16～17 兩天之內，定價相關的決策出現六次，而且**後面的一再推翻前面的**：

| 決策 | 主張 | 後續 |
|---|---|---|
| D030 | 排隊位置定價取代 FRR | **被 D035 推翻**（自變數選錯） |
| D031 | 重掛要看排隊位置守門檻 | **處方被 D034 推翻**（方向相反） |
| D032 | 等待時間該由程式自己算 | 成立，但主角認錯了（點名 `queue_clear_usd_per_hour`，實際過期的是 `target_queue_usd`） |
| D033 | 低價牆是「某個人願意賤賣」 | **定性被 D035 修正**（是常態結構，不是偶發） |
| D034 | 往下調價要先證明划得來 | 成立，但**這次盤查發現它已退化**（見下方 A2） |
| D035 | 陣發掃單，改用期望值定價 | 目前有效，**但驗證方式與前面幾個完全相同** |

### 根因：每一個決策都是用「一個時間切片」做出來的

上面每一條的證據，都是在對話中臨時抓一次即時資料、當場分析、把結論寫成常數塞進
`config.yaml`，然後把那份資料丟掉。於是：

- **沒有累積的市場資料**。每次分析都重抓一次，用完就丟——DB 裡有 `loan_offers`、
  `earnings_daily`、`funding_positions`、`bot_state`，**沒有任何一張表存過市場長什麼樣**。
- **沒有辦法在上線前用歷史資料檢驗策略**。D030 的排隊模型如果當時能對 30 天的資料
  跑一次，「站在最前面只保證賣最低價」當場就會現形，不必等到用半價借出去才發現。
- **沒有辦法量測改動有沒有效**。目前唯一的成效證據是兩筆成交，
  而且其中一筆是事故。

**結論不是「判斷要更小心」——那句話沒有可執行的內容。**
真正的差別在於：這些結論全都是**可以用歷史資料否證的**，只是專案還沒有那個能力。

> **在補上量測能力之前，再多的策略決策都只是換一個時間切片重寫一次同樣的錯誤。**

### 決策：量測基礎建設優先於下一個策略決策

具體路線見 PLAN.md 的分期路線圖，這裡只定原則：

1. **市場資料要落地**。每輪把當時的簿子摘要、成交摘要、K 線指標寫進 DB。
   成本極低（每輪幾百位元組），但它是後面所有事情的前提。
2. **策略改動要先在歷史資料上跑過才上線**，而且窗要跨過不只一種市場狀態。
   D035 的回測（7 天／30 天兩個窗）是目前唯一做過這件事的決策，
   **這個規格從此是下限，不是加分項**。
3. **成效要能量測**：實際拿到的年化 vs 當時可達到的最佳，兩個數字要能對照。
   沒有這一對數字，「策略變好了」永遠只是說法。

### 給未來的自己：新旋鈕上線前的三個問題

D032 已經講過「人手填的常數會過期」，但 `target_queue_usd` 還是過期了，
因為那條教訓沒有變成可執行的檢查。定成三個問題：

1. **這個數字是怎麼來的？** 取自幾個樣本、涵蓋多長的時間？
2. **它什麼時候會過期？** 市場的哪一種變化會讓它失效？
3. **過期時程式怎麼察覺？** 如果答案是「不會，要靠人發現」，那它就不該是常數。

`ev_window_hours: 168` 目前對第 3 題的答案仍然是「不會」——**它是這個策略裡
唯一還沒過關的旋鈕**，已列入路線圖第二期。

---

## D037 — A2 拆成「修掉說謊」與「決定政策」兩件事；閒置時間目前完全沒有上限

- 日期：2026-08-18
- 分支：無（依使用者指示直接在 `main` 更新文件）
- 狀態：已決定（排序與修法方向，程式碼尚未動）
- 相關：D026（靜默失效）、D034（重掛判準）、D035（期望值定價）、D036（量測優先）
- 前情：TASKS.md 的 A2；PROGRESS.md 2026-08-18 那一節

### 背景：D036 的原則與 A2 的急迫性撞在一起

D036 才剛定下「量測基礎建設優先於下一個策略決策」。而 A2（重掛守門檻退化成
「永遠擋下往下調價」）看起來就是一個策略決策——要改用哪一個等待估計器？
按 D036 的字面意思，它應該排在 M1 之後。

**但把 A2 整包當成策略決策，會漏掉它其實同時是一個 bug。** 兩者必須拆開：

| | 性質 | 能不能現在做 |
|---|---|---|
| **A2-a　守門檻在算不出來時偷偷否決** | **Bug**，而且是靜默失效 | **可以**，不需要任何市場知識 |
| **A2-b　新策略下的重掛政策該長怎樣** | **策略決策** | **不行**，要等 M1／M2 的資料 |

### A2-a：這不是「政策保守」，是函式在說謊

`_queue_ahead()` 的契約是「掛在這個價位時前面排著多少錢」。當候選價位高過
訂單簿可見的 250 檔時，它回傳的是**整本簿子的總額**——那個數字的真實語意是
**「至少這麼多，實際不知道」**，但它以「就是這麼多」的形式回傳出去。

於是 `_cheaper_repost_is_not_worth_it()` 拿到兩個一模一樣的數字，
`利息 ÷ (等待 + 借出期間)` 的分母約掉，判準退化成純粹比利率；
而該函式的前置條件已經保證 `candidate.rate < live_rate`，
**所以它的回傳值在這個情境下是恆定的，永遠是「划不來」**。

**一個永遠給同一個答案的判斷式，等於沒有判斷式**——差別只在它看起來像有。
這是 D026「靜默失效」的第四次現身：D026 是壞了沒人知道、D030 是成功了沒人知道、
A1 是決定不做但講錯理由，**這次是判斷式已經不再判斷，但日誌照樣印出一句像模像樣的理由**
（`前方 5,381,114 → 5,381,114 USD`，兩個數字一樣就是自白）。

**修法（不含任何策略選擇）**：`_queue_ahead()` 在候選價位越出可見範圍時回傳
`None`（或明確標記「越界」），讓上層**棄權**——`_cheaper_repost_is_not_worth_it()`
本來就已經有 `ahead is None → return None` 這條路徑。棄權的意思是
「這一項我判斷不出來，不由我擋」，而不是「我判斷結果是不要」。

**這與 A1 的修法是同一條原則**：**講「不知道」遠比講一個具體但錯誤的原因好。**
A3（排隊位置日誌是截斷值）根因完全相同，一起處理。

### ⚠️ 棄權會鬆開目前唯一擋著降價的東西，所以要同時補上限

必須誠實記下這個順序風險：A2-a 修好之後，往下重掛就不再被無條件擋住了。
在 A2-b 的政策定下來之前，這段期間的行為由 `_plans_match()` 的 2% 利率容差
＋ 期望值策略自己決定——**而目前沒有任何機制為「錢閒置多久」設上限**。

- 2026-08-18 的實測：掛單閒置 3.6 小時，最後靠一波掃單成交
- **但那 3.6 小時沒有任何程式在計時，也沒有任何門檻會在第 N 小時介入**
- 閒置資金的年化是 **0%**，這是唯一一種「什麼都沒發生但確定在虧」的狀態

所以 A2-a 要**連同一個看得見的閒置時間量測**一起做（先量測、必要時才設門檻，
順序與 D036 一致）。**不要在沒有資料的情況下直接拍一個「超過 N 小時就降價」的常數
——那正是 `target_queue_usd` 的死法。**

### 🔴 2026-08-18 那筆成交不能拿來支持任何一邊

當天結果很漂亮（實質年化 9.27% vs 立刻成交的 5.47%），很容易被讀成
「撐住高價是對的，A2 這個 bug 其實幫了忙」。**這個推論不成立**，理由有二：

1. **A2 當天根本沒被觸發**。每一輪擋下重掛的是 2% 利率容差，
   候選價位始終在 0.0002729 附近（168 小時窗把短期下跌平滑掉了），
   從沒進到守門檻那段程式碼。
2. **一個樣本。** 它證明的是「陣發掃單真的存在、撐住高價有時候會贏」，
   **不是**「撐住高價的期望值比較高」，更不是「無上限地撐住是對的」。

把它讀成 A2 的背書，就是 D036 描述的那個錯誤再犯一次——而且是在 D036 寫完的隔天。

### 決策

1. **A2-a ＋ A3 現在做**：讓越界時棄權而非偷偷否決，並把閒置時間量出來。
   這是修 bug，不是選策略，不受 D036 的等待條款約束。
2. **A2-b 留到 M1／M2 之後**：新策略下的重掛政策要在回測工具上跑過才定。
3. **M1（市場資料落地）仍是下一個主要工程**。2026-08-18 那筆成交是專案史上
   資訊量最大的一次觀測——市場常態價跌到 5.47%、我們掛 9.96%、掃單吃穿——
   **而它現在只存在於四行日誌與一列 `funding_positions` 裡。**
   簿子當時長什麼樣、掃單多大、吃掉幾檔，全部沒有留下。
   **今天的教訓不是「策略對了」，是「最該被記錄的一天，我們沒有能力記錄」。**

### 附帶：目前規模下真正的產出是知識，不是利息

三筆成交累計毛利息約 0.29 USD、扣費後約 0.25 USD，而且**是手算的**
（`earnings_daily` 仍為空表，見 PLAN 第 3 期 P2-2）。

在 344 USD 的規模下，任何策略改良的金額差異都小到無法用損益判斷對錯。
**這反過來提高了 M1／M3 的優先級**：既然分不出勝負的是金額，
就更需要「實際年化 vs 當時可達到的最佳」這一對數字來分勝負。

## D038 — 等待估計問錯了問題：要問「我進場要等多久」，不是「命中間隔平均多長」

- 日期：2026-08-19
- 分支：`fix/honest-wait-estimate-and-idle-tracking`
- 狀態：**已部署**（2026-08-19 23:44，PR #33，main `da546c2`）
- 相關：D026（靜默失效）、D033（日誌看不出推導）、D035（期望值定價）、
  D036（量測優先）、D037（A2 拆解、閒置無上限）
- 觸發事件：2026-08-19 05:03:19 借款人提前還款（原定 08-20 22:11 到期，提前 41 小時），
  05:03:24 以年化 9.78% 重新掛單（offer `5084375241`），**至當日 23:09 已閒置 18.1 小時未成交**

### 現場：模型說等 2.6 小時，實際等了 18 小時

當輪日誌只有一句 `期望值定價：115 個候選價位，選中年化 9.78%（平均等待 2.6h…）`，
之後 108 輪每一輪都印同一句「維持不動以保住排隊位置」。

查 K 線才看出關鍵時序：**掃到 9.78% 的兩根 K（03:00 的 9.88%、04:00 的 9.96%）
都發生在掛單之前**，05:00 之後 18 小時的最高只到 9.12%（22:00 那根）。
不是掛錯價，是**模型沒告訴我們這個價位會有多痛**。

### 根因：`fmean()` 把剛保留下來的陣發性又抹掉了

`estimate_wait_hours()` 的 docstring 白紙黑字寫著：

> 逐根走訪，不用「命中率取倒數」……「六小時空手、接著連中三次」與
> 「平均兩小時一次」在倒數法下完全一樣，實際的等待體驗差很多。

**意圖完全正確，但最後一行 `statistics.fmean(waits)` 把它推翻了**：
`[6, 0, 0]` 的平均是 2，`[2, 2, 2]` 的平均也是 2。它逐根走訪保留了間隔序列，
然後取平均，於是兩者又變成同一個數字。

單元測試 `test_陣發與均勻分佈算出來的等待不同` 甚至**證明過它「分得出來」**
——1.417 vs 1.500。但那是 6% 的差距，小到在期望值計算裡不影響任何選擇。
**測試證明的是「有差」，不是「差得夠多」，這兩件事在這裡差了 60 倍。**

正確的問題是：**我在一個任意時刻掛單，要等多久**。隨機進場比較容易落進長的那段
空檔（統計上的等候悖論），所以要從**每一個小時各出發一次**算等待，
長空檔就會依它實際佔掉的時間長度被加權。

同一份 168 小時真實 K 線的對照：

| 掛單價 | 舊：間隔平均 | 新：進場等待 | 中位數 | 舊算實質年化 | 真實實質年化 |
|---|---|---|---|---|---|
| 9.12% | 1.6h | 4.3h | 1.5h | 8.82% | 8.37% |
| 9.78% | 2.3h | 6.0h | 3.5h | 9.34% | **8.70%（新最佳解）** |
| 9.96% | 3.2h | **10.8h** | 5.8h | **9.35%（舊最佳解）** | 8.14% |
| 10.29% | 7.5h | 19.3h | 15.5h | 8.90% | 7.33% |

### 為什麼這是修 bug，不受 D036 的等待條款約束

D036 要求「量測基礎建設優先於下一個策略決策」，而這看起來像在改定價策略。
**但函式沒有做到它自己宣稱的事**——這與 D037 認定 `_queue_ahead()` 越界時
謊報「就是這麼多」是同一類，判準也一樣：**契約與行為不符是 bug，
在兩個都符合契約的方案之間選一個才是策略決策。**

D026 靜默失效的第五次現身：D026 壞了沒人知道、D030 成功了沒人知道、
A1 決定不做但講錯理由、A2 判斷式不再判斷、**這次是估計值系統性偏低 3~4 倍，
而日誌把它印得像個精確的數字**。

### ⚠️ 修正不是單向的：規則命中時新算法反而算出更短

很容易把這條讀成「新算法比較保守」，那是錯的，而且會在下次調參時誤導人。

- **陣發時算出更長**：命中擠成一團，多數起點落在乾旱期（測試：3.75 倍）
- **規則時算出更短**：每 60 根命中一次，隨機進場平均落在間隔中間 → 約半個間隔。
  舊算法在 `test_選的是實質年化最高而不是利率最高` 那份資料上算 47.7 小時，
  新算法算 29.9 小時

兩邊都是同一條定義的結果。**修正的是「算對」，不是「調高」。**

### 右設限：計入而不是丟棄

舊版把「等到資料結束還沒等到」那一段直接丟掉，理由寫的是「當成等了 N 根會系統性
低估」——**方向講反了**。丟掉的正是最長的那些等待，丟掉才是低估。

新版以「至少等到窗尾」計入，並回傳 `censored_ratio`。這樣算出來的仍是**下界**
（真實等待只會更長），所以那個比例要一起印進日誌——**它是這個下界有多不可信的刻度**。
2026-08-19 的真實資料上是 11%。

### 第二層：閒置時間量測（D037 順位 1 的那一項）

D037 已預警「目前沒有任何機制為閒置時間設上限……那 3.6 小時沒有任何程式在計時」，
**隔天就從 3.6 小時變成 18.1 小時，計時器仍然一個都沒有**。

三件事：

1. **`_parse_offers()` 補上 `created_at_ms`**（funding offers 索引 2 = MTS_CREATE）。
   **已對正式帳號實打驗證**：回傳 `'1787087004000'` → `2026-08-19 05:03:24 +0800`，
   與掛單當輪日誌完全一致；MTS_UPDATE 同值，等於證明那張單 18 小時沒被動過。
   **用交易所的時間而不是自己記**，重啟與重新部署都不會弄丟。
2. **每輪印出閒置時數、機會成本，並與掛單當初的預估對照**。機會成本用金額講
   （18.1 小時 ≈ 0.07 USD），因為「18 小時」對人沒有重量，而這個專案三筆成交
   累計毛利息才 0.29 USD。
3. **新表 `offer_wait_forecasts`**：掛單當下的預估一張單一列。

**為什麼只存預估、不存實際等待**：實際等待事後算得出來（掛單時間在 `loan_offers`，
成交時間在 `funding_positions`），**「掛出去那一刻我們以為要等多久」才是不存就
永遠消失的那一半**。策略每輪重算，記憶體裡永遠只有「現在這一輪怎麼想」——
少了這張表，事後只能拿今天的模型解釋昨天的決定，正是 D036 記的那個病。

量測的呼叫點刻意放在 `_log_queue_position()` 之後、所有「要不要動這張單」的判斷
**之前**：閒置最久的輪次走的正是「維持不動」這條提早 return 的路徑，
放在後面就永遠只在重掛那一輪量得到。已用測試釘住。

### 🔴 一個推論錯誤，留在這裡當教訓

第一次診斷這件事時，我寫的是「模型用均勻假設、命中率取倒數（168 ÷ 命中次數）」。
**那是錯的**——程式明確反對倒數法，而且 docstring 就寫著理由。

會誤判是因為 `168 ÷ 54 ≈ 3.1` 剛好對得上日誌印的 3.2h。但那是**數學恆等式**
（總落空數 = 窗長 − 命中數，所以間隔平均必然接近窗長 ÷ 命中數），
不是倒數法的證據。**兩種算法的平均值本來就幾乎一樣，這正是問題所在**：
毛病不在用了哪一種平均，而在**取平均這個動作本身**。

與 C1 那次是同一種錯誤：從一個對得上的數字推出一個聽起來合理的機制，
而沒有去讀那段程式碼。**「數字對得上」不等於「機制猜對了」。**
先讀程式再下診斷，這次是靠讀 `estimate_wait_hours()` 本體才發現真正的毛病。

### 這次刻意沒做的事

- **A2-a／A3（`_queue_ahead()` 越界時棄權）**：仍未做。D037 的順序不變，
  而且 A2-a 一放行就會鬆開降價的閘門——手上還沒有閒置資料就放行，
  等於在市場走弱的日子賭一把。
- **「等太久就降價」的政策**：這是策略決策，要等這次的量測累積出資料
  （D036 的等待條款這次真的適用）。方向已經算過：剩餘等待是重尾的
  （9.96% 這個價位，已等 6 小時後的剩餘等待是 15.1 小時，等 12 小時後仍是 15.0 小時
  ——**等越久剩餘越長**），所以未來的降價判斷應該用「已等 W 小時後的條件剩餘等待」
  重跑同一條期望值算式，**不要拍一個「超過 N 小時就降價」的常數**（`target_queue_usd` 的死法）。
- **分批掛單**：算過，在這份資料上輸給單一價位（最佳拆單 8.56% vs 最佳單點 8.77%），
  因為實質年化曲線是凹的，兩點平均必低於拱頂。只有當目標從「最高期望報酬」
  換成「降低完全沒收入的風險」時才值得重新考慮——**那是另一個目標，要先講清楚**。
- **天期那一維**：`offer_period` 仍寫死 2，P1-5 的剩餘部分不變。

### 部署影響（已驗證）

部署前用真實市場資料與場上實單跑過一次完整決策鏈（純讀取）：新算法選
**年化 9.78%**，與場上那張單**完全同價（0% 漂移）**，`_plans_match()` 判定一致。

**2026-08-19 23:44 部署後第一輪證實了這個預測**：走「掛單條件與場上 1 筆一致，
維持不動」，那張已排隊 18.7 小時的單完整保住。

**一個沒預期到的附帶效果**：舊算法這一輪選 9.96%，與場上那張 9.78% 差 **1.8%**
——**卡在 2% 容差的邊緣**，市場再動一點就會觸發一次沒必要的重掛。
新算法傾向選較低的價位，反而讓場上的單更穩。
**降低等待估計的樂觀程度，連帶降低了重掛頻率**，這一點在動手前沒想到。

部署後第一輪的實際日誌（與部署前最後一輪對照）：

```
23:35 舊：選中年化 9.96%（平均等待 3.2h、窗內命中 40 次、實質年化 9.33%）
23:45 新：選中年化 9.78%（進場等待 平均 6.1h／中位數 3.5h／四分之三在 10.0h 內、
          窗內命中 53 次、實質年化 8.68%、11% 的起點在窗內沒等到「真實等待更長」）
23:45 新：場上掛單已閒置 18.7 小時（機會成本約 0.0719 USD），沒有留下當初的等待預估。
```

**價格只降 0.18 個百分點，但對「自己在賭什麼」的認知完全不同了。**
最後那句「沒有留下當初的等待預估」是刻意設計的退路——那張單是新表出現前掛的，
所以它說自己不知道，而不是拿今天的模型硬湊一個數字回填。
**這與 A1、A2-a 是同一條原則：講「不知道」遠比講一個具體但錯誤的答案好。**

## D039 — A2-a／A3 實作：越界的數字要標示，判斷不出來就棄權（並出聲）

- 日期：2026-08-20（收尾跨到 08-21）
- 分支：`fix/honest-queue-position`
- 狀態：已完成（程式碼、測試、真實資料驗收都做完）
- 相關：D026（靜默失效）、D034（重掛判準）、D035（期望值定價）、D036（量測優先）、
  **D037（A2 拆成 bug 與策略決策，這一條是它的 A2-a 部分）**、D038（等待估計）
- 前情：TASKS.md 的 A2-a／A3／B9；PROGRESS.md 2026-08-20 那一節

### 先講證據：2026-08-20 把 D037 的推論變成量測

D037 是**讀程式碼推論**出「守門檻已退化成永遠擋下往下調價」。2026-08-20 拿到了
現場資料：10:12～15:05 **連續 30 輪**被擋下，每一輪日誌的兩個排隊金額**完全相同**
（`前方 3,535,093 → 3,535,093 USD`）。30/30。

而那天唯一放行的一次（15:15，後來 19:10 成交）**也不是判斷**：那一輪簿子剛好變深、
兩個截斷值不再相同，閘門因此開了。**是資料的巧合。**

> **今天成交了，不等於守門檻是對的。** 它被一個假訊號放行，
> 而成交是市場常態價從 5.47% 漲回 9.12% 掃上來的結果。
> 把它讀成守門檻的背書，就是 D036 那個錯誤再犯一次。

### 決定一：`truncated` 是**整本簿子**的性質，不分桶

簿子是「利率由低往高的前 250 檔」，所以可見範圍內是完整的——低於
`visible_top_rate` 的每一檔都看得到。由此：

- `rate <= visible_top_rate` → 兩個金額都是量測值（同天期那一桶即使是 0 也是真的 0）
- `rate > visible_top_rate` → 兩個金額都只是下界

所以一個旗標就夠。簿子若剛好沒被 250 檔截斷，這裡會把「其實是準的」誤報成越界
——方向偏保守（回報「不知道」），而處置是棄權，**誤報的代價只是少一次判斷**。

空簿子也算越界：一個數字都沒有的時候，「前方 0 USD」同樣是編出來的。

### 決定二：`_queue_ahead()` 越界回 `None`，但**日誌照樣印下界**

同一份資料，兩種責任分開：

| 用途 | 走哪條 | 越界時 |
|---|---|---|
| **拿去比較**（守門檻） | `_queue_ahead()` | 回 `None` → 上層棄權 |
| **照實描述**（日誌） | `_describe_queue()` | 印「至少 N USD」＋可見上限 |

**下界不是沒有資訊**（它至少告訴你隊伍不比這個短），會騙人的是把它講成量測值的
那個語氣。所以 A3 的修法不是拿掉數字，是改掉語氣。

### 決定三：棄權也要出聲

這是動手時才想清楚的一點，值得單獨記：**如果棄權是靜悄悄的，A2-a 只是把
「偷偷否決」換成「偷偷放行」**——日誌上同樣看不出這一項有沒有介入，
D026 的靜默失效換個方向再現一次。所以棄權時會寫：

```
往下重掛的守門檻棄權（候選價位年化 9.50% 已超出可見簿子（可見最高年化 9.04%））：
排隊金額只知道下界、比不出快慢，這一項不擋事，改由利率容差與策略決定
（利率 0.00026800 → 0.00026027）。
```

但**沒有 `describe_queue()` 的策略不印**（`FrrPlusStrategy`）：那不是資料缺口，
是它的模型裡本來就沒有隊伍，每輪印一句「無法判斷」只會變成噪音。

### 驗收：對照組才是重點

三層驗收見 PROGRESS.md。其中最能說明「修的是什麼」的是第 3 層的對照組：
**兩個價位一模一樣（場上 9.78%、候選 9.50%），只有簿子的可見範圍不同。**

- 蓋不住 → 棄權 → 重掛
- 蓋得住 → 排隊金額是真的量測值（258,493 → 146,444）→ **照樣否決**

**A2-a 修的是「算不出來時偷偷否決」，不是把這條判準拿掉。** 沒有這個對照組，
「新版會重掛」看起來會像「判準被拆掉了」。

### ⚠️ 這一改鬆開了目前唯一擋著往下調價的東西

D037 已經預警過，這裡再記一次現況：從此往下重掛只剩 `_plans_match()` 的
**2% 利率容差**與期望值策略自己在擋。真正的重掛政策是 **A2-b**，
要在 M1／M2 的回測工具上跑過才定——**不要拍一個「超過 N 小時就降價」的常數**
（`target_queue_usd` 的死法）。

放行的時機是刻意挑的：2026-08-20 19:10 成交後資金已借出、場上沒有我們的單，
**部署成本為零**；而 D038 的量測也已經收到第一組「預估 vs 實際」
（預估中位數 3.5h、實際 3.93h），D037 要求的前置條件成立。

### 順帶清掉 B9

兩處矛盾註解都是這兩個 bug 的共同根因，一起修：

- `api/bitfinex_client.py`「250 檔對應約 500 萬 USD，**足以蓋過整個供給側**」
  —— 2026-08-19 實測只有 1,306,715 USD、可見最高年化 9.04%。改成明講
  「可見範圍內完整、之上一無所知」，並指向 `truncated`
- `strategies/orderbook_depth.py` 模組 docstring 補上「已被 D035 取代、
  但仍是父類別（共用邏輯住在這裡，不是死碼）」

同時把 `_queue_ahead_of_live()` 併進 `_log_live_queue_position()`：A3 之後它只剩
一個呼叫端，**留著就是下一個 `last_evaluation`（A1 記過的死碼）**。


### 2026-08-21 補記：D039 自己生出了 D026 的第六次現身（TASKS.md D4）

PR #34 合併後回頭盤查，發現**這個決定的第一版實作把棄權的理由講錯了**。

棄權有三個成因——場上那張單越界、候選價位越界、`queue_clear_usd_per_hour` 設成 0
——而第一版只看候選價位。於是「場上那張單越界」被寫成
「候選價位年化 9.49% 已超出可見簿子（可見最高年化 9.67%）」，
**9.49 小於 9.67，這句話自己就矛盾**；換算速率被關掉時更離譜，
當下沒有任何東西越界，它照樣這樣寫。

而「可見上限落在舊價與新價之間」正是**市場走弱時最常見的形狀**：場上那張是幾天前
的高價、新算出來的比較低，簿子頂端剛好落在中間。**不是角落案例，是每天的路。**

決策從頭到尾都是對的，錯的只有理由——這正是上面「決定三：棄權也要出聲」想避免的事，
只是漏了一層：**出聲了，但講錯是哪裡不知道**。

> **一個判斷式改成「會說不知道」之後，「不知道什麼」就成了新的說謊空間。**
> 下次再寫這類棄權路徑，理由要從一開始就按成因逐一列，不要先挑一個代表。

同批修掉第四個角落：`not book` 原本混在第一道 guard 裡，**簿子抓不到時整條判斷
靜悄悄跳過**。現在的分界是：「沒有場上的單、沒有計畫」代表根本沒有這個問題，
安靜返回是對的；「拿不到簿子」是有問題卻答不出來，那是棄權，要出聲。

修正見 **PR #35**（分支 `fix/abstain-reason-names-the-right-one`，2026-08-21 01:09 部署），
測試 520 → 524 項
（四個新測試裡有兩個是反向斷言：看得到的那個不可以被點名、沒有東西越界時
不可以寫「超出可見簿子」）。**行為零變動——只動理由。**

## D040 — 實際持有時間量測：把「借出去的錢待了多久」算出來，但先不動那個 48

- 日期：2026-08-22
- 分支：`feature/measure-actual-hold-time`
- 狀態：已完成（程式碼、測試、真實資料驗收都做完）
- 相關：**D036（量測優先於策略）**、D038（等待估計，同一種「先量測再改參數」的處理）、
  D039（越界要標示、算不出來要棄權——這一條沿用同一套語氣規則）、
  D026（靜默失效家族）
- 前情：TASKS.md **D1**「期望值公式假設借滿 48 小時，但四筆有三筆提前還款」；
  PLAN.md 2026-08-21 那一節把 D1「可以先做的那一半」標為不必等 M1

### 為什麼是現在做這一項

D1 在 2026-08-20 的成交盤查裡被記下來，當時是 **4 個樣本**。08-21 到 08-22 又多了
兩筆，而新的兩筆把落差推得更明顯——其中一筆**只借了 2.33 小時**（佔預定 48 小時的 5%）。

更重要的是：**這一半的材料早就躺在資料庫裡**。`funding_positions` 從 2026-08-16 起
就存著 `opened_at` 與 `closed_at`，「實際借了多久」是一道減法，只是從來沒有人算過。
TASKS.md 自己也寫了「不需要等 M1」。在 M1（市場資料落地）這個大工程前面，
先把已經有的資料算出來，成本是幾十行。

### 決定一：只量測，不改 `hold_hours`

`strategies/expected_value.py` 的 `hold_hours = self.offer_period * 24.0` 假設每筆都
借滿天期。實測（六筆、其中五筆已結束）：

| 年化 | 實際持有 | 佔預定 48h |
|---|---|---|
| 9.12% | 1.84h | 4% |
| 5.47% | 45.08h | 94% |
| 9.96% | 6.87h | 14% |
| 9.50% | 20.97h | 44% |
| 9.50% | 2.33h | 5% |
| 9.50% | 16.30h（08-22 12:07 時仍在借出中） | 34% |

**平均完成率 32.1%。** 分子被高估時，等待成本在 `r × P ÷ (W + P)` 裡的權重被壓縮，
選出的價位會偏高。

**但這一輪刻意不動那個 48。** 要換成什麼本身就是策略問題（中位數？依利率分層？
期望持有時間？），而那要在 M2 回測工具上跑過才知道。先改參數再建量測，
正是 D036 記下的錯誤。程式碼裡那一行旁邊留了註解說明這件事，並指向
`scripts/hold_report.py`——**現在至少量得到它錯多少**。

### 決定二：仍在借出中的部位是右設限樣本，分開報

與 D038 對等待估計的處理完全一致。丟掉還開著的部位會低估（長命的部位更容易
還開著），把它們當成已結束也會低估（下界不是實際值）。做法：

- 統計量（平均／中位數／四分位／完成率）**只用已結束的部位**
- 還開著的只貢獻 `censored` 計數與 `censored_ratio`，讓人看得出這份摘要蓋掉多少
- 敘述上改口說「**至少** N 小時（仍在生息中）」——同 D039 對排隊位置越界的語氣

### 決定三：三個誠實度來源跟數字並排，不收進腳註

1. **右設限**：如上。
2. **`closed_at` 是我們偵測到的時間，不是交易所實際還款的時間**：巡檢每 10 分鐘一輪，
   所以每一筆持有時間都被**高估** 0～10 分鐘。對中位數 6.9 小時是 2.4%，
   但對只借了 2.33 小時那筆是 7%。
3. **`opened_at` 可能是 None**：`_millis_to_iso()` 轉不動時留空，這時退用
   `first_seen_at`，同樣是高估後的近似值。退用筆數單獨報，不混進去裝作精確。

另外「起算時間壞掉、算出負數」而被排除的列會計入 `unusable` 並印出來。
**靜靜少算幾筆就是 D026 那個家族的病**：不是沒講，是講了一個不完整的樣本卻不說。

### 決定四：「借滿」不做二分類，回報完成率；門檻跟著印出來

45.08 小時對 48 小時的預定到底算不算「借滿」，是門檻的選擇，不是事實。
所以主要輸出是**完成率**，分類門檻（預設 0.9）跟著報告一起印，讓看的人
知道那條線畫在哪裡。

### 決定五：小樣本不報中位數，直接攤開原始值

**這一項是實作到一半才發現的，而它差點讓報告說謊。**

第一版對「越貴借越短」做了利率中位數分組，便宜組只有 1.84h 與 45.08h 兩筆
（差 25 倍）。`statistics.median` 對偶數筆會插值，給出 **23.46h**——一個沒有對應
任何一筆真實借貸的數字。報告據此印出：

```
差距 16.59h，方向**符合**「越貴借越短」。
```

**一個支持假設的結論，建立在一個虛構的數字上。** 改法：少於 3 筆就不報中位數，
直接列出原始值；兩組任一組不足就讓 `gap_hours` 回 `None`，報告說「還比不出來」。
現在的輸出是：

```
便宜組（< 9.50%）：2 筆已結束，持有 1.84h、45.08h
昂貴組（≥ 9.50%）：3 筆已結束，中位數 6.87h、另有 1 筆仍在借出中
**還比不出來**：中位數要兩組各至少 3 筆已結束的部位才算得準，目前是 2 與 3 筆。
```

兩筆原始值並排，一眼就看得出那組根本沒有集中趨勢。這是 PROGRESS.md 2026-08-19
那句「**真正的毛病不在用哪一種平均，而在取平均這個動作本身**」的直接應用。

### 一個藏在回傳值裡的 bug（同批修掉）

`sync_positions()` 回傳的 `closed` 是 **UPDATE 之前**查出來的 dict，`closed_at`
還留著 `None`。不補那一行的話，呼叫端拿到的「剛收回的部位」看起來會跟「還開著」
一模一樣，於是**每一筆還款的當下都會被講成「至少借了 N 小時（仍在生息中）」**
——講的是還款，話卻說成還在生息。

這個 bug 只有在「有東西真的去讀那個回傳值」時才會現形，而在這一輪之前沒有。
已補上並以**對照實驗**驗收：拿掉那一行，兩個新測試立刻變紅
（`assert None == '2026-08-22T14:47:25+08:00'`）。

### 驗收

1. **測試 524 → 575 項**（單元＋功能 549、整合 26），全過。
   其中三個是**反向斷言**：「已結束的部位不可以說『至少』」、「剛收回的部位不可以
   被講成仍在生息中」、「沒有部位收回時不可以憑空多出持有時間那一行」
2. **對照實驗**：移除 `closed_at` 修正後兩個測試變紅，還原後恢復綠燈
3. **真實資料端到端**：拿正式 DB 副本模擬場上那筆 `464242253` 被還款，
   語氣切換正確——
   - 還款前：`已借出 至少 16.30 小時，佔預定 48 小時的 34%（仍在生息中）`
   - 還款後：`實際借出 16.30 小時，佔預定 48 小時的 34%——提前還款`
4. **`scripts/hold_report.py` 以正式 `config.yaml` ＋ 真實 DB 唯讀實跑**，
   六筆數字與手算完全一致

### 這一項不做什麼

- **不改 `hold_hours`**（見決定一）
- **不接 `earnings_daily`**：那是 P2-2，要走 ledger 端點，是另一件事
- **不推 LINE 通知**：持有時間是分析材料不是事件，每月 200 則的額度要留給成交
  （D024 的額度分配）


### 2026-08-24 補記：第一次在正式環境跑起來，數字也動了

`_log_hold_times()` 的關鍵路徑在 **2026-08-23 23:04:42** 第一次被真的走到
——部位 `464242253` 收回，日誌印出：

```
部位 464242253（年化 9.50%）實際借出 48.56 小時，佔預定 48 小時的 101%——借到期
```

**這是這條決策從「測試都過」變成「真的跑過」的那一刻**（連續第三次「部署完成 ≠
新程式碼被執行過」到此結束）。

統計跟著動了，但**結論沒有動**：

| | 2026-08-22（五筆已結束） | 2026-08-24（六筆已結束） |
|---|---|---|
| 中位數持有 | 6.87h | **13.92h** |
| 平均完成率 | **32.1%** | **43.6%** |
| 借到期／提前還款 | 1／4 | 2／4 |

43.6% 仍然遠低於模型假設的 100%，**分子被高估這件事沒有被推翻**，
要不要改那個 48 依舊是 M2 回測工具的題目（決定一不變）。

「越貴借越短」**仍然比不出來**：新增的那筆落在昂貴組，便宜組還是只有 2 筆已結束，
離門檻（各 3 筆）沒有變近。

## D041 — 跨輪殘留的狀態被當成本輪的事實報出去：兩個成員，同一個病

- 日期：2026-08-23
- 分支：`fix/stale-cross-round-state`（**PR #37，08-23 12:19:26 合併進 main `d81121a`、
  12:20:44 部署**）
- 狀態：已完成並上線（程式碼、測試、對照實驗、真實市場資料驗收都做完）。
  **正式環境的驗收仍待觸發條件**——見文末補記
- 相關：**D026（靜默失效家族）**、D039／D4（越界要標示、理由要指對對象）、
  D027（測試替身比真實世界乾淨）、D036（量測基礎）、D024（LINE 額度）
- 前情：TASKS.md **D2**「LINE 通知把重掛講成『啟動後首輪掛單已送出』」；
  另一個成員是本次規劃下一步時查證日誌才發現的，先前沒有任何文件記過

### 病灶

兩個欄位都是「**本輪**的狀態」，卻都活得比一輪長，於是下一輪把它們當成自己的事實
報出去。這不是兩個 bug，是同一個形狀出現兩次：

| 欄位 | 位置 | 誰在報它 | 報錯成什麼 |
|---|---|---|---|
| `last_evaluation` | `strategies/expected_value.py` | `describe_decision()` 寫日誌 | 上一輪的定價決策 |
| `_offers_live` | `core/bot_engine.py` | `_note_offers_*()` 推 LINE | 「啟動後首輪」／「掛單已不在場上」 |

> **它們都不是「忘了講」，而是「講了一件沒發生的事」。**
> D026 家族至今的每一次現身都是這個形狀，這是第七、第八次。

### 成員一：定價決策跨輪重播

`build_offer_plan()` 有六個出口會在 `choose_rate()` 之前就 return，而評估結果
**只在 `choose_rate()` 內重置**。資金一借出、餘額掉到 150 USD 門檻以下，
那個清單就再也沒人清過。

現場代價（正式機日誌）：**2026-08-21 22:34 → 08-22 19:22，連續 21 小時、87 輪以上**
印出位元組完全相同的一行，而同一輪的鄰行自相矛盾：

```
2026-08-21 22:34:02 INFO 期望值定價：113 個候選價位，選中年化 9.50%（…命中 47 次…）
2026-08-21 22:34:02 INFO 本輪略過：本輪不掛單：可用餘額 0.01 USD 低於下限 150.00 USD
```

那份評估真正算出來的時刻是 **08-21 22:23**，也就是成交前的最後一輪。

**反證來自 08-22 19:22 的容器重啟**：新行程的清單是空的，於是那行整個消失
——16 小時、96 輪一次都沒印。**同樣的市場、同樣的餘額，只差在行程是新的**，
這證明先前那些全部是舊資料，不是每輪重算後碰巧相同。

修正：重置點移到 `build_offer_plan()` 開頭，與 `last_skip_reason` 並排。
**刻意不在那六個出口各補一次**——那正是這個 bug 當初的成因，漏掉任何一條就再犯，
而漏掉的那條不會有人發現。「新的一輪開始了」只有一個位置。

### 成員二：場上狀態只跟著「我們做了什麼」走

`_offers_live` 原本只有兩條路會更新：掛單成功、掛單消失。而**新策略下最常走的是
第三條——什麼都不做**（2026-08-21 那 36 小時裡，123 輪選中的價位一次都沒變過）。
那條路提早 return，場上狀態沒人登記。

`existing` 每輪都從交易所抓回來，**真相一直在手上，只是沒有人去用它**。

漏掉的出口有五個，兩個後果：

1. **D2**：啟動後第一次**重掛**被講成「啟動後首輪掛單已送出」，而容器已經跑了
   15 小時（2026-08-20 15:15 實錄）。半夜看到會誤以為機器人重啟過。
2. **本次新發現**：FRR 讀不到時無條件推「掛單已不在場上」——但真實流程裡
   取消發生在 FRR 檢查**之後**，那一刻單還好端端掛在場上。
   **這則比 D2 嚴重**：D2 是把真事講錯，這是把假事講成真的。

修正：新增 `_note_offers_unchanged(existing)`，在五個「什麼都沒動」的出口照實登記，
**不推播**——什麼都沒發生，推了就是製造雜訊。FRR 那個出口改成先看一眼場上再決定
要不要說「單不見了」。

### 一個意外的結果：D2 那則訊息不是換句話說，是根本不該送

原以為要把「啟動後首輪」改成「掛單已重新上線」。實際跑過才發現：通知推的是
**狀態轉換**（D029），而場上本來有我們的單、重掛之後還是有我們的單
——**沒有轉換，所以不該送**。修正後那一輪安靜通過。

訊息是假的，額度是真的，而每月只有 200 則（D024）。

### 為什麼排在 M1 前面

M1（市場資料落地）要把每輪的市場狀態寫進 DB，而它想回答 **D3**
（「目標為什麼因為一根 K 滾出窗而跳一階」）就**必須把本輪選中的價位與候選集
一起存**——那正是 `last_evaluation`。

> 日誌印錯，旁邊還有一行「餘額不足」可以拆穿它；
> **DB 裡多一列假資料沒有鄰行會反駁**，而 M2 回測工具會拿它當事實。

這是 D036 那個病最貴的變體：不是決策互相推翻，是**用來評斷決策的材料本身是假的**。

### 為什麼 575 項測試一項都沒抓到

兩個成員各有一半的原因，而兩個都是 **D027**（測試替身比真實世界乾淨）：

- `test_沒評估過就不硬掰` 從一個**全新的策略物件**出發，而全新物件的清單本來就是空的。
  真實運作裡策略物件活得跟行程一樣久，**bug 只在第二次呼叫才現形**。
- `FakeClient.create_loan_offer()` 不會把掛出去的單放回 `active_offers`，
  所以替身世界裡「掛單之後場上有單」從來不成立——五個漏掉的出口一個都走不到。
  既有的 `test_invalid_frr_also_counts_as_offers_gone` 因此**假性通過**，
  它的 docstring 還寫著「單已經在流程開頭被取消了」，而那句話在真實流程裡是錯的。

新測試一律**跑兩輪**，並手動把單放回場上。

### 驗收

1. **測試 575 → 587 項**（單元＋功能 561、整合 26），全過
2. **對照實驗兩次**：分別移除兩處修正，11 項變紅、還原後全綠；
   每組各留一項**對照組**（FRR 且場上真的沒單時仍要說、下一輪重新評估後又講得出話來）
   確認**不是把功能整個關掉**
3. **反向斷言**：「不可以印出上一輪那一行的內容」——只斷言 `is None` 的話，
   把方法改成永遠回傳 `None` 也會過，那是把「偷偷講錯」換成「偷偷不講」
4. **真實市場資料端到端**：以正式 `config.yaml` 抓當下的簿子 250 檔、成交 10,000 筆、
   K 線 240 根，重演「第一輪 344.41 USD 評估 → 第二輪 0.01 USD」，
   第二輪的 `describe_decision()` 與 `chosen_forecast()` 都回 `None`

### 這一項不做什麼

- **不改 `FakeClient` 讓掛單自動進場**：那會牽動既有的取消／累積測試，
  對一台真金運作中的機器人風險不成比例。新測試各自把場上狀態擺明白
- **不新增通知類型**：這一輪的職責是讓狀態停止說謊，不是決定要多說什麼
- **不動 `hold_hours` 那個 48**：仍然等 M2（D040 決定一）


### 2026-08-23 補記：上線了，但「驗收過」還沒發生（連續第四次）

PR #37 於 12:19:26 合併、12:20:44 容器重啟，`healthy`、`NRestarts=0`、
14 輪 0 ERROR 0 WARNING。**但兩個成員的修正路徑一條都沒被走到。**

部署後 14 輪全部走「可用餘額 0.17 USD 低於下限 150.00 USD」那個出口，
`choose_rate()` 一次都沒跑到（日誌裡「期望值定價」出現 **0 次**）。所以：

- `last_evaluation` 的重置**從來沒有東西可以重置**
- 場上沒有我們的單，`_note_offers_unchanged()` 的五個出口一個都沒走到

**而這一條決策自己就寫過為什麼這證明不了任何事。** 上面「成員一」那一節的反證是
「08-22 19:22 容器重啟後那行整個消失，因為新行程的清單是空的」——
換句話說，**「那一行沒印出來」在修正前後長得一模一樣**。

> 修好一個「跨輪殘留」的 bug 之後，**第一輪永遠驗收不了它**——
> 因為 bug 的定義就是「第二輪才現形」。

**第一次真正的驗收條件**（寫死在這裡，免得下次又用「部署成功」代替）：
資金回來 → 策略真的評估過一輪（日誌出現「期望值定價」）→ 下一輪又掉回門檻以下，
而那一輪**不再重播**上一輪的定價決策。場上狀態那一半則要等掛單掛上去、
下一輪走「維持不動」。

### 一條該推廣的做法

D040（第三次）、D039／D4（第一、二次）、D041（第四次）都撞上同一件事：
**「測試全過 ＋ 部署成功 ＋ 0 ERROR」三個綠燈同時亮著，仍然可以代表新程式碼一行
都沒跑過。** 前三次還能算巧合，第四次應該當成常態來安排：

**往後每一條修正分支，在合併時就要寫下「什麼事件發生才算被執行到」**，
而不是等部署完再回頭想。這一節就是第一個示範。


### 2026-08-24 補記：驗收通過，而且拿到的證據比要求的強

**上一節寫死的驗收條件，在 2026-08-23 深夜完整走完了**：

| 時間 | 事件 | 對應驗收條件 |
|---|---|---|
| 23:04:42 | 部位 `464242253` 收回，資金回到融資錢包 | 「資金回來」 |
| 23:04:45 | 日誌出現 `期望值定價：109 個候選價位，選中年化 9.11%` | 「策略真的評估過一輪」 |
| 23:04:47〜23:45 | 掛單掛上去，其後 4 輪走「維持不動以保住排隊位置」 | **場上狀態那一半也驗收到了** |
| 23:50:49 | 成交，可用餘額掉回 0.08 USD | 「下一輪又掉回門檻以下」 |
| 08-24 全天 **130 輪** | 每一輪只有「本輪略過」，**`期望值定價` 出現 0 次** | 「不再重播上一輪的定價決策」 |

要求的是「**下一輪**不重播」，實際拿到的是「**連續 130 輪**不重播」。

**關鍵在於這次跟 08-23 補記的那次長得不一樣。** 上一節寫過反證：
「那一行沒印出來」在修正前後長得一模一樣，因為新行程的清單本來就是空的。
這次不同——**`last_evaluation` 先被填滿過（23:04 那輪確實評估並印了），
然後才掉回門檻以下**。清單有東西可以殘留而沒有殘留，這才是驗收。

> **「還沒有機會犯錯」與「有機會犯錯而沒有犯」，中間隔的正好是一次驗收。**

「一條該推廣的做法」那一節的示範到此走完一輪：合併時寫下「什麼事件發生才算被執行到」
→ 事件發生 → 回頭對照。**D042（M1-a）也在 08-23 用同一套做法當天就兌現。**

---


## D042 — 市場資料落地拆成兩張表，而且這一批只存觀測、不存決策

- 日期：2026-08-23
- 分支：`feature/market-snapshot-landing`（M1-a）
- 狀態：🟢 已實作。**M1-b（決策落地）刻意留在後面**，見下方第三節
- 相關：**D036（量測基礎，這一期存在的理由）**、D041（跨輪殘留的狀態）、
  D039（越界的數字要標示）、D038（落地點要在提早 return 之前）、
  D035（K 線的 `high` 才是自變數）、D027（測試替身比真實世界乾淨）
- 前情：TASKS.md 第 1 期 **M1「市場資料落地」**

### 一、問題

DB 有掛單、部位、收益、狀態、等待預估五張表，**沒有任何一張存過市場長什麼樣**。
每次分析都得重抓即時資料，用完就丟，而歷史再也回不去。

具體代價已經有名字了：**D3**——2026-08-20 10:12 候選價位數 111 → 110、
選中的目標同時 9.78% → 9.50%，而當時的市場常態價與一小時前相同。
當天整條事件鏈（改價 → 守門檻 → 重掛 → 成交）的起點就是這個，
**而我們無法直接證實**，因為是哪一根 K 滾出去、當時簿子長什麼樣，都沒有存下來。

### 二、決策：拆兩張表，不是一張

TASKS.md 原文寫的是「新增一張表，每輪把簿子摘要、成交摘要、K 線指標寫進 DB」。
實作時改成兩張：

| 表 | 粒度 | 一天長多少 |
|---|---|---|
| `market_snapshots` | **每輪一列** | 144 列（巡檢 600 秒） |
| `market_candles` | **一根 K 一列**，`(currency, period, timeframe, mts)` 為主鍵 | 24 列 |

**理由是重複度**：K 線每小時才換一根，而巡檢 600 秒一輪。照「每輪存一份窗」的作法，
同一根 K 一天會被寫進去 6 次、240 根的窗一天就是 **34,560 列在講 24 根 K 的事**。

**寫入用 UPSERT 而不是 INSERT OR IGNORE，而且邊界含等號**：已存的最新那一根
當時可能還在成形中，它的 `high` / `close` / `volume` 之後還會變大。
少了等號，每根 K 都會被凍結在剛出生那一刻的樣子——**而 `high` 正是這個策略
唯一在意的欄位**（D035：某根 K 的 `high` ≥ 掛單利率就等於那段時間我們會被掃到）。

實測驗證：同一份 240 根的 K 線，第一次寫 240 根，第二次只寫 1 根。

**附帶好處**：時間一久，這張表存的 K 線歷史會長得比 API 一次取得到的還長
（`/v2/candles` 一次上限 5000 根），而那正是 M2 回測工具需要的東西。

### 三、決策：這一批只存觀測，不存決策

TASKS.md 對 M1 寫了一個警告：

> ⚠ 存之前先確認 D041 的修正已在正式環境驗收過——日誌印錯還有鄰行可以拆穿，
> **DB 裡多一列假資料沒有鄰行會反駁**，而 M2 回測工具會拿它當事實。

**這個警告只管得到「本輪選中的價位與候選集」**（`last_evaluation`，正是 D041 那個
跨輪殘留的欄位），**管不到簿子／成交／K 線**——後者是當輪現抓的外部觀測值，
沒有跨輪殘留的可能。把兩者綁在同一批，等於讓沒有風險的那一半陪著另一半空等。

所以 M1 拆成兩批，而**界線寫進程式而不是只寫在文件裡**：
`core/market_snapshot.py` 的模組說明第一句就是「這個模組刻意不認識任何策略物件」。

> **界線要看得見，否則下次順手就越過去了。**

M1-b（決策落地）的放行條件寫在 STATUS.md：資金回來 → 策略真的評估過一輪 →
下一輪又掉回門檻以下，**而那一輪不再重播上一輪的定價決策**。

### 四、落地點放在所有提早離開的出口之前

寫入放在三個 `_fetch_*` 之後、`raise SkipCycleError` 之前。底下有五條路徑會提早離開
（策略無計畫、維持場上既有掛單、重掛不划算……），而那些正好是
**「市場走弱、單子空掛」的輪次——也就是最需要留下市場長相的輪次**。

這是 D038 那一課的重演：閒置量測原本擺在提早 return 之後，於是永遠量不到
閒置最久的那些輪。**差別在於日誌漏印還看得出來，DB 漏一列事後完全無感。**

一個例外刻意保留：**FRR 無效那一輪不寫列**。它在抓市場資料之前就離開，
確實什麼都沒觀測到——**寫一列空的比不寫更糟**，那會讓「這段期間有幾筆觀測」
這個數字說謊。

### 五、摘要是有損的，所以每個有損的地方都要有欄位承認

這是 D039「越界的數字要標示」從日誌延伸到資料表：

| 欄位 | 承認什麼 | 為什麼非有不可 |
|---|---|---|
| `book_truncated` | 可見範圍之上一無所知 | 沒有它，M2 會把截斷值當真實深度讀，於是「前面排了多少錢」在每個高價位都給同一個答案，而看起來一切正常（A2／A3 的根因） |
| `trade_span_minutes` | 這批成交涵蓋多久 | D035 的第一個錯誤結論敗在樣本窗只有 4 小時，而當時沒有欄位記下這件事 |
| NULL 而不是 0 | 「沒觀測到」≠「觀測到 0」 | 用 0 填會讓一段沒有資料的期間被讀成一段市場死掉的期間 |

**天期一律分開存**（`book_period_totals_json`、`trade_period_rates_json`）：
天期溢價非常大（2026-08-16 實測同一小時內 2 天期 0.000261、30 天期 0.000319），
混在一起算出來的數字不對應任何一個市場。實測 2026-08-23 這一輪，
2 天期加權中位數是年化 5.48%，而全天期混算是 6.57%——**差 1.1 個百分點**。

### 六、成本是量出來的

拿真實回應實測（2026-08-23）：一列約 **1.2 KB**，一天約 190 KB、一年約 68 MB。
TASKS.md 原本寫「每輪幾百位元組」，那是還沒把簿子的累積曲線算進去時的估計。
**兩處程式註解都改成實測值**——一個估計數字留在註解裡，下一個人會拿它當事實。

簿子存的是 **20 點的累積曲線**（每 5% 一個點），不是 250 檔原始資料：
原始資料一輪就是 10 KB 量級，一年 500 MB。曲線反過來讀就是
「掛在這個利率，前面大約排了多少錢」，而那正是 M2 要問的問題。
**解析度就是那 20 個點，這件事寫在模組說明裡。**

### 七、驗證方式（D027）

除了 31 項新測試，另外拿**真實公開 API 回應**跑過一次完整落地——
`get_funding_book` / `get_recent_trades` / `get_rate_candles` 三個端點的真實回傳
直接餵進摘要函式與 Repository。這是 D027 的規矩：測試替身的型別與格式是手寫的，
**比真實世界乾淨**，而 D041 的兩個 bug 都栽在這裡。

實測當下的形狀本身就是證據：**250 檔可見最高只有年化 8.00%**，
`truncated` 正確標成 True——A2／A3 那個場景此刻正在發生。

---

## D043 — 決策落地：把「這個價位是怎麼選出來的」寫進 DB，而且寫在日誌那一行的旁邊

- 日期：2026-08-24
- 分支：`feature/persist-pricing-decision`（M1-b）
- 狀態：**已合併並部署**（PR #43，2026-08-24 22:47 合併進 main `59c087f`、
  **22:48:28 容器重啟**，`healthy`、0 ERROR 0 WARNING、新表與索引自動建好）。
  **正式環境的驗收待觸發條件**——見文末
- 相關：**D042（M1-a：只存觀測、不存決策）**、**D041（跨輪殘留，本項的放行條件）**、
  D038（不存就永遠消失的那一半）、D040（那個已知錯的 48）、D036（量測優先於策略）、
  D039（有損的地方要自己講出來）
- 前情：TASKS.md **M1-b**「本輪選中的價位與候選集，沒有它就答不出 D3」；
  D042 在表註解裡寫死「本輪選中的價位與候選集屬於 M1-b，等 D041 在正式環境驗收過再進來」

### 放行條件已達成

D041 於 **2026-08-23 23:04** 在正式環境驗收通過（連續 130 輪不重播定價決策，
證據見 PROGRESS.md 的 2026-08-24）。當初擋著這一項的那句話是：

> 日誌印錯還有鄰行可以拆穿，**DB 裡多一列假資料沒有鄰行會反駁**，
> 而 M2 回測工具會拿它當事實。

驗收通過解除了放行條件，**但沒有解除那句話本身**——所以這一項的每一個設計決定
都是繞著它轉的。

### 決定一：分成新表，不是往 `market_snapshots` 加欄位

兩者的寫入時機不同，而且**不是每輪都成對**：

| | `market_snapshots` | `pricing_decisions` |
|---|---|---|
| 寫在哪 | 三個 `_fetch_*` 之後、**所有提早離開的出口之前** | `build_offer_plan()` **之後** |
| 什麼輪次會寫 | 只要抓得到市場資料 | **只有策略真的評估過的輪次** |
| 2026-08-24 那天 | 130 列 | **0 列** |

那一天資金全部借出，餘額守門檻讓 `choose_rate()` 一次都沒跑到。併成一張表的話，
那 130 列就得為決策留一整排 NULL——**而 NULL 太多的表沒有人讀得懂**。
更糟的是「這段期間評估過幾次」這個數字會從 0 變成 130。

順帶：快照寫在提早離開的出口**之前**是 D042 刻意的（那些輪次最需要留下市場長相），
而決策必須在**之後**——這兩件事本來就不可能塞進同一次 INSERT。
`record_market_snapshot()` 因此改為回傳新列的 id，讓決策指得回去。
**不能用時間去 JOIN**：同一秒可能有兩列，而決策比快照晚幾百毫秒才產生。

### 決定二：寫入點緊貼著 `_log_pricing_rationale()`

```python
plans = self.strategy.build_offer_plan(...)
self._log_pricing_rationale()      # 給人看
self._record_pricing_decision(...)  # 給 M2 看
```

**兩者讀同一份 `last_evaluation`，於是日誌那一行就是 DB 那一列的鄰行。**
D041 擔心的「DB 裡沒有鄰行會反駁」，用這個位置接了回來——不是靠承諾，
是靠位置。功能測試 `test_決策與日誌那一行講的是同一個價位` 把它釘住。

**第二次 `build_offer_plan()`（取消舊單後用真實餘額重算）不再落一列**：
`choose_rate()` 只吃 K 線、不看餘額，同一輪的兩次評估必然選出同一個價位，
多存一列只會讓「這段期間評估過幾次」說謊。

### 決定三：沒評估過的輪次，一列都不寫

`pricing_decision()` 回傳 `None` 就什麼都不做。**不寫一列空的**——
理由與決定一同源，而這一條在 repository 與 bot_engine 兩層各擋一次
（`if not decision: return None`）。

**這是 D041 的保護延伸到新出口**：策略物件活得跟行程一樣久，
`last_evaluation` 只要沒在 `build_offer_plan()` 開頭重置，
上一輪的決策就會被寫成這一輪的一列——而那一列不會有鄰行反駁它。
`last_window`（M1-b 新加的第三個「本輪狀態」）因此也放在同一個重置點，
並有測試釘住：**每多一個都得在同一個地方重置，漏掉的那一個不會有人發現。**

### 決定四：候選集只存價位與實質年化兩排

**成本是量出來的**（拿正式 DB 的 K 線跑出 109～110 個候選）：

| 存法 | 大小 |
|---|---|
| 每個候選的完整評估（rate／wait／median／p75／hits／censored／effective） | **17 KB** |
| 陣列的陣列（同樣七個欄位，去掉鍵名） | 5.3 KB |
| **只留價位與實質年化兩排** | **2.6 KB** |

留下 `effective` 是因為**它就是排序依據**——有了它才答得出「為什麼是這個價位」，
而那正是 D3 的問題（候選價位數 111 → 110，選中的目標同時 9.78% → 9.50%）。
選中的那一個候選的完整評估另有 `chosen_*` 欄位，其餘候選的等待分佈是中間量。

⚠ **有損的地方要自己講出來**（D039）：其餘候選的等待分佈**沒有存**。
`market_candles` 存著同一批 K 線，理論上重算得出來——**但重算不保證重現**：
最新那一根 K 還在成形，事後 UPSERT 過的 `high` 已經不是當時看到的值。
所以重算出來的東西**是另一個問題的答案**，不可以拿來冒充當時的決策。

### 決定五：`hold_hours_assumed` 存的是假設，不是事實

那個 48 已知與現實不符（D040 實測完成率 43.6%）。存它不是因為它對，
而是因為 **M2 要拿它當「當時假設了什麼」**——換掉那個數字之後，
舊決策才有辦法跟新決策比較。**先改參數再建量測正是 D036 記下的錯誤**，
所以這一項照樣不動它。

### 成本

**實測**（寫 200 列再 VACUUM，量檔案增長）：**一列 4,137 位元組**，含索引。

- 目前資金使用率約四分之三 → 每天約 35 輪會評估 → **一年約 50 MB**
- **最壞情況（每輪都評估）一年 207 MB** ——比 `market_snapshots` 的 68 MB/年 大三倍

最壞情況要寫出來，因為那是「市場一直很好、錢一直掛不出去」的日子，
**正好也是最想回頭看的日子**。

### 驗收

1. **測試 618 → 650 項**（單元＋功能 624、整合 26），全過。新增 32：
   策略層 14、資料層 10、功能層 8
2. **對照實驗兩組**：
   - 拿掉 `last_window` 的跨輪重置 → `test_窗的座標也不可以跨輪殘留` 立刻變紅
   - 讓沒評估過的輪次也寫一列 → 三個反向斷言同時變紅
     （`test_餘額不足的一輪有市場沒有決策`、`test_連續多輪沒錢也不會累積出決策`、
     `test_評估過之後又沒錢的那一輪不留下第二列`）
3. **正式 DB 副本端到端**：`CREATE TABLE IF NOT EXISTS` 在開啟時自動建好新表
   （**不需要遷移腳本**，與 D042、D038 走同一條路）；拿真實的 268 根 K 線跑出
   109 個候選，寫入後讀回來——兩排等長、實質年化最高的那個價位等於 `chosen_rate`、
   `snapshot_id` 指得回同一輪的快照

### 什麼事件發生才算「被執行到」

**這一節是照 D041 的「一條該推廣的做法」寫的**：合併時就寫下驗收條件，
而不是等部署完再回頭想。前四次的教訓是「測試全過 ＋ 部署成功 ＋ 0 ERROR」
三個綠燈同時亮著，仍然可以代表新程式碼一行都沒跑過。

**這一項部署後不會立刻被執行到**：部位 `464372858` 要到 **2026-08-25 23:50** 才到期，
在那之前每一輪都走餘額守門檻，`pricing_decisions` 會**正確地**保持 0 列。
**0 列在那段期間是通過，不是失敗**——這一點要先寫下來，免得屆時把它當成 bug 去查。

驗收條件（部位收回後的那一輪）：

1. `pricing_decisions` 出現**第一列**
2. 那一列的 `snapshot_id` 指得回同一輪的 `market_snapshots`（不是 NULL、不是別輪的）
3. 那一列的 `chosen_rate` 換算年化，等於同一輪日誌「期望值定價」那一行講的價位
4. `candidate_rates_json` 讀得回一個排序好的陣列，長度等於 `candidate_count`
5. **資金再度借出、餘額掉回門檻以下之後，不再多出任何一列**
   ——這是 D041 的保護在 DB 這一側的樣子

查法：
```sql
SELECT id, decided_at, snapshot_id, chosen_rate * 365 * 100 AS chosen_annual,
       candidate_count, window_hours
FROM pricing_decisions ORDER BY id;
```

### 這一項不做什麼

- **不改 `hold_hours`**（決定五）
- **不動 `ev_window_hours`**：2026-08-24 算出「9.11% 的命中率全期 38.8%、
  最近 72 小時只剩 9.7%」，那是 M2 回測工具的題目，不是現在拍板的理由
- **不做 M2**：這張表是 M2 的輸入，不是 M2
- **不推 LINE 通知**：決策是分析材料不是事件（同 D040 的額度判斷）

