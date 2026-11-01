# -*- coding: utf-8 -*-
"""正式資料庫的每日備份（D076／丙-6）。由 `shuyu-lending-bot-backup.timer` 觸發，跑在容器外。

**為什麼要有它**：`market_snapshots`、`pricing_decisions`、`repost_comparisons` 重抓不回來，
而那正是 D036 說不能丟的資料。2026-11-01 查到這台機器上沒有任何副本。

**放哪裡**：DB 在 `/workspace`（`sda`），備份預設放家目錄（NVMe）。**防得了單顆硬碟損壞，
防不了整台機器出事**（D076 第四節）。

**為什麼跟告警腳本一樣只用標準函式庫**：跑在容器外，而且要在機器人壞掉時也能跑（見 `notify_failure.py`）。
推 LINE 直接用那支的函式——兩支部署在同一個目錄，不必再抄一份。

**每一次都驗還原**：沒驗過的備份等於沒有備份。流程是
複製 → 查完整性 → 壓縮 → 解壓回來再查一次（比對每張表的列數）→ 才換掉舊檔。
驗不過就不算成功：不覆蓋、不刪舊備份、推一則 LINE、離開碼 1。

**成功不推 LINE**（額度，D024），但會寫 `backup_status.json` 到 DB 旁邊：
週報讀它，超過 48 小時就喊（D076 第二節）——**定時器自己沒跑的時候，這是唯一會出聲的地方**。

用法：

    python3 scripts/backup_db.py
    BFX_DB_PATH=/path/to/lending.sqlite3 BFX_BACKUP_DIR=/path/to/backups python3 scripts/backup_db.py
"""

import gzip
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from typing import Dict, List, Optional

try:
    import notify_failure  # 主機端：兩支裝在同一個目錄
except ImportError:  # pragma: no cover - repo 裡跑（測試、手動）的時候
    from scripts import notify_failure

DEFAULT_DB = "/workspace/deploy/active-bots/ShuyuLendingBot/data/lending.sqlite3"
DEFAULT_DIR = "~/.local/share/shuyu-lending-bot/backups"
DEFAULT_KEEP = 30
STATUS_FILENAME = "backup_status.json"

# **只動符合這個檔名的檔案**：刪檔的程式要對自己能刪什麼非常確定。
BACKUP_NAME = re.compile(r"^lending-\d{8}\.sqlite3\.gz$")


class BackupError(Exception):
    """備份沒有成功（複製、驗證、壓縮任一步）。訊息要能直接放進 LINE。"""


def _table_counts(path: str) -> Dict[str, int]:
    """每張表的列數，同時也是「這個檔真的打得開、讀得動」的證明。"""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in sorted(names)
        }
    finally:
        connection.close()


def _integrity_check(path: str) -> None:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if result != "ok":
        raise BackupError(f"完整性檢查沒過：{result}")


def copy_database(source: str, destination: str) -> None:
    """用 SQLite 的 backup API 複製。**不能 `cp`**：機器人正在寫，而且資料還在 `-wal` 裡。"""
    if not os.path.exists(source):
        raise BackupError(f"找不到資料庫：{source}")
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=60)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    except sqlite3.Error as exc:
        raise BackupError(f"複製失敗：{exc}") from exc
    finally:
        dst.close()
        src.close()


def compress(source: str, destination: str) -> None:
    with open(source, "rb") as reader, gzip.open(destination, "wb", compresslevel=6) as writer:
        shutil.copyfileobj(reader, writer)


def verify_restores(archive: str, expected: Dict[str, int], workdir: str) -> None:
    """解壓回來再查一次。**比的是列數，不只是打得開**：少一張表也是壞的。"""
    restored = os.path.join(workdir, "restored.sqlite3")
    try:
        with gzip.open(archive, "rb") as reader, open(restored, "wb") as writer:
            shutil.copyfileobj(reader, writer)
    except OSError as exc:
        raise BackupError(f"壓縮檔解不開：{exc}") from exc
    _integrity_check(restored)
    got = _table_counts(restored)
    if got != expected:
        raise BackupError(f"還原後列數對不上：{got} 對 {expected}")


