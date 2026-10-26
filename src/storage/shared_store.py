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

SMB-специфика:
    На сетевых папках Windows (Z:\\, \\\\server\\share) rename/replace
    может падать с WinError 5 (ACCESS_DENIED), если файл держит
    антивирус, Windows Search Indexer или другой клиент.
    Поэтому write_bytes_atomic:
      - использует UUID в имени .tmp (нет коллизий между клиентами);
      - делает retry с экспоненциальным backoff;
      - в крайнем случае падает в прямую запись (не атомарно,
        но данные не теряются).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
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


def write_bytes_atomic(path: Path, data: bytes, retries: int = 5) -> None:
    """Атомарная запись bytes через .tmp + os.replace.

    На SMB (сетевые папки Windows) rename/replace может падать с
    WinError 5 (файл занят антивирусом/индексатором/другим клиентом).
    Поэтому:
      - .tmp с уникальным именем (UUID) — два клиента не бьются за один .tmp;
      - retry с экспоненциальным backoff;
      - финальный fallback — прямая запись без atomic (лучше потерять
        атомарность, чем потерять данные).

    Args:
        path: Куда писать.
        data: Что писать.
        retries: Сколько попыток replace сделать до fallback.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Уникальный .tmp: два клиента одновременно не мешают друг другу
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex[:8]}.tmp")

    tmp.write_bytes(data)

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            tmp.replace(path)
            return  # успех
        except (PermissionError, OSError) as e:
            last_err = e
            # На SMB WinError 5 — часто транзиентная (антивирус/индексатор)
            delay = 0.05 * (2 ** attempt)  # 50, 100, 200, 400, 800 мс
            logger.debug(
                f"write_bytes_atomic: replace failed (attempt {attempt + 1}/{retries}, "
                f"retry in {delay:.2f}s): {e}"
            )
            time.sleep(delay)
            if not tmp.exists():
                # Кто-то (антивирус?) уже удалил tmp — пересоздадим
                tmp.write_bytes(data)

    # Fallback: прямая запись. Не атомарно, но данные не потеряем.
    logger.warning(
        f"write_bytes_atomic: atomic replace failed after {retries} attempts "
        f"({last_err}), falling back to direct write: {path}"
    )
    try:
        path.write_bytes(data)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


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
        login_name: str | None = None,  # <--- НОВЫЙ ПАРАМЕТР
) -> None:
    """Создаёт маркер логина.

    Args:
        shared_folder: Корень шары.
        login: Логин (открытым текстом — НЕ сохраняется в имени файла).
        fp: Fingerprint публичного ключа.
        login_name: Опционально, сам логин для сохранения в JSON (для UI).
    """
    path = login_marker_path(shared_folder, login)
    if path.exists():
        raise FileExistsError(f"Логин уже существует: {login}")

    data = {
        "fp": fp,
        "created_at": int(time.time() * 1000),
    }
    if login_name:
        data["login"] = login_name

    write_json_atomic(path, data)
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


# ============================================================================
# ЧАТЫ: .meta/ и групповые ключи
# ============================================================================

def chat_meta_path(shared_folder: Path | str, chat_id: str) -> Path:
    """Путь к метаданным чата: .meta/<chat_id>.json"""
    return safe_join(shared_folder, DIR_META, f"{chat_id}.json")


def chat_meta_enc_path(shared_folder: Path | str, chat_id: str) -> Path:
    """Путь к зашифрованным метаданным: .meta/<chat_id>.enc"""
    return safe_join(shared_folder, DIR_META, f"{chat_id}.enc")


def chat_keys_path(shared_folder: Path | str, chat_id: str) -> Path:
    """Путь к обёрткам group_key: .meta/<chat_id>.keys.json"""
    return safe_join(shared_folder, DIR_META, f"{chat_id}.keys.json")


def save_chat_meta(shared_folder: Path | str, chat_id: str, meta: dict) -> Path:
    """Сохраняет открытые метаданные чата."""
    path = chat_meta_path(shared_folder, chat_id)
    write_json_atomic(path, meta)
    return path


def load_chat_meta(shared_folder: Path | str, chat_id: str) -> dict:
    """Загружает открытые метаданные чата."""
    return read_json(chat_meta_path(shared_folder, chat_id))


def save_chat_meta_enc(shared_folder: Path | str, chat_id: str, blob: bytes) -> Path:
    """Сохраняет зашифрованные метаданные чата."""
    path = chat_meta_enc_path(shared_folder, chat_id)
    write_bytes_atomic(path, blob)
    return path


def load_chat_meta_enc(shared_folder: Path | str, chat_id: str) -> bytes:
    """Загружает зашифрованные метаданные чата."""
    return chat_meta_enc_path(shared_folder, chat_id).read_bytes()


def save_chat_keys(shared_folder: Path | str, chat_id: str, keys: dict) -> Path:
    """Сохраняет обёртки group_key (JSON)."""
    path = chat_keys_path(shared_folder, chat_id)
    write_json_atomic(path, keys)
    return path


def load_chat_keys(shared_folder: Path | str, chat_id: str) -> dict:
    """Загружает обёртки group_key."""
    return read_json(chat_keys_path(shared_folder, chat_id))


# ============================================================================
# ПАПКИ СООБЩЕНИЙ / ФАЙЛОВ
# ============================================================================

def chat_message_dir(shared_folder: Path | str, chat_id: str) -> Path:
    """Путь к папке сообщений: message/<chat_id>/"""
    return safe_join(shared_folder, DIR_MESSAGE, chat_id)


def chat_files_dir(shared_folder: Path | str, chat_id: str) -> Path:
    """Путь к папке вложений: files/<chat_id>/"""
    return safe_join(shared_folder, DIR_FILES, chat_id)


def ensure_chat_folders(shared_folder: Path | str, chat_id: str) -> None:
    """Создаёт папки для чата: message/<id>/, files/<id>/, .status/<id>/"""
    chat_message_dir(shared_folder, chat_id).mkdir(parents=True, exist_ok=True)
    chat_files_dir(shared_folder, chat_id).mkdir(parents=True, exist_ok=True)
    safe_join(shared_folder, DIR_STATUS, chat_id).mkdir(parents=True, exist_ok=True)


def load_pub_key_by_fp16(shared_folder: Path | str, fp16: str) -> str:
    """Загружает публичный ключ по короткому fp16.

    Raises:
        FileNotFoundError: если ключа нет.
    """
    path = safe_join(shared_folder, DIR_KEYS, f"{fp16}.pub.pem")
    return path.read_text(encoding="ascii")