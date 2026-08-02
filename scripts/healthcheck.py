# -*- coding: utf-8 -*-
"""容器健康檢查：判斷機器人是否還在正常巡檢。

「容器還活著」不等於「機器人還在工作」——程式可能卡在某個不返回的呼叫上，
行程還在但已經好幾輪沒有巡檢。這支腳本讀 `bot_state.last_run_at`（M3 已經
把每輪心跳寫進 SQLite，含正常略過的輪次），只問一件事：**距離上一次心跳
是不是太久了**。

刻意不看 `consecutive_failures`：連續失敗代表交易所連線或金鑰有問題，
機器人本身還在正常工作，重啟容器並不會讓它變好，那條路已經由 `FailureTracker`
的告警負責（見 DECISIONS.md D016）。

離開碼遵循容器 healthcheck 慣例：0 = healthy，1 = unhealthy。
資料庫一律以唯讀模式開啟，健康檢查不該有任何副作用——特別是不能像
`Repository` 那樣順手建立目錄與資料表，否則 DB 掛載掉了反而會被檢查本身補回去，
真正的問題就被蓋掉了。
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# 容忍幾輪沒有心跳才算不健康。取 3 輪是為了讓單輪的網路延遲、
# 取消掛單的等待、交易所偶發變慢都不會誤判成卡死。
DEFAULT_SILENCE_CYCLES = 3
# 再加一段固定緩衝，避免 interval 設得很小時（例如測試用 10 秒）門檻過於嚴苛。
DEFAULT_SILENCE_BUFFER_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = 600


def project_root() -> Path:
    """專案根目錄（本檔在 `scripts/` 底下，往上一層）。

    不依賴當前工作目錄：健康檢查是由容器執行時期呼叫的，cwd 不保證是 /app。
    """
    return Path(__file__).resolve().parent.parent


def max_silence_seconds(engine_config: Optional[Dict[str, Any]]) -> int:
    """算出「多久沒心跳就算不健康」。

    預設是巡檢間隔的 3 倍再加 60 秒；若 `engine.health_max_silence_seconds`
    有設值則直接採用，讓間隔特別長或特別短的部署能自行調整。
    """
    engine_config = engine_config or {}

    override = engine_config.get("health_max_silence_seconds")
    if override:
        return max(1, int(override))

    interval = int(engine_config.get("interval_seconds", DEFAULT_INTERVAL_SECONDS) or DEFAULT_INTERVAL_SECONDS)
    return interval * DEFAULT_SILENCE_CYCLES + DEFAULT_SILENCE_BUFFER_SECONDS


def evaluate(state: Optional[Dict[str, Any]], limit_seconds: int, now: Optional[datetime] = None) -> Tuple[bool, str]:
    """依狀態列判斷健康與否，回傳 (是否健康, 說明文字)。

    抽成純函式是為了能直接對各種邊界情況寫測試，不必真的準備一個 SQLite 檔。
    """
    now = now or datetime.now(timezone.utc)

    if not state or not state.get("last_run_at"):
        return False, "bot_state 尚未寫入任何心跳（機器人可能還沒跑完第一輪）"

    raw = str(state["last_run_at"])
    try:
        last_run_at = datetime.fromisoformat(raw)
    except ValueError:
        return False, f"心跳時間無法解析：{raw}"

    if last_run_at.tzinfo is None:
        # 寫入端一律帶 UTC 時區，這裡只是防呆：沒有時區就當成 UTC，
        # 免得跟 now 相減直接拋 TypeError。
        last_run_at = last_run_at.replace(tzinfo=timezone.utc)

    age = (now - last_run_at).total_seconds()
    if age < 0:
        # 心跳時間在未來，通常是主機時鐘被校正過。這不是機器人的錯，
        # 判成不健康會平白重啟一個好好的容器。
        return True, f"心跳時間 {raw} 在未來（時鐘偏移），視為正常"

    if age > limit_seconds:
        return False, f"距離上次心跳已 {int(age)} 秒，超過上限 {limit_seconds} 秒"

    return True, f"心跳正常，距離上次巡檢 {int(age)} 秒（上限 {limit_seconds} 秒）"


def read_state(db_path: Path) -> Optional[Dict[str, Any]]:
    """以唯讀模式讀回 `bot_state` 那一列，讀不到就回 None。"""
    uri = f"file:{db_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT last_run_at, last_frr, last_action, consecutive_failures FROM bot_state WHERE id = 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def resolve_db_path(root: Path) -> Path:
    """決定 SQLite 檔位置：環境變數優先，其次讀 config.yaml，最後用預設值。

    設定檔讀不到時不讓整支腳本壞掉——健康檢查的職責是回報機器人狀態，
    自己因為 PyYAML 沒裝而爆掉只會產生假警報。
    """
    env_path = os.getenv("BFX_DB_PATH")
    if env_path:
        return Path(env_path)

    relative = "data/lending.sqlite3"
    config = load_config_quietly(root)
    if config:
        relative = (config.get("database", {}) or {}).get("path") or relative

    path = Path(relative)
    return path if path.is_absolute() else root / path


def load_config_quietly(root: Path) -> Optional[Dict[str, Any]]:
    """讀 config.yaml，任何失敗都回 None（呼叫端自行退回預設值）。"""
    try:
        import yaml
    except ModuleNotFoundError:
        return None

    config_path = Path(os.getenv("BFX_CONFIG") or (root / "config.yaml"))
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except (OSError, ValueError):
        return None


def main() -> int:
    root = project_root()
    db_path = resolve_db_path(root)
    config = load_config_quietly(root) or {}
    limit_seconds = max_silence_seconds(config.get("engine", {}))

    if not db_path.exists():
        print(f"unhealthy: 找不到資料庫 {db_path}", file=sys.stderr)
        return 1

    try:
        state = read_state(db_path)
    except sqlite3.Error as exc:
        # 唯讀連線碰到需要復原的 WAL 也會走到這裡，代表寫入端已經不正常了。
        print(f"unhealthy: 讀取 {db_path} 失敗：{exc}", file=sys.stderr)
        return 1

    healthy, reason = evaluate(state, limit_seconds)
    if healthy:
        print(f"healthy: {reason}")
        return 0

    print(f"unhealthy: {reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
