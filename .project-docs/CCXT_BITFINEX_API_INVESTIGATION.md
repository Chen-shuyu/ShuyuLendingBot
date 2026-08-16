# ccxt × Bitfinex Funding API 盤點調查

> 本檔案為 TASKS.md「🔴 下一步・最高優先」調查項目的原始盤點紀錄（資料/清單性質），
> 供之後彙整成 DECISIONS.md 新決策（D010）時參考。調查完成、決策拍板後，
> 結論摘要一併寫進 DECISIONS.md，本檔案保留作為詳細佐證資料。

- 調查日期：2026-07-26
- ccxt 版本：4.5.64（`requirements.txt` 釘選 `ccxt>=4.2.0`）
- ccxt 安裝位置：`/home/shuyu/.local/lib/python3.12/site-packages/ccxt/bitfinex.py`（3798 行）
- 官方文件來源：<https://docs.bitfinex.com/docs/introduction>（REST v2 / WebSocket v2）

---

## 結論摘要（TL;DR）

1. **ccxt 對 Bitfinex 的「P2P Funding（放貸市場）」從頭到尾沒有任何統一（unified）方法**，
   不是版本移除、是從未實作過。全套件搜尋 `create_funding_offer` / `cancel_funding_offer` /
   `fetch_funding_offers` 這類名稱，在 ccxt 任何交易所、任何檔案（含 base Exchange 類別）都
   查無結果——`create_loan_offer()` 現有的 `hasattr()` 判斷式檢查的是**從未存在過的方法**，
   不是「這版剛好沒有」，必定每次都走到 `raise FatalError`。
2. ccxt 的 `has{}` 能力宣告也印證這點：`bitfinex.py` 的 `has` 字典裡完全沒有
   `createFundingOffer`／`fetchFundingOffers`／`fetchFundingLoans` 這些鍵值，代表官方
   ccxt maintainer 自己也沒有把這組能力列入「聲稱支援」的範圍。
3. ccxt 唯一能碰到 Bitfinex funding 資料的路徑，是**implicit/raw API**（也就是
   `private_post_auth_*`／`public_get_*` 這種直接對應官方 REST 端點路徑的方法）——
   這正是 `get_frr()` 與 `cancel_active_offers()` 目前已經在用的做法，**方向正確**。
4. 逐一比對官方文件後，`get_frr()`、`get_available_balance()`、`cancel_active_offers()`
   的欄位解析與端點呼叫方式都與官方規格一致，判定**正確**。**唯一還沒修的是
   `create_loan_offer()`**，需要改呼叫 `private_post_auth_w_funding_offer_submit`（詳見下方
   §4、§5）。

---

## 1. ccxt 對 Bitfinex funding 提供的方法盤點

### 1.1 統一（unified）方法 —— 結論：不存在

在 `bitfinex.py` 搜尋所有 `def fetch_`／`def create_`／`def cancel_` 開頭且與
`fund/loan/offer/borrow/lend` 相關的方法，結果只有：

```
fetch_funding_rates()          # 永續合約資金費率，跟 P2P 放貸市場無關
fetch_funding_rate_history()   # 同上
parse_funding_rate()           # 同上（內部解析用）
parse_funding_rate_history()   # 同上（內部解析用）
```

這四個方法名稱雖然有 `funding` 字樣，但語意上對應的是**衍生品/永續合約的資金費率
（funding rate，多空雙方互付的費用）**，跟 Bitfinex 的 **P2P 放貸市場（margin funding /
`fUSD` 這種 f-prefixed 貨幣對）完全是兩件事**——這正是專案先前 `get_frr()` 誤用
`fetch_funding_rate()` 導致數值錯誤的根本原因（見 DECISIONS.md 相關修正紀錄）。

全 ccxt 套件搜尋 `create_funding_offer`／`cancel_funding_offer`／`fetch_funding_offers`：

```bash
grep -rl "def create_funding_offer\|def cancel_funding_offer\|def fetch_funding_offers" ccxt/
# 無結果（任何交易所都沒有這組方法，base Exchange 類別也沒有）
```

`bitfinex.py` 的 `has{}` 能力宣告也沒有任何一個 funding-offer 相關鍵值（完整清單見
`/home/shuyu/.local/lib/python3.12/site-packages/ccxt/bitfinex.py:43-136`）。

**判定**：現有程式碼 `create_loan_offer()` 中 `hasattr(self.exchange, "create_funding_offer")` /
`"createFundingOffer"` 這兩個判斷式檢查的方法名稱是**在整個 ccxt 生態系中從未存在過的
虛構名稱**，不是「這個版本剛好被移除」。這兩個 `if` 分支永遠不會成立，程式碼一定會落到
`raise FatalError("目前的 ccxt 版本沒有提供此交易所所需的 funding-offer 方法。")`。

### 1.2 Raw / Implicit 方法 —— 完整清單

ccxt 對每個交易所都會依官方 REST 端點路徑自動產生一組「implicit API」方法
（命名規則：`{public|private}_{get|post}_` + 路徑轉底線），這些不是 ccxt 自己包裝過的
統一格式，而是直接對應官方端點、回傳官方原始格式。以下是 `abstract/bitfinex.py`
（3798 行檔案中定義 implicit API 清單的部分）裡與 funding 相關的完整清單：

| ccxt 方法名稱（snake_case） | 對應官方 REST 路徑 | HTTP |
|---|---|---|
| `public_get_ticker_symbol` | `GET /v2/ticker/{symbol}` | 公開 |
| `public_get_funding_stats_symbol_hist` | `GET /v2/funding/stats/{symbol}/hist` | 公開 |
| `public_get_book_symbol_precision` | `GET /v2/book/{symbol}/{precision}` | 公開 |
| `public_get_trades_symbol_hist` | `GET /v2/trades/{symbol}/hist` | 公開 |
| `private_post_auth_r_wallets` | `POST /v2/auth/r/wallets` | 私有 |
| `private_post_auth_r_wallets_hist` | `POST /v2/auth/r/wallets/hist` | 私有 |
| `private_post_auth_r_funding_offers` | `POST /v2/auth/r/funding/offers` | 私有 |
| `private_post_auth_r_funding_offers_symbol` | `POST /v2/auth/r/funding/offers/{symbol}` | 私有 |
| `private_post_auth_w_funding_offer_submit` | `POST /v2/auth/w/funding/offer/submit` | 私有 |
| `private_post_auth_w_funding_offer_cancel` | `POST /v2/auth/w/funding/offer/cancel` | 私有 |
| `private_post_auth_w_funding_offer_cancel_all` | `POST /v2/auth/w/funding/offer/cancel/all` | 私有 |
| `private_post_auth_w_funding_close` | `POST /v2/auth/w/funding/close` | 私有 |
| `private_post_auth_w_funding_auto` | `POST /v2/auth/w/funding/auto` | 私有 |
| `private_post_auth_w_funding_keep` | `POST /v2/auth/w/funding/keep` | 私有 |
| `private_post_auth_r_funding_offers_symbol_hist` | `POST /v2/auth/r/funding/offers/{symbol}/hist` | 私有 |
| `private_post_auth_r_funding_offers_hist` | `POST /v2/auth/r/funding/offers/hist` | 私有 |
| `private_post_auth_r_funding_loans` | `POST /v2/auth/r/funding/loans` | 私有 |
| `private_post_auth_r_funding_loans_hist` | `POST /v2/auth/r/funding/loans/hist` | 私有 |
| `private_post_auth_r_funding_loans_symbol` | `POST /v2/auth/r/funding/loans/{symbol}` | 私有 |
| `private_post_auth_r_funding_loans_symbol_hist` | `POST /v2/auth/r/funding/loans/{symbol}/hist` | 私有 |
| `private_post_auth_r_funding_credits` | `POST /v2/auth/r/funding/credits` | 私有 |
| `private_post_auth_r_funding_credits_hist` | `POST /v2/auth/r/funding/credits/hist` | 私有 |
| `private_post_auth_r_funding_credits_symbol` | `POST /v2/auth/r/funding/credits/{symbol}` | 私有 |
| `private_post_auth_r_funding_credits_symbol_hist` | `POST /v2/auth/r/funding/credits/{symbol}/hist` | 私有 |
| `private_post_auth_r_funding_trades_symbol_hist` | `POST /v2/auth/r/funding/trades/{symbol}/hist` | 私有 |
| `private_post_auth_r_funding_trades_hist` | `POST /v2/auth/r/funding/trades/hist` | 私有 |
| `private_post_auth_r_info_funding_key` | `POST /v2/auth/r/info/funding/{key}` | 私有 |

