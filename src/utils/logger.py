"""Логирование Pygram через loguru.

Настройка вызывается один раз из main.py через setup_logging().
"""

import sys
from pathlib import Path

from loguru import logger

from src.constants import get_app_dir


# Формат для консоли: с цветами, короткий
_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
    "<level>{message}</level>"
)

# Формат для файла: без цветов, с полным именем модуля
_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | "
    "{level: <8} | "
    "{name}:{function}:{line} — "
    "{message}"
)


def setup_logging(level: str = "INFO") -> None:
    """Настраивает loguru: консоль + файл.

    Безопасно для PyInstaller --noconsole: если sys.stderr is None,
    консольный sink не добавляется.

    Args:
        level: Минимальный уровень логирования (DEBUG/INFO/...).
    """
    logger.remove()

    # Консоль — только если stderr существует (PyInstaller --noconsole)
    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            level=level.upper(),
            format=_CONSOLE_FORMAT,
            colorize=True,
        )

    # Файл — всегда. Логи рядом с приложением, а не в CWD.
    log_dir = get_app_dir() / "logs"
    log_dir.mkdir(exist_ok=True)

    logger.add(
        log_dir / "pygram.log",
        level=level.upper(),
        format=_FILE_FORMAT,
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
    )