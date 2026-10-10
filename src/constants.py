"""Константы и пути Pygram."""
import sys
from pathlib import Path


def get_app_dir() -> Path:
    """Возвращает корень приложения (.exe или корень проекта)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent