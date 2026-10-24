# 2026-10-24 政策模擬（D074 的依據）——研究腳本，不是工具

**這個目錄只放在 `research/policy-sim-20261024` 分支，刻意不合併進 main**：
腳本是當天一次性的研究，**沒有測試**。要變成常設工具（TASKS 丙-4），
請照專案規矩重寫並附測試——尤其要有一條「對不上時會說對不上」。

方法、驗收與結論都寫在 `.project-docs/DECISIONS.md` 的 **D073**（判定）與 **D074**（政策比較）。

## 檔案

| 檔案 | 做什麼 |
|---|---|
| `returns_lib.py` | 實得年化三種算法（D072 第五節）：①入帳日落在窗內 ②平移一天 ③部位推算 |
| `reproduce.py` | 先重現 D072 第二節已記錄的數字（還原到 10-10 23:47 的資料狀態） |
| `analyze.py`／`rolling.py` | 判定窗、延長期、逐週、7 日窗（D073） |
| `sim.py` | 政策模擬：成交規則同 D049、持有時間用真實樣本袋、跨起跑點（D054） |
| `validate_fill.py` | 驗收一：每筆真實成交回頭重跑成交規則（天期 2 1.18×、天期 30 0.31×） |
| `run_validate_policy.py` | 驗收二：重現 08-17～09-13（6.56%／6.59% 對實際 6.46%） |
| `run_main.py`／`run_robust.py`／`run_weekly.py` | 政策比較、地板 × P 掃描、持有假設敏感度、逐週 |
| `diag_A.py` | 第一版重現失敗時的診斷（P 被固定成 12） |

## 怎麼重跑

工作目錄需要三樣東西（`POLICY_SIM_WORKDIR`，預設是目前目錄）：

1. **正式 DB 的唯讀副本**（不要直接讀正在寫入的那一份）：
   ```
   python3 -I -c "import sqlite3; s=sqlite3.connect('file:<正式 DB>?mode=ro', uri=True); d=sqlite3.connect('snap/lending.sqlite3'); s.backup(d)"
   ```
2. **K 線**（公開端點，唯讀）：`dl2/candles_p2.json`、`dl2/candles_p30.json`
   ```
   curl -s "https://api-pub.bitfinex.com/v2/candles/trade:1h:fUSD:p2/hist?start=<ms>&end=<ms>&limit=10000&sort=1" -o dl2/candles_p2.json
   ```
   先拿重疊段跟 DB 的 `market_candles` 對過再用（10-24 那次：天期 30 872 根 0 不一致）。
3. `hold_samples.json`、`market_rate_by_hour.json`：由 DB 副本產生（產生方式見 D074 第二節與 `sim.py` 的說明）。

⚠ **天期 30 的模擬會把等待算快約 3 倍**（排隊看不到）——只能當上限。天期 2 才驗得過。
