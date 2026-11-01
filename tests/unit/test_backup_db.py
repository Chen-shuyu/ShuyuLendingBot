# -*- coding: utf-8 -*-
"""`scripts/backup_db.py`（D076／丙-6）。

釘的重點：**沒驗過的備份等於沒有備份**，以及**壞掉的時候要出聲、不能把舊備份刪掉**。
"""
import gzip
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import backup_db

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 1, 4, 10, tzinfo=CST)


@pytest.fixture
def database(tmp_path):
    """WAL 模式、資料還在 -wal 裡沒寫回主檔——正式環境就是這個樣子。"""
    path = tmp_path / "data" / "lending.sqlite3"
    path.parent.mkdir()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE market_snapshots (id INTEGER PRIMARY KEY, frr REAL)")
    connection.execute("CREATE TABLE bot_kv (key TEXT PRIMARY KEY, value TEXT)")
    connection.executemany("INSERT INTO market_snapshots (frr) VALUES (?)", [(0.0003,)] * 25)
    connection.commit()
    yield str(path)
    connection.close()


def restored_counts(archive, tmp_path):
    restored = tmp_path / "check.sqlite3"
    with gzip.open(archive, "rb") as reader:
        restored.write_bytes(reader.read())
    return backup_db._table_counts(str(restored))


class Test做一次備份:
    def test_備份還原得回來而且資料一筆不少(self, database, tmp_path):
        """🔴 **資料還在 -wal 裡**：用 `cp` 主檔會少資料，這裡要拿得到。"""
        summary = backup_db.run_backup(database, str(tmp_path / "b"), now=NOW)
        assert Path(summary["file"]).name == "lending-20261101.sqlite3.gz"
        assert restored_counts(summary["file"], tmp_path) == {"bot_kv": 0, "market_snapshots": 25}
        assert summary["tables"]["market_snapshots"] == 25
        assert summary["last_ok_at"].startswith("2026-11-01T04:10")

    def test_機器人正在寫也能備份(self, database, tmp_path):
        writer = sqlite3.connect(database)
        writer.execute("INSERT INTO bot_kv VALUES ('k', 'v')")  # 交易開著，還沒 commit
        try:
            summary = backup_db.run_backup(database, str(tmp_path / "b"), now=NOW)
        finally:
            writer.rollback()
            writer.close()
        assert summary["tables"]["market_snapshots"] == 25

    def test_同一天重跑是覆蓋不是多一份(self, database, tmp_path):
        target = tmp_path / "b"
        backup_db.run_backup(database, str(target), now=NOW)
        backup_db.run_backup(database, str(target), now=NOW)
        assert [p.name for p in target.iterdir()] == ["lending-20261101.sqlite3.gz"]

    def test_工作目錄不會留在備份資料夾裡(self, database, tmp_path):
        target = tmp_path / "b"
        backup_db.run_backup(database, str(target), now=NOW)
        assert not [p for p in target.iterdir() if p.name.startswith(".work-")]


class Test只留最新幾份:
    def test_超過就刪最舊的(self, database, tmp_path):
        target = tmp_path / "b"
        for day in range(1, 6):
            backup_db.run_backup(database, str(target), keep=3, now=NOW.replace(day=day))
        assert sorted(p.name for p in target.iterdir()) == [
            "lending-20261103.sqlite3.gz",
            "lending-20261104.sqlite3.gz",
            "lending-20261105.sqlite3.gz",
        ]

    def test_不是備份檔的東西絕對不碰(self, tmp_path):
        """🔴 刪檔的程式要對自己能刪什麼非常確定。"""
        for name in ("lending-20260101.sqlite3.gz", "notes.txt", "lending-latest.sqlite3.gz", "lending.sqlite3"):
            (tmp_path / name).write_text("x")
        removed = backup_db.prune(str(tmp_path), keep=0)
        assert removed == []
        assert (tmp_path / "notes.txt").exists()
        (tmp_path / "lending-20260102.sqlite3.gz").write_text("x")
        assert backup_db.prune(str(tmp_path), keep=1) == ["lending-20260101.sqlite3.gz"]
        assert (tmp_path / "lending-latest.sqlite3.gz").exists()


class Test壞掉的時候:
    def test_找不到資料庫就算失敗(self, tmp_path):
        with pytest.raises(backup_db.BackupError, match="找不到資料庫"):
            backup_db.run_backup(str(tmp_path / "nope.sqlite3"), str(tmp_path / "b"), now=NOW)

    def test_資料庫是壞的就不算成功_舊備份也不會被刪(self, database, tmp_path, monkeypatch):
        """🔴 **舊備份只在新的驗過之後才會被刪**：不然壞資料會把好備份輪掉。"""
        target = tmp_path / "b"
        for day in (1, 2, 3):
            backup_db.run_backup(database, str(target), keep=3, now=NOW.replace(day=day))
        before = sorted(p.name for p in target.iterdir())

        def 驗不過(archive, expected, workdir):
            raise backup_db.BackupError("還原後列數對不上")

        monkeypatch.setattr(backup_db, "verify_restores", 驗不過)
        with pytest.raises(backup_db.BackupError):
            backup_db.run_backup(database, str(target), keep=3, now=NOW.replace(day=4))
        assert sorted(p.name for p in target.iterdir()) == before

    def test_壞掉的壓縮檔驗得出來(self, database, tmp_path):
        bad = tmp_path / "bad.gz"
        bad.write_bytes(b"not a gzip file")
        with pytest.raises(backup_db.BackupError, match="解不開"):
            backup_db.verify_restores(str(bad), {}, str(tmp_path))

    def test_還原後少資料驗得出來(self, database, tmp_path):
        """一個永遠說通過的驗證，跟沒有驗證一樣（對不上時要真的說對不上）。"""
        summary = backup_db.run_backup(database, str(tmp_path / "b"), now=NOW)
        with pytest.raises(backup_db.BackupError, match="列數對不上"):
            backup_db.verify_restores(summary["file"], {"market_snapshots": 999}, str(tmp_path))


