# ShuyuLendingBot 專案架構與開發規劃書

> 本文件為 ShuyuLendingBot（Bitfinex 美元放貸機器人）的最高開發指導原則，統整策略藍圖、系統架構、Python 實作最佳實踐、資料記錄、Red Hat 部署維運與後續開發步驟。
>
> 定位：將現有「單次 dry-run 雛型」升級為「模組解耦、可 24 小時常駐、可觀測」的正式放貸機器人。核心是把 MikaLendingBot 的策略精華（FRR 底線、spread 分批、xDays 動態天期、maxtolend 風控）以 Python 3 + `ccxt` 重寫成純函式策略層，補上主迴圈狀態機、Rate Limit 重試、SQLite 收益記錄。
>
> 已定案決策（2026-07-14）：
> 1. 通知管道：LINE Messaging API push（取代已停用的 LINE Notify）。
> 2. 交付形式：本規劃文件（不含程式碼實作）。
> 3. 主迴圈：程式內 `while True` + `time.sleep` + systemd 崩潰重啟。

---

## 現況盤點（開發前必讀）

在動工前，先釐清目前雛型與目標之間的落差。以下三項為**致命問題**，必須優先修正：

- **主迴圈缺失**：`main.py` 目前是「單次 dry-run」，執行一次即結束，尚無 PRD 所述的 10 分鐘循環巡檢。
- **通知管道已失效**：`modules/line_notifier.py` 仍呼叫 `notify-api.line.me`，但 **LINE Notify 已於 2025 年 3 月底停止服務**，此路徑實際上永遠失敗。
- **FRR 抓取錯誤**：`modules/exchange_client.py` 的 `get_frr()` 使用 `fetch_funding_rate`，那是「永續合約資金費率」，並非放貸市場的 FRR（閃電返還率），會取得錯誤數據。

其他待補項目：

- 尚無 `strategies/`、`api/`、`db/` 分層資料夾。
- 無放貸歷史與利息收益的資料記錄機制。
- 無 API Rate Limit 重試與退避機制。
- `utils/logger.py` 使用 `FileHandler`，24 小時常駐會導致日誌檔無限增大。
- `cancel_active_offers()` 目前僅回傳未成交訂單，並未真正取消。

已就緒的部分：

- `.gitattributes` 已正確設定 `* text=auto eol=lf`，Linux 執行腳本不會因 CRLF 出錯。
- `systemd/bfx-lending-bot.service` 已存在（需調整為配合程式內部迴圈）。
- `config/settings.py` 已支援 YAML + 環境變數 + secrets 檔載入。

---

## 1. 專案目標與策略藍圖

### 1.1 演進方向

- 從「一次性腳本」演進為「常駐服務」。
- 策略邏輯提煉自 MikaLendingBot，但去除其全域狀態耦合與 Python 2 語法糟粕，改以 Python 3 純函式重寫。
- 底層通訊由舊版 Bitfinex V1 API 改為 `ccxt` 封裝的 V2 API，降低被交易所淘汰的風險。

### 1.2 從 MikaLendingBot 提煉的策略精華

對應 `PROJECT_ANALYSIS_FOR_NEW_BOT.md` §4.3 借貸核心：

- **動態利率底線**：`目標利率 = max(FRR + premium, minimum_rate)`。以市場 FRR 為浮動底線，額外加上微幅溢價，確保收益高於市場均價。對應舊專案 `Lending.py` 的 FRR 覆寫邏輯。
- **資金分配（雙發彈夾）**：
  - 餘額 ≥ 300 美元 → 平分兩筆掛出（錯開還款時間、保留搶高利彈性）。
  - 150 ≤ 餘額 < 300 → 不拆單，單筆全下。
  - 餘額 < 150 → 低於 Bitfinex 最低放貸門檻，記錄日誌後休眠。
  - 對應舊專案 `spreadlend` 分批概念的簡化版。
- **xDays 動態天期**：
  - 平時掛最短 **2 天**，維持資金靈活性。
  - 一旦年化利率突破 **30%（日利率 0.00082）** 暴利閾值，直接掛 **30 天**鎖住高利。
  - 對應舊專案 `xdaythreshold`。
- **風控上限（建議預留）**：`maxtolend` / `maxpercenttolend`，限制單幣種曝險。對應舊 `MaxToLend.py`。現階段僅放 USD，仍建議保留介面以利未來擴充。

### 1.3 現雛型策略骨架

