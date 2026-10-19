"""Пользователи Pygram: регистрация, логин, сессии.

Схема:
    - register_user() создаёт identity + если первый — делает админом.
    - login_user() аутентифицирует и возвращает User (с priv_pem в памяти).
    - Сессия хранится локально в %USERPROFILE%\\.pygram\\.session_<fp16>.
    - Приватный ключ НЕ хранится в сессии (только в памяти).

Формат .session_<fp16>:
    {"login": "...", "fp16": "...", "created_at": ..., "expires_at": ...,
     "boot_marker": ...}
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from config import get_config
from src.core.admin import has_any_admin, is_admin, make_admin
from src.core.identity import (
    authenticate,
    register_identity,
)
from src.os_integration.win import get_local_dir
from src.storage.shared_store import (
    load_login_marker,
    load_pub_key,
)


# ============================================================================
# Модель
# ============================================================================

@dataclass
class User:
    """Активный пользователь (в памяти, пока приложение работает)."""
    login: str
    fp16: str
    priv_pem: str
    pub_pem: str
    is_admin: bool
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))

    @property
    def role(self) -> str:
        return "admin" if self.is_admin else "user"


# ============================================================================
# Регистрация
# ============================================================================

def register_user(
        shared_folder: Path | str,
        login: str,
        password: str,
) -> User:
    """Регистрирует нового пользователя.

    Если это первый пользователь — делает его админом.

    Raises:
        FileExistsError: логин занят.
        ValueError: параметры некорректны.
    """
    fp16 = register_identity(shared_folder, login, password)

    # Первый пользователь — админ
    if not has_any_admin(shared_folder):
        make_admin(shared_folder, fp16, by="system")
        logger.info(f"Первый пользователь {login} назначен админом")

    full_fp = load_login_marker(shared_folder, login)["fp"]
    pub_pem = load_pub_key(shared_folder, full_fp)

    user = User(
        login=login,
        fp16=fp16,
        priv_pem="",  # при регистрации не расшифровываем
        pub_pem=pub_pem,
        is_admin=is_admin(shared_folder, fp16),
    )
    _save_session(user)
    return user


# ============================================================================
# Логин
# ============================================================================

def login_user(
        shared_folder: Path | str,
        login: str,
        password: str,
) -> User:
    """Логинит пользователя.

    Raises:
        FileNotFoundError: логин не найден.
        ValueError: неверный пароль.
    """
    priv_pem, fp16 = authenticate(shared_folder, login, password)
    full_fp = load_login_marker(shared_folder, login)["fp"]
    pub_pem = load_pub_key(shared_folder, full_fp)

    user = User(
        login=login,
        fp16=fp16,
        priv_pem=priv_pem,
        pub_pem=pub_pem,
        is_admin=is_admin(shared_folder, fp16),
    )
    _save_session(user)
    logger.info(f"Пользователь вошёл: {login} (fp16={fp16})")
    return user


# ============================================================================
# Сессия
# ============================================================================

def _session_path(fp16: str) -> Path:
    """Путь к локальному .session_<fp16>."""
    return get_local_dir() / f".session_{fp16}"


def _get_ttl() -> int:
    """TTL сессии из конфига. Fallback — 86400 (24 часа)."""
    try:
        return get_config().session_ttl
    except (FileNotFoundError, ValueError, ImportError):
        return 86400


def _save_session(user: User) -> None:
    """Сохраняет метаданные сессии локально. Приватный ключ НЕ пишется."""
    now = int(time.time() * 1000)
    ttl = _get_ttl()
    data = {
        "login": user.login,
        "fp16": user.fp16,
        "created_at": now,
        "expires_at": now + ttl * 1000,
        "boot_marker": _get_boot_marker(),
    }
    path = _session_path(user.fp16)
    path.write_text(json.dumps(data), encoding="utf-8")
    logger.debug(f"Сессия сохранена: {path}")


def _get_boot_marker() -> int:
    """Монотонный маркер времени (ms). Не зависит от ОС.

    Используется для инвалидации сессии при перезагрузке ПК.
    time.monotonic() сбрасывается при перезагрузке системы.
    """
    return int(time.monotonic() * 1000)


def logout_user(user: User) -> None:
    """Удаляет локальную сессию пользователя."""
    path = _session_path(user.fp16)
    if path.is_file():
        path.unlink()
    logger.info(f"Пользователь вышел: {user.login}")


def load_saved_session(fp16: str) -> dict | None:
    """Читает локальную сессию, если она валидна.

    Returns:
        dict с login, fp16 или None, если сессии нет / истекла / boot-marker не совпал.
    """
    path = _session_path(fp16)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    now = int(time.time() * 1000)
    if data.get("expires_at", 0) < now:
        logger.debug(f"Сессия истекла: {fp16}")
        path.unlink(missing_ok=True)
        return None

    # boot_marker от monotonic: если ПК перезагружался, monotonic меньше.
    # Но абсолютное значение не сравнимо с сохранённым после перезагрузки.
    # Поэтому проверяем только «не стал ли маркер меньше».
    saved = data.get("boot_marker", 0)
    current = _get_boot_marker()
    if saved and current < saved:
        logger.debug(f"Boot-marker сброшен (перезагрузка?): {fp16}")
        path.unlink(missing_ok=True)
        return None

    return data


def list_saved_sessions() -> list[dict]:
    """Возвращает список сохранённых (валидных) сессий для UI логина."""
    local_dir = get_local_dir()
    result = []
    for entry in local_dir.iterdir():
        if not entry.is_file():
            continue
        if not entry.name.startswith(".session_"):
            continue
        fp16 = entry.name[len(".session_"):]
        data = load_saved_session(fp16)
        if data:
            result.append(data)
    return result
