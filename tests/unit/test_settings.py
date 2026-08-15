# -*- coding: utf-8 -*-
"""`config/settings.py` 的單元測試。

設定載入錯了會直接影響實盤：金鑰讀不到會變成沒授權的呼叫，secrets 解析錯
則可能讓錯的金鑰進到環境變數。這一層完全不需要網路就能測完。
"""

import pytest

from config.settings import (
    get_default_secrets_path,
    load_config,
    load_secrets_from_disk,
    resolve_config_path,
)

SAMPLE_YAML = """
bitfinex:
  api_key: "file-key"
  api_secret: "file-secret"
  dry_run_balance_usd: 344.12

strategy:
  min_required_usd: 150

line:
  enabled: true
  token: "file-token"
  to_user_id: "file-user-id"
"""


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE_YAML, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """設定相關的環境變數在每個測試開始前一律清空，避免受本機環境影響。"""
    for name in (
        "BFX_API_KEY",
        "BFX_API_SECRET",
        "BFX_CONFIG",
        "BFX_SECRETS_FILE",
        "LINE_CHANNEL_ACCESS_TOKEN",
        "LINE_TO_USER_ID",
    ):
        monkeypatch.delenv(name, raising=False)


class TestLoadConfig:
    def test_reads_yaml_sections(self, config_file):
        config = load_config(str(config_file))
        assert config["strategy"]["min_required_usd"] == 150
        assert config["bitfinex"]["dry_run_balance_usd"] == 344.12

    def test_file_values_used_when_env_absent(self, config_file):
        config = load_config(str(config_file))
        assert config["bitfinex"]["api_key"] == "file-key"
        assert config["bitfinex"]["api_secret"] == "file-secret"

    def test_env_overrides_file_credentials(self, config_file, monkeypatch):
        """容器部署靠環境變數注入金鑰，必須蓋過設定檔裡的值。"""
        monkeypatch.setenv("BFX_API_KEY", "env-key")
        monkeypatch.setenv("BFX_API_SECRET", "env-secret")
        config = load_config(str(config_file))
        assert config["bitfinex"]["api_key"] == "env-key"
        assert config["bitfinex"]["api_secret"] == "env-secret"

    def test_empty_env_does_not_override(self, config_file, monkeypatch):
        """空字串視同沒設定，不能把設定檔裡的金鑰清成空的。"""
        monkeypatch.setenv("BFX_API_KEY", "")
        assert load_config(str(config_file))["bitfinex"]["api_key"] == "file-key"

    def test_missing_sections_get_defaults(self, tmp_path):
        path = tmp_path / "bare.yaml"
        path.write_text("strategy:\n  min_required_usd: 200\n", encoding="utf-8")
        config = load_config(str(path))
        assert config["bitfinex"]["api_key"] == ""
        assert config["line"]["enabled"] is False

    def test_empty_yaml_still_returns_dict(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        config = load_config(str(path))
        assert config["bitfinex"] == {"api_key": "", "api_secret": ""}

    def test_line_enabled_is_coerced_to_bool(self, config_file):
        assert load_config(str(config_file))["line"]["enabled"] is True

    def test_line_env_overrides_file(self, config_file, monkeypatch):
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "env-token")
        monkeypatch.setenv("LINE_TO_USER_ID", "U-env")
        config = load_config(str(config_file))
        assert config["line"]["token"] == "env-token"
        assert config["line"]["to_user_id"] == "U-env"

    def test_old_line_notify_names_are_not_honoured(self, config_file, monkeypatch):
        """LINE Notify 已於 2025-03 停用，舊變數名刻意不做向後相容。

        留著舊名只會讓人以為設了就有用，而舊 token 對新端點必定是 401。
        """
        monkeypatch.setenv("LINE_NOTIFY_TOKEN", "old-token")
        config = load_config(str(config_file))
        assert config["line"]["token"] == "file-token"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "not-here.yaml"))


class TestResolveConfigPath:
    def test_defaults_to_project_root(self, tmp_path):
        assert resolve_config_path(tmp_path) == tmp_path / "config.yaml"

    def test_env_takes_precedence(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BFX_CONFIG", "/etc/bot/config.yaml")
        assert str(resolve_config_path(tmp_path)) == "/etc/bot/config.yaml"


class TestLoadSecrets:
    def test_parses_key_value_pairs(self, tmp_path, monkeypatch):
        secrets = tmp_path / "secrets.env"
        secrets.write_text("BFX_API_KEY=abc123\nBFX_API_SECRET=def456\n", encoding="utf-8")
        monkeypatch.setenv("BFX_SECRETS_FILE", str(secrets))

        load_secrets_from_disk(tmp_path)
        import os

        assert os.environ["BFX_API_KEY"] == "abc123"
        assert os.environ["BFX_API_SECRET"] == "def456"

    def test_handles_export_prefix_quotes_comments_and_blanks(self, tmp_path, monkeypatch):
        secrets = tmp_path / "secrets.env"
        secrets.write_text(
            "\n"
            "# 這是註解\n"
            'export BFX_API_KEY="quoted-key"\n'
            "BFX_API_SECRET='single-quoted'\n"
            "這行沒有等號所以要被略過\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("BFX_SECRETS_FILE", str(secrets))

        load_secrets_from_disk(tmp_path)
        import os

        assert os.environ["BFX_API_KEY"] == "quoted-key"
        assert os.environ["BFX_API_SECRET"] == "single-quoted"

    def test_does_not_override_existing_env(self, tmp_path, monkeypatch):
        """已由容器或 systemd 注入的值優先，檔案只是補漏（用的是 setdefault）。"""
        secrets = tmp_path / "secrets.env"
        secrets.write_text("BFX_API_KEY=from-file\n", encoding="utf-8")
        monkeypatch.setenv("BFX_SECRETS_FILE", str(secrets))
        monkeypatch.setenv("BFX_API_KEY", "already-set")

        load_secrets_from_disk(tmp_path)
        import os

        assert os.environ["BFX_API_KEY"] == "already-set"

    def test_falls_back_to_project_root_secrets(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BFX_SECRETS_FILE", str(tmp_path / "does-not-exist.env"))
        (tmp_path / "secrets.env").write_text("BFX_API_KEY=fallback\n", encoding="utf-8")

        load_secrets_from_disk(tmp_path)
        import os

        assert os.environ["BFX_API_KEY"] == "fallback"

    def test_silently_returns_when_nothing_found(self, tmp_path, monkeypatch):
        """找不到 secrets 不該讓機器人起不來——金鑰也可能純粹由環境變數提供。"""
        monkeypatch.setenv("BFX_SECRETS_FILE", str(tmp_path / "nope.env"))
        load_secrets_from_disk(tmp_path)  # 不應拋出例外


class TestDefaultSecretsPath:
    def test_points_at_user_config_dir(self):
        path = get_default_secrets_path()
        assert path.name == "secrets.env"
        assert path.parent.name == "bfx-lending-bot"
