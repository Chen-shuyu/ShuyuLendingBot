# -*- coding: utf-8 -*-
"""載入與管理專案設定。

這裡集中處理 YAML 設定檔的讀取，方便之後擴充環境變數、
設定驗證與預設值邏輯。
"""

import os
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - environment fallback
    yaml = None


def get_default_secrets_path() -> Path:
    """回傳 Linux 主機上常見的 secrets 檔案位置。"""
    return Path.home() / ".config" / "bfx-lending-bot" / "secrets.env"


def load_config(path: str):
    """讀取 YAML 設定檔，並優先使用環境變數中的敏感資訊。"""
    if yaml is None:
        raise RuntimeError("需要安裝 PyYAML，才能讀取設定檔。")

    with open(path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    bitfinex_config = config.setdefault("bitfinex", {})
    bitfinex_config["api_key"] = os.getenv("BFX_API_KEY") or bitfinex_config.get("api_key", "")
    bitfinex_config["api_secret"] = os.getenv("BFX_API_SECRET") or bitfinex_config.get("api_secret", "")

    line_config = config.setdefault("line", {})
    line_config["enabled"] = bool(line_config.get("enabled", False))
    line_config["token"] = os.getenv("LINE_NOTIFY_TOKEN") or line_config.get("token", "")
    line_config["channel"] = os.getenv("LINE_NOTIFY_CHANNEL") or line_config.get("channel", "")

    return config


def resolve_config_path(root_dir: Path) -> Path:
    """根據環境變數或專案根目錄，決定設定檔位置。"""
    config_path = os.getenv("BFX_CONFIG")
    if config_path:
        return Path(config_path)
    return root_dir / "config.yaml"


def load_secrets_from_disk(root_dir: Path) -> None:
    """從 Linux 常見的設定目錄載入 secrets。"""
    secrets_path = os.getenv("BFX_SECRETS_FILE")
    if not secrets_path:
        secrets_path = str(get_default_secrets_path())

    secrets_path_obj = Path(secrets_path)
    if not secrets_path_obj.exists():
        # 若專案目錄下還有舊的 secrets.env，也可兼容讀取
        fallback_path = root_dir / "secrets.env"
        if fallback_path.exists():
            secrets_path_obj = fallback_path
        else:
            return

    with open(secrets_path_obj, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
