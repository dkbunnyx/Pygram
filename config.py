"""Конфигурация Pygram: загрузка и валидация настроек из .env."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv.main import load_dotenv


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


def load_config() -> Config:
    """Загружает .env и возвращает объект Config.

    Raises:
        FileNotFoundError: если .env не найден.
        ValueError: если значения в .env некорректны.
    """
    env_path = Path(".env")
    if not env_path.exists():
        raise FileNotFoundError(
            "Файл .env не найден. Скопируйте .env.example в .env "
            "и заполните значения."
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