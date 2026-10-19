"""Локальные пути Pygram (бывшая Windows-интеграция).

После отказа от DPAPI этот модуль отвечает только за путь к папке
локальных файлов пользователя (UI-настройки, .session, logs, pygram.db).

Вся критичная информация (ключи, пароли, сообщения) хранится в сетевой
папке (SHARED_FOLDER) и защищена Argon2id + AES-GCM + RSA.
"""

from __future__ import annotations

from pathlib import Path


LOCAL_DIR_NAME = ".pygram"


def get_local_dir() -> Path:
    """Возвращает папку для локальных файлов пользователя.

    Windows: %USERPROFILE%\\.pygram\\
    Linux/macOS: ~/.pygram/  (на будущее)

    Папка создаётся, если её нет.

    Returns:
        Path: Существующая папка.
    """
    local_dir = Path.home() / LOCAL_DIR_NAME
    local_dir.mkdir(parents=True, exist_ok=True)
    return local_dir


def is_windows() -> bool:
    """True, если мы на Windows. Оставлено для совместимости."""
    import sys
    return sys.platform.startswith("win")