`modules/lending_strategy.py` 的 `build_offer_plan()` 已實作「門檻判斷 + 拆單 + 天期判斷」，方向正確。後續需補：

- 「只補掛差額」（避免重複掛出已成交部分）。
- 多筆階梯利率（spread）。
- 風控上限檢查。

---

## 2. 系統架構與模組規劃

建議從現有 `config/ modules/ utils/` 演進為分層解耦結構：

```
ShuyuLendingBot/
├── config/            # 設定載入與驗證
│   ├── settings.py            # 現有，補型別驗證（dataclass / pydantic）
│   └── config.yaml
├── api/               # 交易所適配層（Exchange Adapter）
│   ├── base.py                # 抽象介面（對應舊 ExchangeApi.py 契約）
│   ├── bitfinex_client.py     # 由現 exchange_client.py 移入，修正 FRR
│   └── rate_limiter.py        # Rate Limit + 指數退避重試
├── strategies/        # 策略層（純函式，易測試）
│   ├── base.py                # Strategy 抽象基底
│   └── frr_plus.py            # FRR+ 雙發彈夾策略（由 lending_strategy.py 移入）
├── core/              # 編排層（Orchestration）
│   └── bot_engine.py          # 主迴圈狀態機（對應舊 BotWorker.py）
├── db/                # 資料層
│   ├── models.py              # 資料表定義
│   └── repository.py          # SQLite 讀寫封裝（WAL 模式）
├── notify/            # 通知層
│   └── line_messaging.py      # LINE Messaging API（取代已停用的 LINE Notify）
├── utils/
│   └── logger.py              # 現有，改用 RotatingFileHandler
├── tests/                     # 單元 / 整合測試
├── systemd/                   # 部署設定
├── main.py                    # 精簡為 bootstrap，主迴圈移入 core/
└── .gitattributes             # 已正確設定 eol=lf
```

### 2.1 分層職責

對應 `PROJECT_ANALYSIS_FOR_NEW_BOT.md` §9.1 建議分層：

| 層級 | 資料夾 | 職責 | 對應舊專案 |
| --- | --- | --- | --- |
| Exchange Adapter | `api/` | 統一交易所 API 形狀、Rate Limit | `ExchangeApi` + `ExchangeApiFactory` |
| Strategy | `strategies/` | 計算掛單利率、金額、天期（純函式） | `Lending` + `MaxToLend` |
| Orchestration | `core/` | 主迴圈、重試、錯誤隔離 | `BotWorker` |
| Observability | `utils/` + `notify/` | 結構化日誌、通知、狀態 | `Logger` + `Notify` |
| Persistence | `db/` | 掛單與收益記錄 | `AccountStats`（改良併發） |

### 2.2 刻意排除的部分

為降低複雜度並符合單帳戶單幣種現況，本專案**不採用**舊專案的：

- Plugin 生態（`PluginsManager`、`Plugin` hooks）。
- 多 Worker / `Manager` 多執行緒架構。
- Web 前端頁面（先以 CLI / 日誌觀測，未來再加）。

---

## 3. Python 程式碼優化與實作建議

### 3.1 例外處理分層

對應舊專案 §12「錯誤五分類」，簡化為三類自訂例外：

- `RetryableError`：可重試（HTTP 429、timeout、5xx）。
- `FatalError`：不可重試（API key 無效、權限不足）。
- `SkipCycleError`：本輪略過（餘額不足）。

主迴圈 `try/except` 只捕捉 `RetryableError` 並續跑；遇 `FatalError` 發送通知後退出，交由 systemd 判斷是否重啟。

### 3.2 API Rate Limit 重試機制

於 `api/rate_limiter.py` 以 decorator 包裝所有交易所 API 呼叫：

- 指數退避：第 n 次重試等待 `2^n` 秒（設上限，例如 60 秒）。
- 最多重試 5 次，超過則拋出 `RetryableError` 交主迴圈處理。
- `ccxt` 已提供 `enableRateLimit=True`，但仍需自行捕捉 `ccxt.RateLimitExceeded` 與 `ccxt.NetworkError`。

### 3.3 修正 FRR 抓取（重要）

`modules/exchange_client.py` 的 `get_frr()` 現用 `fetch_funding_rate`（永續合約資金費率），應改為 Bitfinex V2 放貸 FRR：

- 呼叫 `GET /v2/ticker/fUSD`，回傳陣列的 index 0 即為 FRR（日利率）。
- 或透過 `ccxt` 對應方法取得 funding ticker 後解析 FRR 欄位。