這組 implicit 方法**完整涵蓋**官方文件列出的所有 funding REST 端點（見 §2），代表
「整支改走 raw API」在方法可用性上沒有缺口——ccxt 沒有擋掉任何一個官方端點，只是不幫
你把回傳的陣列格式轉成統一物件，需要自己照官方文件的 index 對照表解析。

### 1.3 為什麼 implicit 方法「可靠」，統一方法反而「地雷」

- **Implicit 方法是機械化產生的**：ccxt 內部依官方 API 路徑表自動生成，只要官方端點沒改
  路徑，這組方法名稱就不會消失，跟 ccxt 版本迭代基本無關（`get_frr()`／
  `cancel_active_offers()` 兩次意外驗證了這點）。
- **統一方法要靠該交易所的 maintainer 手動實作**：Bitfinex 的 P2P funding 市場是相對小眾
  的功能（多數交易所連 P2P 放貸都沒有），ccxt maintainer 沒有動機為它建一套統一抽象層，
  這解釋了為什麼「看起來應該存在」的 `createFundingOffer` 從未被實作。
- 先前踩到的三次隱藏 bug（`ccxt.bitfinex2` 被移除、`fetch_balance` 查錯錢包、
  `cancel_active_offers` 查錯訂單類型）**全部發生在「試圖用統一/半統一介面」的地方**，
  已經改走 raw API 的 `get_frr()` 目前為止沒有再踩雷。

---

## 2. Bitfinex 官方 REST API — Funding 相關端點總覽

來源：<https://docs.bitfinex.com/llms.txt>（官方文件索引）與各端點頁面。

### 2.1 認證端點（REST Auth）—— 14 個

| 端點 | 路徑 | 說明 |
|---|---|---|
| Active Funding Offers | `POST /v2/auth/r/funding/offers/{Symbol}` | 查詢目前未成交的放貸掛單 |
| Submit Funding Offer | `POST /v2/auth/w/funding/offer/submit` | 建立新的放貸掛單 |
| Cancel Funding Offer | `POST /v2/auth/w/funding/offer/cancel` | 依 ID 取消單筆掛單 |
| Cancel All Funding Offers | `POST /v2/auth/w/funding/offer/cancel/all` | 一次取消全部（可篩選幣種），不需先查詢再逐筆取消 |
| Funding Close | `POST /v2/auth/w/funding/close` | 結束一筆已成交的放貸（loan/credit） |
| Funding Auto-renew | `POST /v2/auth/w/funding/auto` | 設定資金到期後自動依指定利率/期限續放 |
| Keep Funding | `POST /v2/auth/w/funding/keep` | 切換單筆 loan/credit 的「保留」狀態，避免自動歸還 |
| Funding Offers History | `POST /v2/auth/r/funding/offers/hist` | 已取消/已成交掛單的歷史紀錄 |
| Funding Loans | `POST /v2/auth/r/funding/loans` | 「未被使用」的已出借資金（尚在等待被借走） |
| Funding Loans History | `POST /v2/auth/r/funding/loans/hist` | 上者的歷史紀錄 |
| Funding Credits | `POST /v2/auth/r/funding/credits` | 「已被使用」的出借資金（已配對成交、正在計息） |
| Funding Credits History | `POST /v2/auth/r/funding/credits/hist` | 上者的歷史紀錄 |
| Funding Trades | `POST /v2/auth/r/funding/trades/{Symbol}/hist` | 每筆成交紀錄（金額、利率、期限），**適合拿來算每日收益** |
| Funding Info | `POST /v2/auth/r/info/funding/{Key}` | 帳戶層級的 funding 統計資訊 |

### 2.2 WebSocket 認證頻道 —— 5 個（目前專案未使用 WebSocket）

`Funding Offers`／`Funding Credits`／`Funding Loans`／`Funding Info`／`Funding Trades`
即時推播頻道，路徑與 REST 版一一對應。目前專案採輪詢（polling）架構，暫不需要，
但列入 M3/M4 若要做即時告警可評估。

---

## 3. 關鍵端點詳細規格（已用到或即將用到的部分）

### 3.1 Submit Funding Offer（`create_loan_offer()` 應該改呼叫的端點）

`POST /v2/auth/w/funding/offer/submit`

