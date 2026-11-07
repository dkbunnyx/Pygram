# tests/conftest.py
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Изолирует os.environ от реального окружения системы.

    Автоматически применяется ко всем тестам. Удаляет переменные,
    которые config.py читает из .env.
    """
    for key in [
        "SHARED_FOLDER", "BACKUP_FOLDER",
        "LOG_LEVEL", "MAX_ACCOUNTS", "SESSION_TTL", "THEME",
    ]:
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture(autouse=True)
def isolate_pygram_trust_storage(tmp_path, monkeypatch):
    """Каждый тест получает отдельное локальное хранилище root fingerprint."""
    local = tmp_path / "pygram_local"
    local.mkdir()
    monkeypatch.setattr("src.core.trust.get_local_dir", lambda: local)
    yield local


def bootstrap_super_admin(shared, login, password):
    """Создаёт тестового первого супер-администратора с локальным pin."""
    from src.core.admin import make_admin
    from src.core.identity import authenticate, register_identity
    from src.core.trust import pin_initial_root

    fp16 = register_identity(shared, login, password)
    priv_pem, authenticated_fp16 = authenticate(shared, login, password)
    if authenticated_fp16 != fp16:
        raise AssertionError("Fingerprint changed during test bootstrap")
    make_admin(
        shared,
        fp16,
        by=fp16,
        by_priv=priv_pem,
        bootstrap=True,
    )
    pin_initial_root(shared, fp16)
    return fp16, priv_pem