### 3.4 非同步與執行緒設計

- 現階段為單帳戶單幣種，**建議先採單執行緒 + `time.sleep` 主迴圈**，簡單且可靠，不需引入 `asyncio`。
- 僅在未來需要「主迴圈」與「HTTP 狀態端點 / 通知」並行時，才使用 `threading.Thread(daemon=True)`。
- 避免舊專案的全域狀態耦合，改用「注入式物件」（將 config、logger、client 以參數傳入）。

### 3.5 dry-run 與冪等性

- 保留現有 `dry_run` 旗標，方便部署前驗證流程。
- 策略層維持**純函式**（輸入餘額 + FRR，輸出 `OfferPlan` 清單），所有副作用集中於 `api/` 與 `core/`，以利單元測試。

---

## 4. 資料記錄與狀態管理

### 4.1 SQLite（WAL 模式）避免寫入衝突

- `db/repository.py` 開啟連線後執行 `PRAGMA journal_mode=WAL;`，讓讀寫並行不互鎖。
- 採「單一寫入者（主迴圈）+ 多唯讀查詢（未來報表 / 狀態頁）」模型，天然避免寫入衝突。
- 對應舊 `AccountStats.py` 的 sqlite3 使用，但改良併發行為。

### 4.2 建議資料表

- `loan_offers`：掛單流水。
  - 欄位：`id`、`currency`、`amount`、`rate`、`duration`、`status`、`created_at`。
- `earnings_daily`：每日收益彙總。
  - 欄位：`date`、`currency`、`interest`、`principal_avg`。
  - 對應舊專案 today / yesterday / total earnings。
- `bot_state`：單列狀態表，供崩潰後恢復與狀態頁讀取。
  - 欄位：`last_run_at`、`last_frr`、`last_action`。

### 4.3 資料一致性

- 每輪「取消舊 offer → 查餘額 → 掛新單 → 寫入 DB」以**單一 transaction 收尾**：掛單 API 成功才 `commit`，失敗則 `rollback`。
- 避免舊專案直接寫 JSON 檔（易發生半寫損毀）；狀態一律寫入 DB，需輸出 JSON 時再由 DB 匯出。

---

## 5. Red Hat 部署與維運建議

### 5.1 systemd 服務調整

現有 `systemd/bfx-lending-bot.service` 靠 `Restart=always` 反覆重跑單次腳本。改為「程式內部 `while True` 迴圈 + systemd 僅負責崩潰重啟」：

- `Restart=on-failure`、`RestartSec=30`。
- 設定 `StartLimitIntervalSec` / `StartLimitBurst`，避免異常時無限快速重啟。
- 可選用 `WatchdogSec` 搭配程式 heartbeat，偵測卡死。

### 5.2 LF 換行（已完成）

`.gitattributes` 已設定 `* text=auto eol=lf` 及 `*.py`／`*.md`／`*.yaml` 的 `eol=lf`，`start.sh` 在 Linux 不會因 CRLF 出錯。建議補一行 `*.sh text eol=lf` 明確化，確保 shell 腳本換行正規化。

### 5.3 日誌輪替

`utils/logger.py` 現用 `FileHandler`，24 小時常駐會導致單檔無限增大。改為：

- `logging.handlers.RotatingFileHandler`（例如單檔 10MB、保留 5 份），或
- 搭配系統 `logrotate` 設定管理日誌檔。

### 5.4 安全

- API Key 嚴禁勾選「提現（Withdraw）」，僅開放融資掛單與讀取權限。
- secrets 透過 `BFX_SECRETS_FILE` 載入（現已支援），檔案權限設為 `chmod 600`，禁止硬編碼於程式或 config。

### 5.5 監控與告警

- systemd `WatchdogSec` + 每次成功巡檢送出 heartbeat。
- 連續 N 次失敗時，透過 LINE Messaging API 主動告警。

---

## 6. 後續開發 Step-by-Step

### 第一步：修正致命問題（讓現雛型「正確」）

1. 修正 `get_frr()`，改抓 Bitfinex V2 `/v2/ticker/fUSD` 的 FRR 欄位。
2. 改寫通知模組為 LINE Messaging API push（`https://api.line.me/v2/bot/message/push`，需 Channel access token）。
3. `main.py` 加入 `while True` 主迴圈 + `time.sleep(interval)` + 例外隔離。

### 第二步：補策略與風控

4. `cancel_active_offers()` 真正實作「只取消未成交 offer」（`cancel_funding_offer`），不動已成交的 active loan。
5. 策略補上「只補掛差額」與 spread 多筆階梯利率、`maxtolend` 上限檢查。

### 第三步：資料與可觀測

6. 建立 `db/`（SQLite WAL 模式），記錄掛單與每日收益。
7. `logger` 換用 `RotatingFileHandler`；補上 heartbeat 與告警。

### 第四步：部署與測試

8. 補上 `strategies` 純函式單元測試 + `bot_engine` 整合測試。
9. 調整 systemd 為內部迴圈模式，先實機 dry-run，再以小額實單驗證。

---

## 附錄 A：範圍界定

- **納入**：單帳戶 USD 放貸、FRR+ 雙發彈夾策略、SQLite 記錄、systemd 常駐、LINE Messaging API 通知。
- **排除**：多交易所、多 Worker、Plugin 生態、Web 前端（先以 CLI / 日誌觀測，未來再加）。
- **技術選型**：`ccxt.bitfinex2`（V2 API）、單執行緒主迴圈、SQLite（非外部 DB）。

---

## 附錄 B：給 AI 協作者的實作指引（重要）

> 本節提供 AI 自動撰寫程式時所需的「精確規格」，避免各自解讀導致產出不一致。實作時請以本節的介面簽章、設定鍵名、驗收標準為準。

### B.1 開發環境與通用規範

- Python 版本：3.11 以上。
- 所有 `.py` 檔開頭保留 `# -*- coding: utf-8 -*-`；檔案以 UTF-8（無 BOM）、LF 換行儲存。
- 全面加上 type hints；對外函式加繁體中文 docstring。
- 命名：模組與函式 `snake_case`、類別 `PascalCase`、常數 `UPPER_SNAKE_CASE`。
- 嚴禁在日誌或例外訊息中輸出 API key、secret、access token。
- 金額計算一律以 `float` 處理後 `round(x, 2)`；利率保留至少 6 位小數（`round(rate, 6)`）。
- 每完成一個模組，先確保 `dry_run=True` 可跑通再接實盤。

### B.2 模組介面契約（函式簽章）

以下為各模組必須實作的公開介面。AI 實作時請維持簽章一致，方便跨模組組裝與測試。

```python
# strategies/base.py
class Strategy(ABC):
    @abstractmethod
    def build_offer_plan(self, balance_usd: float, frr: float) -> list[OfferPlan]: ...

# strategies/frr_plus.py
@dataclass
class OfferPlan:
    currency: str
    amount: float
    rate: float       # 日利率（decimal，例如 0.00035 = 每日 0.035%）
    duration: int     # 天期（2 或 30）

# api/base.py
class ExchangeClient(ABC):
    def test_connection(self) -> bool: ...
    def get_available_balance(self, currency: str) -> float: ...
    def get_frr(self, currency: str) -> float: ...                       # 回傳日利率
    def get_active_offers(self, currency: str) -> list[dict]: ...        # 未成交掛單
    def cancel_offer(self, offer_id: str) -> bool: ...
    def create_loan_offer(self, currency: str, amount: float,
                          rate: float, duration: int) -> dict: ...

# api/rate_limiter.py
def with_retry(max_attempts: int = 5, base_delay: float = 2.0,
               max_delay: float = 60.0): ...   # decorator，指數退避

# core/bot_engine.py
class BotEngine:
    def __init__(self, config, client, strategy, notifier, repository, logger): ...
    def run_forever(self) -> None: ...    # while True 主迴圈
    def run_once(self) -> None: ...       # 單輪巡檢（供測試與 dry-run 呼叫）

# db/repository.py
class Repository:
    def __init__(self, db_path: str): ...            # 開啟時設 PRAGMA journal_mode=WAL
    def record_offer(self, plan: OfferPlan, result: dict) -> None: ...
    def upsert_daily_earning(self, date: str, currency: str,
                             interest: float) -> None: ...
    def save_state(self, last_frr: float, last_action: str) -> None: ...

# notify/line_messaging.py
class LineMessenger:
    def __init__(self, config): ...
    def send(self, message: str) -> bool: ...
```

### B.3 主迴圈單輪流程（`run_once` 偽碼）

實作 `core/bot_engine.py` 時，單輪順序須為：