| 參數 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `type` | string | 是 | `LIMIT`／`FRRDELTAFIX`／`FRRDELTAVAR` |
| `symbol` | string | 是 | 如 `fUSD` |
| `amount` | string | 是 | 正值＝掛出放貸 |
| `rate` | string | 是 | 日利率小數（1% → `"0.01"`） |
| `period` | int32 | 是 | 天期，**最小 2、最大 120** |
| `flags` | int32 | 否 | 選用旗標 |

`type` 三選一的語意差異（直接影響策略設計，建議請使用者一併確認要用哪種）：

- **`LIMIT`**：固定利率掛單，等同目前 D004 策略「算出一個固定利率就掛出去」的做法。
- **`FRRDELTAFIX`**：掛「相對 FRR 的偏移量」，成交當下鎖定利率（之後 FRR 變動不影響已成交部分）。
- **`FRRDELTAVAR`**：掛「相對 FRR 的動態偏移量」，利率隨 FRR 持續浮動（偏移量必須為正）。

目前策略層 `strategies`/`lending_strategy.py` 算出的是「目標利率 = max(FRR+premium,
minimum_rate)」這種**算好的固定數值**，語意上對應 `type="LIMIT"`；若未來想讓掛單利率
自動跟著 FRR 浮動、減少每輪重新計算利率的必要，`FRRDELTAVAR` 是更貼近「FRR+ 策略」
原意的做法（MikaLendingBot 的 FRR 覆寫邏輯概念上更接近這個）——**這點列入 §5 待使用者決定**。

### 3.2 Active Funding Offers（`cancel_active_offers()` 目前用來查詢的端點）

`POST /v2/auth/r/funding/offers/{Symbol}`，回傳陣列，關鍵欄位：
`[0]=ID`、`[1]=SYMBOL`、`[4]=AMOUNT`、`[6]=TYPE`、`[10]=STATUS`、`[14]=RATE`、`[15]=PERIOD`。

比對現有程式碼 `exchange_client.py:139-145` 的解析（`offer[0]`／`offer[1]`／`offer[4]`／
`offer[14]`／`offer[15]`）——**index 對照完全正確**。

### 3.3 Cancel Funding Offer / Cancel All Funding Offers

- `Cancel Funding Offer`（`POST /v2/auth/w/funding/offer/cancel`，參數僅 `id`）——
  現有程式碼用法正確。
- `Cancel All Funding Offers`（`POST /v2/auth/w/funding/offer/cancel/all`，參數僅選填
  `currency`）——**可以一次取消全部，不需要「先查詢再逐筆取消」**。目前
  `cancel_active_offers()` 用的是「查詢 + for 迴圈逐筆取消」，屬於可運作但非最精簡的做法
  （好處是能回傳每筆被取消掛單的明細做 log／通知，壞處是多次 API 呼叫、且 UI
  上仍是逐筆送出取消請求）。**列入 §5 待使用者決定是否簡化**。

### 3.4 Ticker（`get_frr()` 用來查詢 FRR 的端點）

`GET /v2/ticker/{symbol}`，當 `symbol` 為 funding 貨幣（如 `fUSD`）時，
**`index [0]` 即為 FRR**（Flash Return Rate，過去一小時所有固定利率成交的平均值）。
現有程式碼 `ticker[0]` 用法正確。

### 3.5 Wallets（`get_available_balance()` 用來查詢餘額的端點）

`POST /v2/auth/r/wallets`，回傳陣列每筆錢包：
`[0]=TYPE`（`exchange`／`margin`／`funding` 三選一）、`[1]=CURRENCY`、`[2]=BALANCE`、
`[4]=AVAILABLE_BALANCE`。ccxt 的 `fetch_balance({"type": "funding"})` 內部呼叫的正是這支
implicit API（`privatePostAuthRWallets`），並依 `type` 參數篩選對應錢包（見
`bitfinex.py:940-979`）——**現有程式碼用法正確**（D009 的修正是對的）。

---

## 4. ShuyuLendingBot 現況比對表

