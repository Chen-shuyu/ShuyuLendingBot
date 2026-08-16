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