```
1. 取消未成交舊 offer（get_active_offers → cancel_offer；不動已成交 active loan）
2. 查詢 funding 錢包可用 USD 餘額
3. 若餘額 < min_required_usd → 記錄日誌、save_state、return（跳過本輪）
4. 抓取 FRR（get_frr）；若失敗回傳 None/0 → 記錄警告並跳過本輪，不可用 0 掛單
5. strategy.build_offer_plan(balance, frr) 產生掛單計畫
6. 對每個 plan：create_loan_offer → record_offer（同一 transaction 收尾）
7. 組摘要文字 → notifier.send
8. save_state(last_frr, last_action)
```

主迴圈 `run_forever` 以 `try/except` 包住 `run_once`：捕 `RetryableError` 記錄後續跑；捕 `FatalError` 發通知後 `raise`（交 systemd 重啟）；每輪結束 `time.sleep(interval_seconds)`。

### B.4 完整 config.yaml 目標範例

AI 擴充設定時，`config.yaml` 應涵蓋以下鍵（敏感值仍走 secrets）：

```yaml
bitfinex:
  api_key: ""              # 由環境變數 BFX_API_KEY 覆蓋
  api_secret: ""           # 由環境變數 BFX_API_SECRET 覆蓋
  dry_run_balance_usd: 344.12
  dry_run_frr: 0.0002

strategy:
  min_required_usd: 150
  split_threshold_usd: 300
  short_duration: 2
  long_duration: 30
  premium_rate: 0.0002
  minimum_rate: 0.0001
  long_duration_threshold: 0.00082

engine:
  interval_seconds: 600    # 主迴圈巡檢間隔（10 分鐘）
  dry_run: true            # 部署驗證用；上線改 false

retry:
  max_attempts: 5
  base_delay: 2.0
  max_delay: 60.0

database:
  path: data/lending.sqlite3

logging:
  level: INFO
  file: logs/bfx_lending_bot.log
  max_bytes: 10485760      # 10MB
  backup_count: 5

line:
  enabled: false
  channel_access_token: ""   # 由 LINE_CHANNEL_ACCESS_TOKEN 覆蓋
  to_user_id: ""             # 由 LINE_TO_USER_ID 覆蓋（push 目標）
```

### B.5 Bitfinex V2 / ccxt 對照

- **FRR（放貸底線）**：`GET https://api-pub.bitfinex.com/v2/ticker/fUSD`，回傳陣列 index 0 為 FRR（日利率）。此為公開端點，不需簽章。
- **可用餘額**：`ccxt.bitfinex2().fetch_balance()`，取 funding 錢包的可用（free）USD。
- **掛出放貸單**：`create_funding_offer(symbol='fUSD', amount, rate, period)`；`rate` 為日利率、`period` 為天期。
- **未成交掛單**：`fetch_open_orders`／對應 funding offer 查詢方法；只取消未成交者，勿取消 `fetch_funding_loans` 回傳的已成交部位。
- 所有實盤呼叫都要包在 `with_retry` decorator 內，並捕捉 `ccxt.RateLimitExceeded`、`ccxt.NetworkError`、`ccxt.ExchangeError`。

### B.6 LINE Messaging API 規格（取代已停用的 LINE Notify）

- 端點：`POST https://api.line.me/v2/bot/message/push`
- Headers：`Authorization: Bearer {CHANNEL_ACCESS_TOKEN}`、`Content-Type: application/json`
- Body：`{"to": "{USER_ID}", "messages": [{"type": "text", "text": "..."}]}`
- 環境變數：`LINE_CHANNEL_ACCESS_TOKEN`、`LINE_TO_USER_ID`。
- `enabled=false` 或缺 token 時，`send()` 應安靜回傳 `False`，不可讓通知失敗中斷主流程。

### B.7 例外映射表

| 來源 | 映射為 | 主迴圈處理 |
| --- | --- | --- |
| `ccxt.RateLimitExceeded`、`ccxt.NetworkError`、timeout、HTTP 5xx | `RetryableError` | 退避重試；仍失敗則記錄後續跑下一輪 |
| API key 無效、權限不足、簽章錯誤 | `FatalError` | 發通知後 `raise`，交 systemd 重啟 |
| 餘額 < 門檻、FRR 取不到 | `SkipCycleError` | 記錄日誌，跳過本輪 |

### B.8 邊界情況（必須處理）

