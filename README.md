# ShuyuLendingBot

這是一個以 Bitfinex 放貸為核心的 Python 機器人專案。其目標不是單純做一個簡單腳本，而是建立一個可持續演進、可部署於 Linux 主機、並支援後續正式上線的放貸機器人雛形。

這個專案目前先以 dry-run 模式為主，目的是先把整個流程跑通：讀取設定、載入 secrets、檢查交易所連線、判斷策略、生成掛單計畫，並把流程與日誌整理乾淨。之後可以再往實際掛單與長時間自動執行發展。

---

## 1. 專案目標

這個專案的核心目標可以概括為三件事：

1. 以 Bitfinex 放貸市場為場景，實作一個可被持續運行的放貸機器人骨架。
2. 以 PRD 的策略思維為基礎，先實作簡單且清楚的策略邏輯，避免一開始就把事情做得太複雜。
3. 建立可部署於 Linux 主機的工程化結構，包含 secrets 管理、systemd 服務、Docker Compose 與日誌輸出。

---

## 2. 商業邏輯說明

這個專案的商業邏輯目前聚焦在「放貸收益」與「資金利用率」兩個方向。

### 目前實作的基本思路

- 依據可用 USD 餘額決定是否有條件掛單。
- 依據 FRR（Funding Rate / Funding Return Rate）作為市場利率基準。
- 依據策略設定，決定要掛的利率、天期與拆單方式。
- 目前先以 dry-run 方式模擬掛單，避免一開始就把真實資金下出去。

### 目前的策略方向

目前的邏輯是：

- 如果餘額低於最低門檻，就不掛單。
- 如果餘額足夠，會依據設定產生一組掛單方案。
- 若餘額高於拆單門檻，則拆成兩筆掛單。
- 若市場利率高於某個門檻，則選擇較長的天期。

這個版本屬於「第一階段的策略雛形」，後續可以再擴充為更細緻的動態策略，例如：

- 根據市場利率變化自動調整利率
- 根據資金量與風險偏好調整拆單
- 根據市場熱度與掛單深度做更智慧的出價
- 針對不同幣種、不同天期做不同策略

---

## 3. 程式架構說明

目前專案採用比較清楚的分層結構，方便後續擴充與維護。

### 目錄結構

- config/
  - 放置設定相關邏輯與設定載入程式。
  - 目前主要是讀取 YAML 設定檔與 secrets。

- modules/
  - 放置核心業務模組。
  - 包含：
    - exchange_client.py：與交易所互動的封裝層
    - lending_strategy.py：策略邏輯
    - line_notifier.py：LINE Notify 通知封裝

- utils/
  - 放置通用工具。
  - 目前包含 logger.py，負責日誌輸出與紀錄。

- systemd/
  - 放置 systemd 服務檔，方便在 Linux 主機上以服務方式執行。

- logs/
  - 放置執行日誌。

### 主要執行流程

1. 讀取設定檔 config.yaml。
2. 自動載入主機上的 secrets 檔案。
3. 初始化日誌、通知、交易所連線與策略模組。
4. 取得可用餘額與 FRR。
5. 根據策略生成掛單計畫。
6. 以 dry-run 方式模擬掛單結果。

---

## 4. 設定方式

### 4.1 依賴套件

先安裝 Python 依賴：

```bash
pip install -r requirements.txt
```

### 4.2 設定檔

專案設定檔為：

- config.yaml

這個檔案主要放「非敏感」設定，例如：

- dry-run 金額
- 門檻值
- 利率、天期參數
- 日誌設定

### 4.3 Secrets 管理

敏感資訊請放在 Linux 主機上的以下位置：

```bash
/home/shuyu/.config/bfx-lending-bot/secrets.env
```

範例檔案請參考：

- secrets.env.example

請確保 secrets 檔案權限為 600，避免被其他使用者讀取。

### 4.4 目前支援的環境變數

目前程式會讀取以下環境變數：

- BFX_API_KEY
- BFX_API_SECRET
- LINE_NOTIFY_TOKEN
- LINE_NOTIFY_CHANNEL
- BFX_SECRETS_FILE

如果沒有設定環境變數，程式會回退到 config.yaml 與預設路徑。

---

## 5. 執行方式

### 5.1 直接執行

```bash
bash start.sh
```

### 5.2 使用 Docker Compose

```bash
docker compose up -d --build
```

### 5.3 使用 systemd

```bash
sudo cp systemd/bfx-lending-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bfx-lending-bot
```

---

## 6. 部署建議

這個專案現在已經具備基本的部署雛形，適合在 Linux 主機上做進一步實作。

### 建議的部署方式

- 個人開發與測試：直接使用 python3 main.py 或 bash start.sh
- 自動化維運：使用 systemd 服務
- 容器化：使用 Docker Compose 或 Podman

### 建議的日誌管理方式

- 將 stdout / stderr 輸出收斂到 logs 目錄
- 未來可再接上 logrotate，避免日誌無限增長
- 若後續正式上線，可把日誌送到遠端集中管理

---

## 7. 未來優化方向

這個專案目前還是雛形，後續建議分階段演進：

### 第一階段：從 dry-run 走向實際掛單

- 真正接上 Bitfinex API 下單流程
- 加入取消舊單與重試邏輯
- 增加錯誤處理與重試機制

### 第二階段：強化策略

- 加入更細緻的 FRR 判斷
- 增加不同天期的策略切換
- 依據市場波動調整掛單數量與利率

### 第三階段：提升穩定性

- 加入心跳檢查與健康監控
- 增加自動重啟與異常回報
- 加入執行狀態紀錄與歷史記錄

### 第四階段：擴充功能

- 加入更多通知管道，例如 Telegram、Slack
- 加入資料庫或 JSON 歷史紀錄
- 加入 Web UI 或簡單儀表板

---

## 8. 注意事項

- 請不要把真正的 API 金鑰、TOKEN 或 secret 值寫進 GitHub。
- 請保持 secrets 檔案權限為 600。
- 目前版本仍以 dry-run 為主，尚未正式下單。
- 若未來要正式上線，請先做好風險控制與交易量限制。

---

## 9. 開發建議

如果你之後要繼續開發，建議依照這個順序來做：

1. 先把實際掛單流程接上
2. 再把主迴圈改成每隔一段時間巡檢一次
3. 再加上錯誤恢復與通知
4. 最後再進一步做策略優化與長期運行

這樣比較不容易一開始就把整個專案做得太複雜。