"""Пользователи Pygram: регистрация, логин, сессии."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil
from loguru import logger

from config import get_config
from src.core.admin import has_any_admin, is_admin, make_admin
from src.core.identity import authenticate, register_identity
from src.os_integration.win import get_local_dir
from src.storage.local_db import get_db
from src.storage.shared_store import load_login_marker, load_pub_key


@dataclass
class User:
    login: str
    fp16: str
    priv_pem: str
    pub_pem: str
    is_admin: bool
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))

    @property
    def role(self) -> str:
        return "admin" if self.is_admin else "user"


def register_user(shared_folder: Path | str, login: str, password: str) -> User:
    fp16 = register_identity(shared_folder, login, password)

    if not has_any_admin(shared_folder):
        make_admin(shared_folder, fp16, by="system")
        logger.info(f"Первый пользователь {login} назначен супер-админом")

    # --- СОЗДАЕМ ИЗБРАННОЕ ---
    from src.core.chat_logic import create_favorites
    try:
        create_favorites(shared_folder, login)
        logger.info(f"Для пользователя {login} создано Избранное")
    except Exception as e:
        logger.error(f"Не удалось создать Избранное: {e}")
    # --------------------------

    # Сразу логиним пользователя, чтобы получить приватный ключ в память
    user = login_user(shared_folder, login, password)

    return user


def login_user(shared_folder: Path | str, login: str, password: str) -> User:
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

    # Сохраняем в локальную БД для отображения имен
    get_db().save_user_map(user.fp16, user.login)

    logger.info(f"Пользователь вошёл: {login} (fp16={fp16})")
    return user


def _session_path(fp16: str) -> Path:
    return get_local_dir() / f".session_{fp16}"

def _get_ttl() -> int:
    try:
        return get_config().session_ttl
    except (FileNotFoundError, ValueError, ImportError):
        return 86400

def _save_session(user: User) -> None:
    now = int(time.time() * 1000)
    ttl = _get_ttl()
    data = {
        "login": user.login,
        "fp16": user.fp16,
        "created_at": now,
        "expires_at": now + ttl * 1000,
        "boot_time": int(psutil.boot_time()),
        "last_login": now,  # <--- ДОБАВИЛИ ЭТО
    }
    path = _session_path(user.fp16)
    path.write_text(json.dumps(data), encoding="utf-8")
    logger.debug(f"Сессия сохранена: {path}")

def logout_user(user: User) -> None:
    p = _session_path(user.fp16)
    if p.is_file(): p.unlink()
    logger.info(f"Пользователь вышел: {user.login}")

def load_saved_session(fp16: str) -> dict | None:
    path = _session_path(fp16)
    if not path.is_file(): return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if data.get("expires_at", 0) < int(time.time() * 1000):
        path.unlink(missing_ok=True)
        return None

    # Проверка на перезагрузку
    if data.get("boot_time", 0) != int(psutil.boot_time()):
        logger.debug(f"Компьютер перезагружался: {fp16}")
        path.unlink(missing_ok=True)
        return None

    return data


def list_saved_sessions() -> list[dict]:
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

    # Сортируем по last_login: самый свежий — первый
    result.sort(key=lambda x: x.get("last_login", 0), reverse=True)
    return result