- 餘額「剛好等於」`min_required_usd`（150）→ 視為可掛單（`>=`）。
- 餘額介於 `min_required_usd` 與 `split_threshold_usd` 之間 → 單筆全下，不拆單。
- FRR 回傳 `None`、`0` 或負值 → 跳過本輪，不可用無效利率掛單。
- 已有未成交舊 offer → 先取消再重掛（避免重複曝險）。
- 拆單後單筆金額低於 150 → 退回為單筆全下（例如餘額 301 拆成 150.5 仍合法；但若門檻邊界導致單筆 < 150 則不可拆）。
- 掛單 API 部分成功、部分失敗 → 已成功者仍寫入 DB，失敗者記錄並於下一輪重試。

### B.9 檔案變更清單（老雛型 → 新架構）

| 動作 | 檔案 | 說明 |
| --- | --- | --- |
| 移動＋修正 | `modules/exchange_client.py` → `api/bitfinex_client.py` | 修正 `get_frr`、補 `get_active_offers`／`cancel_offer` |
| 新增 | `api/base.py`、`api/rate_limiter.py` | 抽象介面與重試 decorator |
| 移動＋擴充 | `modules/lending_strategy.py` → `strategies/frr_plus.py` | 補 spread、只補掛差額、maxtolend |
| 新增 | `strategies/base.py` | Strategy 抽象基底 |
| 新增 | `core/bot_engine.py` | 主迴圈狀態機（從 `main.py` 抽出） |
| 改寫 | `modules/line_notifier.py` → `notify/line_messaging.py` | 改用 LINE Messaging API |
| 新增 | `db/models.py`、`db/repository.py` | SQLite WAL 資料層 |
| 修改 | `utils/logger.py` | 改 `RotatingFileHandler` |
| 精簡 | `main.py` | 只保留 bootstrap，主迴圈移入 `core/` |
| 修改 | `systemd/bfx-lending-bot.service` | `Restart=on-failure`、配合內部迴圈 |
| 修改 | `requirements.txt` | 移除 LINE Notify 相關假設；`ccxt`、`PyYAML`、`requests` 版本鎖定 |

### B.10 各模組驗收標準（Definition of Done）

- **api**：`dry_run` 下 `get_frr` 回傳設定值；實盤下能正確解析 `/v2/ticker/fUSD` FRR；所有實盤呼叫具重試。
- **strategies**：純函式、無副作用；涵蓋 B.8 所有邊界情況的單元測試全數通過。
- **core**：`run_once` 可獨立呼叫並通過整合測試；`run_forever` 遇 `RetryableError` 不中斷。
- **db**：WAL 模式啟用；掛單與每日收益正確寫入；重複日期以 upsert 累加。
- **notify**：`enabled=false` 時安靜略過；`enabled=true` 時成功推播文字訊息。
- **部署**：`systemctl start` 後可常駐；kill 程序後由 systemd 自動重啟；日誌正確輪替。

### B.11 術語表

- **FRR（Flash Return Rate）**：Bitfinex 官方計算的市場平均放貸日利率，作為浮動掛單底線。
- **offer（掛單）**：尚未成交的放貸委託，可被取消。
- **loan（放貸部位）**：已成交、資金已借出的部位，**不可**任意取消。
- **funding 錢包**：Bitfinex 用於放貸的資金錢包，與交易錢包分開。
- **日利率 vs 年化**：Bitfinex 掛單用「日利率」；年化 ≈ 日利率 × 365。閾值 0.00082 日利率 ≈ 30% 年化。
- **dry-run**：不實際下單的驗證模式，用設定中的假餘額與假 FRR 跑通流程。

---

## 附錄 C：程式異動紀錄（Change Log）

> **提醒（給 AI 與開發者）**：只要對本專案的任何程式碼或設定進行修改，完成後**務必**在下表新增一列，記錄「異動日期、異動人員、異動說明」。這是強制流程，不可略過。
>
> - 日期格式：`YYYY-MM-DD`。
> - 異動人員：真人請填姓名／代號；AI 協作請填「AI（模型名稱）」。
> - 異動說明：簡述改了什麼、為什麼改、影響哪些檔案。

| 異動日期 | 異動人員 | 異動說明 |
| --- | --- | --- |
| 2026-07-14 | ShuYu | 建立 `SHUYU_PROJECT_PLAN.md` 專案規劃書，並補上附錄 B 實作指引與附錄 C 異動紀錄章節。 |
| <!-- YYYY-MM-DD --> | <!-- 姓名 / AI（模型） --> | <!-- 異動說明，例如：修正 get_frr 改抓 /v2/ticker/fUSD --> |
