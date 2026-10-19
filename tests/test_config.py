"""Тесты для config.py."""

import pytest
from config import Config, ensure_config, load_config, get_config


@pytest.fixture(autouse=True)
def isolate_app_dir(tmp_path, monkeypatch):
    """Изолируем get_app_dir от реальной папки приложения."""
    fake_app_dir = tmp_path / "app"
    fake_app_dir.mkdir()
    monkeypatch.setattr("config.get_app_dir", lambda: fake_app_dir)
    get_config.cache_clear()
    yield fake_app_dir
    get_config.cache_clear()


class TestConfigValidation:
    def test_valid_minimal(self):
        c = Config(shared_folder="share", backup_folder="backup")
        assert c.log_level == "INFO"
        assert c.max_accounts == 3
        assert c.session_ttl == 86400
        assert c.theme == "dark"

    def test_empty_shared_folder(self):
        with pytest.raises(ValueError, match="SHARED_FOLDER"):
            Config(shared_folder="", backup_folder="backup")

    def test_whitespace_shared_folder(self):
        with pytest.raises(ValueError, match="SHARED_FOLDER"):
            Config(shared_folder="   ", backup_folder="backup")

    def test_empty_backup_folder(self):
        with pytest.raises(ValueError, match="BACKUP_FOLDER"):
            Config(shared_folder="share", backup_folder="")

    def test_invalid_log_level(self):
        with pytest.raises(ValueError, match="LOG_LEVEL"):
            Config(shared_folder="s", backup_folder="b", log_level="VERBOSE")

    def test_log_level_normalized(self):
        c = Config(shared_folder="s", backup_folder="b", log_level="debug")
        assert c.log_level == "DEBUG"

    def test_max_accounts_zero(self):
        with pytest.raises(ValueError, match="MAX_ACCOUNTS"):
            Config(shared_folder="s", backup_folder="b", max_accounts=0)

    def test_max_accounts_negative(self):
        with pytest.raises(ValueError, match="MAX_ACCOUNTS"):
            Config(shared_folder="s", backup_folder="b", max_accounts=-1)

    def test_session_ttl_zero(self):
        with pytest.raises(ValueError, match="SESSION_TTL"):
            Config(shared_folder="s", backup_folder="b", session_ttl=0)

    def test_invalid_theme(self):
        with pytest.raises(ValueError, match="THEME"):
            Config(shared_folder="s", backup_folder="b", theme="solarized")


class TestLoadConfig:
    def test_env_missing(self, isolate_app_dir):
        with pytest.raises(FileNotFoundError, match=".env"):
            load_config()

    def test_env_valid(self, isolate_app_dir):
        (isolate_app_dir / ".env").write_text(
            "SHARED_FOLDER=share\n"
            "BACKUP_FOLDER=backup\n"
            "LOG_LEVEL=DEBUG\n"
            "MAX_ACCOUNTS=5\n"
            "SESSION_TTL=3600\n"
            "THEME=light\n",
            encoding="utf-8",
        )
        c = load_config()
        assert c.shared_folder == "share"
        assert c.backup_folder == "backup"
        assert c.log_level == "DEBUG"
        assert c.max_accounts == 5
        assert c.session_ttl == 3600
        assert c.theme == "light"

    def test_env_invalid_int(self, isolate_app_dir):
        (isolate_app_dir / ".env").write_text(
            "SHARED_FOLDER=s\nBACKUP_FOLDER=b\nMAX_ACCOUNTS=abc\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="MAX_ACCOUNTS"):
            load_config()

    def test_get_config_caches(self, isolate_app_dir):
        (isolate_app_dir / ".env").write_text(
            "SHARED_FOLDER=s\nBACKUP_FOLDER=b\n",
            encoding="utf-8",
        )
        get_config.cache_clear()
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2


class TestEnsureConfig:
    def test_creates_file(self, isolate_app_dir):
        path = ensure_config("/tmp/share")
        assert path.exists()
        assert path == isolate_app_dir / ".env"
        content = path.read_text(encoding="utf-8")
        assert "SHARED_FOLDER=/tmp/share" in content
        assert "BACKUP_FOLDER=" in content

    def test_creates_loadable(self, isolate_app_dir):
        ensure_config("/tmp/share")
        c = load_config()
        assert c.shared_folder == "/tmp/share"
        assert c.log_level == "INFO"

    def test_raises_if_exists(self, isolate_app_dir):
        ensure_config("/tmp/share")
        with pytest.raises(FileExistsError, match=".env"):
            ensure_config("/tmp/other")

    def test_empty_folder_raises(self, isolate_app_dir):
        with pytest.raises(ValueError, match="shared_folder"):
            ensure_config("")