| `exchange_client.py` 方法 | 實際呼叫的 ccxt API | 統一／raw | 對照官方文件 | 判定 |
|---|---|---|---|---|
| `test_connection()` | `fetch_balance()`（無 `type` 參數） | 統一 | 預設查 `exchange` 錢包，不是 `funding` | ⚠️ 語意上查錯錢包，但用途僅是「連線測試」不影響金額判讀，風險低（見 §6） |
| `get_available_balance()` | `fetch_balance({"type": "funding"})` | 統一（走 `privatePostAuthRWallets`） | 一致 | ✅ 正確 |
| `get_frr()` | `public_get_ticker_symbol({"symbol": f"{ccy}"})` | raw | 一致（index 0 = FRR） | ✅ 正確 |
| `cancel_active_offers()` 查詢 | `private_post_auth_r_funding_offers_symbol` | raw | 一致 | ✅ 正確 |
| `cancel_active_offers()` 取消 | `private_post_auth_w_funding_offer_cancel` | raw | 一致 | ✅ 正確（可考慮改用 cancel/all，見 §3.3） |
| `create_loan_offer()` | `hasattr` 檢查 `create_funding_offer`／`createFundingOffer`（**兩者皆不存在**） | 統一（虛構、不存在） | 應改用 `private_post_auth_w_funding_offer_submit` | ❌ **必定失敗，需修正** |

### 額外發現（超出「API 用法對不對」範圍，但調查過程中一併注意到）

- **`cancel_active_offers()` 目前沒有被 `main.py` 的 `run_once()` 呼叫**——搜尋全專案，
  這個方法只有定義、沒有任何呼叫點。若策略要做「只補掛差額」（TASKS.md M2 待辦），
  勢必要決定「補掛前要不要先取消舊掛單」的邏輯，屆時才會真正用到這支方法。目前先記錄，
  不算 ccxt API 用法問題，留給 M2 開發時處理。

---

## 5. 待使用者決定的問題

1. **`create_loan_offer()` 修正時，`type` 要用 `LIMIT` 還是 `FRRDELTAVAR`？**
   - `LIMIT`：延續現有策略層「算好固定利率再掛」的邏輯，改動最小。
   - `FRRDELTAVAR`：掛單利率交給 Bitfinex 自動跟 FRR 浮動，更貼近 D004「FRR+ 動態底線」
     的原始精神，但策略層的「利率計算」邏輯要改成「計算相對 FRR 的 premium 偏移量」
     而非「算出絕對利率」，改動範圍較大。
   - 建議：先用 `LIMIT` 讓 M2 能繼續推進（風險最低、改動最小），`FRRDELTAVAR` 列入 M2
     的「策略優化」待辦另外評估。
2. **`cancel_active_offers()` 要不要改用 `cancel/all` 端點簡化？**
   - 維持現況（查詢+逐筆取消）：能保留每筆掛單明細做 log／LINE 通知內容。
   - 改用 `cancel/all`：呼叫次數少、程式碼更簡單，但取消當下拿不到明細（可先查詢一次
     留存明細、再呼叫 cancel/all 執行取消，兩者可以並存）。
   - 建議：先維持現況，不是急迫問題。
3. **`test_connection()` 的 `fetch_balance()` 要不要也加上 `type="funding"`？**
   - 目前只做「連線測不測得通」的布林判斷，查哪個錢包不影響邏輯正確性，優先度低，
     但補上可以讓語意更一致（都查 funding 錢包）、且能在啟動階段就順便驗證 funding
     錢包權限是否正常開通。
   - 建議：M2 修正 `create_loan_offer()` 時，順手把這裡也補上 `type="funding"`（同一輪
     順手修，比照 D009 的做法）。

---

## 6. 後續建議動作

1. 修正 `create_loan_offer()`：改呼叫 `private_post_auth_w_funding_offer_submit`，
   帶入 `type`（依 §5.1 決定）、`symbol`、`amount`（字串、正值）、`rate`（日利率字串）、
   `period`（限制 2～120 天，策略層目前的「30 天鎖利」與「2 天短天期」都在範圍內，
   不需額外檢查）。
2. 比照 D009 的模式，同一輪一併修正 `test_connection()` 補 `type="funding"`（§5.3）。
3. 這份盤點的結論（「全面改走 raw/implicit API 作為 Bitfinex funding 的統一呼叫方式」）
   待使用者確認後，寫成 DECISIONS.md 新決策（D010），正式解除 TASKS.md 目前的
   「🔴 最高優先」阻塞狀態，才能繼續 M2 其餘項目（差額補掛、spread、maxtolend）。
