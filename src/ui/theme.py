"""Управление темами оформления Pygram."""

from pathlib import Path
from loguru import logger


def load_theme(app, theme_name: str = "base"):
    """Загружает QSS-файл и применяет его ко всему приложению."""
    try:
        if theme_name == "custom":
            theme_name = "base"

        theme_path = Path(__file__).parent / "themes" / f"{theme_name}.qss"

        if theme_path.exists():
            qss = theme_path.read_text(encoding="utf-8")
            app.setStyleSheet(qss)
            logger.info(f"Тема загружена: {theme_name}")
        else:
            logger.warning(f"Файл темы не найден: {theme_path}")
    except Exception as e:
        logger.error(f"Ошибка загрузки темы: {e}")