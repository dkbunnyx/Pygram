"""Конфигурация Pygram: загрузка и валидация настроек из .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv.main import load_dotenv

from src.constants import get_app_dir


@dataclass
class Config:
    shared_folder: str
    backup_folder: str
    log_level: str = "INFO"
    max_accounts: int = 3
    session_ttl: int = 86400
    theme: str = "dark"

    def __post_init__(self) -> None:
        """Проверяет корректность значений после инициализации."""
        if not self.shared_folder or not self.shared_folder.strip():
            raise ValueError("SHARED_FOLDER не может быть пустым")
        if not self.backup_folder or not self.backup_folder.strip():
            raise ValueError("BACKUP_FOLDER не может быть пустым")

        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level.upper() not in valid_levels:
            raise ValueError(
                f"LOG_LEVEL должен быть одним из {valid_levels}, "
                f"получено: {self.log_level}"
            )
        self.log_level = self.log_level.upper()

        if self.max_accounts < 1:
            raise ValueError("MAX_ACCOUNTS должен быть >= 1")
        if self.session_ttl <= 0:
            raise ValueError("SESSION_TTL должен быть > 0")
        if self.theme not in {"dark", "light"}:
            raise ValueError(
                f"THEME должен быть 'dark' или 'light', получено: {self.theme}"
            )


def _env_path() -> Path:
    """Путь к .env: в папке приложения (dev — корень проекта, .exe — %APPDATA%\\Pygram)."""
    return get_app_dir() / ".env"


def ensure_config(shared_folder: str) -> Path:
    """Создаёт .env с дефолтами при первом запуске.

    Args:
        shared_folder: Путь к папке шары (выбран пользователем в диалоге).

    Returns:
        Path: Путь к созданному .env.

    Raises:
        FileExistsError: если .env уже существует (не перезаписываем).
        ValueError: если shared_folder пустой.
    """
    if not shared_folder or not shared_folder.strip():
        raise ValueError("shared_folder не может быть пустым")

    env_path = _env_path()
    if env_path.exists():
        raise FileExistsError(f".env уже существует: {env_path}")

    backup_folder = str(get_app_dir() / "backups")
    content = (
        f"# Pygram config (создан автоматически при первом запуске)\n"
        f"SHARED_FOLDER={shared_folder}\n"
        f"BACKUP_FOLDER={backup_folder}\n"
        f"LOG_LEVEL=INFO\n"
        f"MAX_ACCOUNTS=3\n"
        f"SESSION_TTL=86400\n"
        f"THEME=dark\n"
    )
    env_path.write_text(content, encoding="utf-8")
    return env_path


def load_config() -> Config:
    """Загружает .env и возвращает объект Config.

    Raises:
        FileNotFoundError: если .env не найден (вызови ensure_config() сначала).
        ValueError: если значения в .env некорректны.
    """
    env_path = _env_path()
    if not env_path.exists():
        raise FileNotFoundError(
            f"Файл .env не найден: {env_path}. "
            f"Вызови ensure_config() для создания."
        )

    load_dotenv(env_path)

    def _get_int(key: str, default: int) -> int:
        raw = os.getenv(key)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except ValueError as e:
            raise ValueError(
                f"{key} должен быть целым числом, получено: {raw!r}"
            ) from e

    return Config(
        shared_folder=os.getenv("SHARED_FOLDER", ""),
        backup_folder=os.getenv("BACKUP_FOLDER", ""),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        max_accounts=_get_int("MAX_ACCOUNTS", 3),
        session_ttl=_get_int("SESSION_TTL", 86400),
        theme=os.getenv("THEME", "dark"),
    )


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()