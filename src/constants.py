"""Глобальные константы Pygram."""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "Pygram"


def get_app_dir() -> Path:
    """Возвращает папку приложения для конфига, логов, бэкапов.

    - В dev (не frozen): корень проекта (рядом с config.py).
    - В .exe (frozen): %APPDATA%\\Pygram (Windows) или ~/.config/Pygram (Linux/macOS).
      Причина: рядом с .exe может быть Program Files (без прав на запись)
      или пользователь запускает из архива. %APPDATA% всегда доступен.

    Папка создаётся, если её нет.

    Returns:
        Path: Существующая папка приложения.
    """
    if getattr(sys, "frozen", False):
        # Собранный .exe
        appdata = os.getenv("APPDATA")
        if appdata:
            app_dir = Path(appdata) / APP_NAME
        else:
            # Linux/macOS fallback (XDG)
            app_dir = Path.home() / ".config" / APP_NAME
    else:
        # Dev-режим: корень проекта (src/constants.py → src → корень)
        app_dir = Path(__file__).resolve().parent.parent

    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir