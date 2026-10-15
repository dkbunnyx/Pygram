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