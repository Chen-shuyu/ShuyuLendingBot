#!/usr/bin/env bash
# 這個啟動腳本會先載入 secrets，然後再啟動機器人
# 使用方式：bash start.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_FILE="${BFX_SECRETS_FILE:-/home/shuyu/.config/bfx-lending-bot/secrets.env}"
LOG_DIR="$ROOT_DIR/logs"
# 固定檔名，輪替交給程式內的 RotatingFileHandler 處理（見 utils/logger.py）；
# 舊版每次啟動都帶時間戳，重啟多次後 log 檔會無限累積。
LOG_FILE="$LOG_DIR/bfx_lending_bot.log"

mkdir -p "$LOG_DIR"

export BFX_LOG_FILE="$LOG_FILE"

if [ -f "$SECRETS_FILE" ]; then
    # shellcheck disable=SC1090
    source "$SECRETS_FILE"
fi

cd "$ROOT_DIR"
python3 main.py
