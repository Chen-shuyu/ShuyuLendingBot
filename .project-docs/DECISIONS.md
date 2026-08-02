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