def prune(backup_dir: str, keep: int) -> List[str]:
    """只留最新的 `keep` 份，回傳刪掉的檔名。檔名含日期，排序就是時間順序。"""
    names = sorted(name for name in os.listdir(backup_dir) if BACKUP_NAME.match(name))
    stale = names[:-keep] if keep > 0 else []
    for name in stale:
        os.remove(os.path.join(backup_dir, name))
    return stale


def write_status(path: str, status: Dict) -> bool:
    """寫週報要讀的狀態檔。**寫不出來不算備份失敗**（備份本身是好的），但要回報。"""
    temp = f"{path}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(status, handle, ensure_ascii=False, indent=2)
        os.replace(temp, path)
        return True
    except OSError:
        return False


def read_status(path: str) -> Dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def run_backup(source: str, backup_dir: str, keep: int = DEFAULT_KEEP, now: Optional[datetime] = None) -> Dict:
    """做一次備份。成功回傳摘要，失敗丟 `BackupError`。**舊備份只在新的驗過之後才會被刪。**"""
    now = now or datetime.now(notify_failure.resolve_timezone())
    os.makedirs(backup_dir, exist_ok=True)
    final = os.path.join(backup_dir, f"lending-{now:%Y%m%d}.sqlite3.gz")
    with tempfile.TemporaryDirectory(dir=backup_dir, prefix=".work-") as workdir:
        copied = os.path.join(workdir, "copy.sqlite3")
        copy_database(source, copied)
        _integrity_check(copied)
        counts = _table_counts(copied)
        if not counts:
            raise BackupError("複製出來的資料庫沒有任何資料表")
        archive = os.path.join(workdir, "copy.sqlite3.gz")
        compress(copied, archive)
        verify_restores(archive, counts, workdir)
        os.replace(archive, final)
    removed = prune(backup_dir, keep)
    return {
        "last_ok_at": now.isoformat(timespec="seconds"),
        "file": final,
        "size_bytes": os.path.getsize(final),
        "tables": counts,
        "removed": removed,
    }


def build_failure_message(reason: str, last_ok_at: Optional[str]) -> str:
    """失敗訊息，三段式（格式規格在 `notify/messages.py`，同 `notify_failure.py` 各自實作）。"""
    icon = notify_failure.PUSH_ABNORMAL_ICONS["ERROR"]
    lines = [
        f"{icon}【{notify_failure.PUSH_CATEGORY_SYSTEM}】資料庫備份失敗",
        f"時間：{notify_failure.push_timestamp()}",
        f"原因：{reason}",
        f"上次成功：{last_ok_at or '從來沒有'}",
        "影響：掛單不受影響，但這份資料目前沒有新的副本",
        notify_failure.PUSH_FOOTER_ACTION_REQUIRED,
    ]
    return "\n".join(lines)


def main() -> int:
    source = os.getenv("BFX_DB_PATH") or DEFAULT_DB
    backup_dir = os.path.expanduser(os.getenv("BFX_BACKUP_DIR") or DEFAULT_DIR)
    keep = int(os.getenv("BFX_BACKUP_KEEP") or DEFAULT_KEEP)
    status_path = os.path.join(os.path.dirname(source), STATUS_FILENAME)
    previous = read_status(status_path)

    try:
        summary = run_backup(source, backup_dir, keep)
    except (BackupError, OSError, sqlite3.Error) as exc:
        reason = str(exc) or type(exc).__name__
        print(f"備份失敗：{reason}", file=sys.stderr)
        write_status(
            status_path,
            {**previous, "last_error": reason, "last_error_at": notify_failure.push_timestamp()},
        )
        notify_failure.send_line_push(
            build_failure_message(reason, previous.get("last_ok_at")), level="ERROR"
        )
        return 1

    if not write_status(status_path, summary):
        # 備份是好的，所以不算失敗；但週報會以為很久沒備份，要留下痕跡。
        print(f"⚠ 備份成功，但寫不出狀態檔：{status_path}", file=sys.stderr)
    print(
        f"備份完成：{summary['file']}（{summary['size_bytes'] / 1e6:.1f} MB），"
        f"market_snapshots {summary['tables'].get('market_snapshots', 0)} 列；"
        f"刪掉舊備份 {len(summary['removed'])} 份"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
