"""Работа с сетевой папкой (шарой) Pygram.

Единая точка доступа к файлам в SHARED_FOLDER. Атомарная запись,
проверка существования, безопасное построение путей.

Структура шары:
    .logins/<sha256(login)>          — маркер логина: {fp: "...", created_at: ...}
    .keys/<fp16>.pub.pem             — публичный RSA-ключ
    .auth/<fp16>.auth                — Argon2id-хеш пароля
    .identities/<fp16>.enc           — приватный RSA-ключ (Argon2id+AES-GCM)
    .admins/list.json                — список админов
    .meta/<chat_id>.json             — минимальные мета чата
    .meta/<chat_id>.enc              — зашифрованные мета
    .meta/<chat_id>.keys.json        — обёртки group_key
    message/<chat_id>/*.bin          — сообщения
    files/<chat_id>/*                — вложения
    .status/<chat_id>/*              — статусы доставки
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from loguru import logger

from src.utils.validators import safe_join


# ============================================================================
# Служебные папки в шаре
# ============================================================================

DIR_LOGINS = ".logins"
DIR_KEYS = ".keys"
DIR_AUTH = ".auth"
DIR_IDENTITIES = ".identities"
DIR_ADMINS = ".admins"
DIR_META = ".meta"
DIR_MESSAGE = "message"
DIR_FILES = "files"
DIR_STATUS = ".status"

ALL_DIRS = [
    DIR_LOGINS, DIR_KEYS, DIR_AUTH, DIR_IDENTITIES,
    DIR_ADMINS, DIR_META, DIR_MESSAGE, DIR_FILES, DIR_STATUS,
]


# ============================================================================
# Базовые операции
# ============================================================================

def ensure_shared_structure(shared_folder: Path | str) -> None:
    """Создаёт все служебные папки в шаре, если их нет.

    Args:
        shared_folder: Корень шары.
    """
    root = Path(shared_folder).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for d in ALL_DIRS:
        (root / d).mkdir(exist_ok=True)
    logger.debug(f"Структура шары готова: {root}")


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Атомарная запись bytes через .tmp + os.replace.

    Args:
        path: Куда писать.
        data: Что писать.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_json_atomic(path: Path, data: Any) -> None:
    """Атомарная запись JSON (UTF-8, отступ 2)."""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    write_bytes_atomic(path, text.encode("utf-8"))


def read_json(path: Path) -> Any:
    """Читает JSON. Бросает ValueError, если файл битый.

    Raises:
        FileNotFoundError: если файла нет.
        ValueError: если JSON некорректен.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Файл не найден: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Некорректный JSON в {path}: {e}") from e


# ============================================================================
# Хеши / fingerprint
# ============================================================================

def sha256_login(login: str) -> str:
    """Возвращает sha256-хеш логина (hex, 64 символа).

    Используется как имя маркера в .logins/.
    Сам логин в шаре не хранится.
    """
    if not isinstance(login, str) or not login:
        raise ValueError("login должен быть непустой строкой")
    return hashlib.sha256(login.encode("utf-8")).hexdigest()


def short_fp(fp: str, length: int = 16) -> str:
    """Первые `length` символов fingerprint для имён файлов.

    Args:
        fp: Полный fingerprint (hex).
        length: Сколько символов оставить.

    Returns:
        Короткий fingerprint (hex).
    """
    if length < 8 or length > len(fp):
        raise ValueError(f"length должен быть 8..{len(fp)}")
    return fp[:length]


# ============================================================================
# Пути: .logins/
# ============================================================================

def login_marker_path(shared_folder: Path | str, login: str) -> Path:
    """Путь к маркеру логина: .logins/<sha256(login)>"""
    h = sha256_login(login)
    return safe_join(shared_folder, DIR_LOGINS, h)


def login_exists(shared_folder: Path | str, login: str) -> bool:
    """Есть ли логин в системе (по маркеру)?"""
    return login_marker_path(shared_folder, login).is_file()


def save_login_marker(
    shared_folder: Path | str,
    login: str,
    fp: str,
) -> None:
    """Создаёт маркер логина.

    Args:
        shared_folder: Корень шары.
        login: Логин (открытым текстом — НЕ сохраняется).
        fp: Fingerprint публичного ключа.
    """
    import time
    path = login_marker_path(shared_folder, login)
    if path.exists():
        raise FileExistsError(f"Логин уже существует: {login}")
    write_json_atomic(path, {
        "fp": fp,
        "created_at": int(time.time() * 1000),
    })
    logger.debug(f"Маркер логина создан: sha256({login})")


def load_login_marker(shared_folder: Path | str, login: str) -> dict:
    """Читает маркер логина.

    Raises:
        FileNotFoundError: если логина нет.
    """
    path = login_marker_path(shared_folder, login)
    return read_json(path)


# ============================================================================
# Пути: .keys/, .auth/, .identities/
# ============================================================================

def pub_key_path(shared_folder: Path | str, fp: str, fp_len: int = 16) -> Path:
    """Путь к публичному ключу: .keys/<fp16>.pub.pem"""
    return safe_join(shared_folder, DIR_KEYS, f"{short_fp(fp, fp_len)}.pub.pem")


def auth_path(shared_folder: Path | str, fp: str, fp_len: int = 16) -> Path:
    """Путь к Argon2id-хешу пароля: .auth/<fp16>.auth"""
    return safe_join(shared_folder, DIR_AUTH, f"{short_fp(fp, fp_len)}.auth")


def identity_path(shared_folder: Path | str, fp: str, fp_len: int = 16) -> Path:
    """Путь к зашифрованному приватнику: .identities/<fp16>.enc"""
    return safe_join(shared_folder, DIR_IDENTITIES, f"{short_fp(fp, fp_len)}.enc")


# ============================================================================
# Запись / чтение ключевых файлов
# ============================================================================

def save_pub_key(shared_folder: Path | str, fp: str, pub_pem: str) -> Path:
    """Сохраняет публичный ключ в .keys/<fp16>.pub.pem."""
    path = pub_key_path(shared_folder, fp)
    write_bytes_atomic(path, pub_pem.encode("ascii"))
    return path


def load_pub_key(shared_folder: Path | str, fp: str) -> str:
    """Загружает публичный ключ.

    Raises:
        FileNotFoundError: если ключа нет.
    """
    path = pub_key_path(shared_folder, fp)
    return path.read_text(encoding="ascii")


def save_auth(shared_folder: Path | str, fp: str, password_hash: str) -> Path:
    """Сохраняет Argon2id-хеш пароля в .auth/<fp16>.auth."""
    path = auth_path(shared_folder, fp)
    write_bytes_atomic(path, password_hash.encode("ascii"))
    return path


def load_auth(shared_folder: Path | str, fp: str) -> str:
    """Загружает Argon2id-хеш пароля.

    Raises:
        FileNotFoundError: если файла нет.
    """
    path = auth_path(shared_folder, fp)
    return path.read_text(encoding="ascii")


def save_identity_blob(shared_folder: Path | str, fp: str, blob: bytes) -> Path:
    """Сохраняет зашифрованный приватник в .identities/<fp16>.enc."""
    path = identity_path(shared_folder, fp)
    write_bytes_atomic(path, blob)
    return path


def load_identity_blob(shared_folder: Path | str, fp: str) -> bytes:
    """Загружает зашифрованный приватник.

    Raises:
        FileNotFoundError: если файла нет.
    """
    path = identity_path(shared_folder, fp)
    return path.read_bytes()