class Test主程式:
    @pytest.fixture
    def pushed(self, monkeypatch):
        sent = []
        monkeypatch.setattr(backup_db.notify_failure, "send_line_push", lambda m, level="CRITICAL": sent.append((m, level)) or True)
        return sent

    def test_成功不推LINE但會寫狀態檔(self, database, tmp_path, monkeypatch, pushed):
        monkeypatch.setenv("BFX_DB_PATH", database)
        monkeypatch.setenv("BFX_BACKUP_DIR", str(tmp_path / "b"))
        assert backup_db.main() == 0
        assert pushed == []
        status = json.loads((Path(database).parent / backup_db.STATUS_FILENAME).read_text(encoding="utf-8"))
        assert status["tables"]["market_snapshots"] == 25
        assert status["last_ok_at"]

    def test_失敗要推LINE而且離開碼非零(self, tmp_path, monkeypatch, pushed):
        (tmp_path / "data").mkdir()
        monkeypatch.setenv("BFX_DB_PATH", str(tmp_path / "data" / "nope.sqlite3"))
        monkeypatch.setenv("BFX_BACKUP_DIR", str(tmp_path / "b"))
        assert backup_db.main() == 1
        message, level = pushed[0]
        assert level == "ERROR"
        lines = message.splitlines()
        assert lines[0].endswith("【系統】資料庫備份失敗")
        assert lines[-1] == "——— 需人工介入"
        assert "找不到資料庫" in message

    def test_失敗時不洗掉上次成功的時間(self, database, tmp_path, monkeypatch, pushed):
        """週報靠 `last_ok_at` 判斷備份多舊；失敗一次就洗掉的話會講錯。"""
        monkeypatch.setenv("BFX_DB_PATH", database)
        monkeypatch.setenv("BFX_BACKUP_DIR", str(tmp_path / "b"))
        assert backup_db.main() == 0
        status_path = Path(database).parent / backup_db.STATUS_FILENAME
        ok_at = json.loads(status_path.read_text(encoding="utf-8"))["last_ok_at"]

        monkeypatch.setattr(backup_db, "run_backup", lambda *a, **k: (_ for _ in ()).throw(backup_db.BackupError("磁碟滿了")))
        assert backup_db.main() == 1
        status = json.loads(status_path.read_text(encoding="utf-8"))
        assert status["last_ok_at"] == ok_at
        assert status["last_error"] == "磁碟滿了"
        assert ok_at in pushed[0][0]


class Test排程與部署的設定:
    ROOT = Path(__file__).resolve().parent.parent.parent

    def test_定時器當天沒跑要補跑(self):
        timer = (self.ROOT / "systemd" / "shuyu-lending-bot-backup.timer").read_text(encoding="utf-8")
        assert "OnCalendar=" in timer
        assert "Persistent=true" in timer
        assert "WantedBy=timers.target" in timer

    def test_單元跑的是CI裝上去的那支腳本(self):
        service = (self.ROOT / "systemd" / "shuyu-lending-bot-backup.service").read_text(encoding="utf-8")
        assert "%h/.local/share/shuyu-lending-bot/backup_db.py" in service
        assert "Type=oneshot" in service

    def test_CI真的會安裝並啟用(self):
        """🔴 最糟的失敗方式是「以為接上了、其實沒有」（同 B2）。"""
        workflow = next((self.ROOT / ".github" / "workflows").glob("*.y*ml")).read_text(encoding="utf-8")
        assert "cp scripts/backup_db.py ~/.local/share/shuyu-lending-bot/" in workflow
        assert "shuyu-lending-bot-backup.timer" in workflow
        assert "enable --now shuyu-lending-bot-backup.timer" in workflow
        assert "is-enabled shuyu-lending-bot-backup.timer" in workflow

    def test_備份腳本只用標準函式庫(self):
        """跑在容器外：主機上沒有專案的相依套件（同 `notify_failure.py`）。"""
        import ast

        source = (self.ROOT / "scripts" / "backup_db.py").read_text(encoding="utf-8")
        allowed = {"gzip", "json", "os", "re", "shutil", "sqlite3", "sys", "tempfile", "datetime", "typing", "notify_failure", "scripts"}
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                assert {a.name.split(".")[0] for a in node.names} <= allowed
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] in allowed
