"""Идентификация Pygram: RSA-ключи, шифрование приватного ключа.

Формат .identities/<fp16>.enc — JSON-контейнер:
    {
      "version": 1,
      "fp": "...",               # полный fingerprint
      "created_at": ...,
      "kdf": {"algo": "argon2id", "time_cost": 3,
              "memory_cost": 65536, "parallelism": 4,
              "salt": "base64..."},
      "cipher": {"algo": "aes-256-gcm",
                 "nonce": "base64...",
                 "ciphertext": "base64..."}
    }

AAD для AES-GCM: f"fp={fp}|identity|v{version}" — защита от подмены.

Файлы в шаре:
    .logins/<sha256(login)>  — {fp: ..., created_at: ...}
    .keys/<fp16>.pub.pem     — публичный ключ (открыто, так и надо)
    .auth/<fp16>.auth        — Argon2id-хеш пароля
    .identities/<fp16>.enc   — приватник (Argon2id+AES-GCM)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from loguru import logger

from src.core.crypto import (
    AES_KEY_SIZE,
    aes_decrypt,
    aes_encrypt,
    derive_key_argon2,
    fingerprint,
    from_base64,
    generate_rsa_keypair,
    generate_salt,
    hash_password,
    load_private_key,
    to_base64,
    verify_password,
)
from src.storage.shared_store import (
    ensure_shared_structure,
    identity_path,
    load_auth,
    load_identity_blob,
    load_login_marker,
    load_pub_key,
    login_exists,
    save_auth,
    save_identity_blob,
    save_login_marker,
    save_pub_key,
)


# ============================================================================
# Константы формата
# ============================================================================

IDENTITY_VERSION = 1
KDF_ALGO = "argon2id"
KDF_TIME_COST = 3
KDF_MEMORY_COST = 65536
KDF_PARALLELISM = 4
KDF_SALT_SIZE = 16

AAD_TEMPLATE = "fp={fp}|identity|v{version}"


# ============================================================================
# Генерация
# ============================================================================

def generate_identity(login: str, password: str) -> tuple[str, str]:
    """Генерирует RSA-пару. Ничего не сохраняет.

    Args:
        login: Логин (для валидации).
        password: Пароль (для валидации).

    Returns:
        Кортеж (priv_pem, pub_pem).

    Raises:
        ValueError: если логин/пароль пустые.
    """
    if not login or not isinstance(login, str):
        raise ValueError("login должен быть непустой строкой")
    if not password or not isinstance(password, str):
        raise ValueError("password должен быть непустой строкой")

    logger.debug(f"Генерация RSA-пары для {login}")
    return generate_rsa_keypair()


# ============================================================================
# Регистрация (сохранить всё)
# ============================================================================

def register_identity(
    shared_folder: Path | str,
    login: str,
    password: str,
) -> str:
    """Регистрирует нового пользователя.

    Создаёт:
        .logins/<sha256(login)>  — маркер
        .keys/<fp16>.pub.pem     — публичный ключ
        .auth/<fp16>.auth        — Argon2id(пароль)
        .identities/<fp16>.enc   — приватник (Argon2id+AES-GCM)

    Args:
        shared_folder: Корень шары.
        login: Логин.
        password: Пароль.

    Returns:
        fp16 (короткий fingerprint) — идентификатор пользователя в шаре.

    Raises:
        FileExistsError: если логин занят.
        ValueError: если параметры некорректны.
    """
    ensure_shared_structure(shared_folder)

    if login_exists(shared_folder, login):
        raise FileExistsError(f"Логин '{login}' уже занят")

    priv_pem, pub_pem = generate_identity(login, password)
    fp = fingerprint(pub_pem)
    fp16 = fp[:16]

    # 1) Маркер логина
    save_login_marker(shared_folder, login, fp)

    # 2) Публичный ключ
    save_pub_key(shared_folder, fp, pub_pem)

    # 3) Argon2id-хеш пароля (для быстрой проверки при логине)
    save_auth(shared_folder, fp, hash_password(password))

    # 4) Зашифрованный приватник
    _save_encrypted_priv(shared_folder, fp, priv_pem, password)

    logger.info(f"Зарегистрирован {login} (fp16={fp16})")
    return fp16


def _save_encrypted_priv(
    shared_folder: Path | str,
    fp: str,
    priv_pem: str,
    password: str,
) -> None:
    """Внутренняя: шифрует priv_pem и пишет в .identities/<fp16>.enc."""
    salt = generate_salt(KDF_SALT_SIZE)
    session_key = derive_key_argon2(password, salt)

    if len(session_key) != AES_KEY_SIZE:
        raise RuntimeError(f"session_key неверного размера: {len(session_key)}")

    aad = AAD_TEMPLATE.format(fp=fp, version=IDENTITY_VERSION).encode("utf-8")
    nonce, ciphertext = aes_encrypt(session_key, priv_pem.encode("utf-8"), aad=aad)

    container = {
        "version": IDENTITY_VERSION,
        "fp": fp,
        "created_at": int(time.time() * 1000),
        "kdf": {
            "algo": KDF_ALGO,
            "time_cost": KDF_TIME_COST,
            "memory_cost": KDF_MEMORY_COST,
            "parallelism": KDF_PARALLELISM,
            "salt": to_base64(salt),
        },
        "cipher": {
            "algo": "aes-256-gcm",
            "nonce": to_base64(nonce),
            "ciphertext": to_base64(ciphertext),
        },
    }

    blob = json.dumps(container, ensure_ascii=False, indent=2).encode("utf-8")
    save_identity_blob(shared_folder, fp, blob)


# ============================================================================
# Логин (загрузить, расшифровать)
# ============================================================================

def authenticate(
    shared_folder: Path | str,
    login: str,
    password: str,
) -> tuple[str, str]:
    """Проверяет пароль и расшифровывает приватный ключ.

    Args:
        shared_folder: Корень шары.
        login: Логин.
        password: Пароль.

    Returns:
        (priv_pem, fp16).

    Raises:
        FileNotFoundError: если логина нет.
        ValueError: если пароль неверный или файл повреждён.
    """
    if not login_exists(shared_folder, login):
        raise FileNotFoundError(f"Логин '{login}' не найден")

    marker = load_login_marker(shared_folder, login)
    fp = marker["fp"]
    fp16 = fp[:16]

    # 1) Быстрая проверка Argon2id-хеша пароля
    try:
        stored_hash = load_auth(shared_folder, fp)
    except FileNotFoundError as e:
        raise ValueError(f"Файл .auth/<fp16>.auth повреждён/отсутствует") from e

    if not verify_password(password, stored_hash):
        raise ValueError("Неверный пароль")

    # 2) Расшифровка приватника
    priv_pem = _load_encrypted_priv(shared_folder, fp, password)

    logger.info(f"Аутентификация успешна: {login} (fp16={fp16})")
    return priv_pem, fp16


def _load_encrypted_priv(
    shared_folder: Path | str,
    fp: str,
    password: str,
) -> str:
    """Внутренняя: читает .identities/<fp16>.enc и расшифровывает."""
    try:
        blob = load_identity_blob(shared_folder, fp)
    except FileNotFoundError as e:
        raise ValueError(f"Файл .identities/<fp16>.enc отсутствует") from e

    try:
        container = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"Битый identity-файл: {e}") from e

    _validate_container(container, fp)

    salt = from_base64(container["kdf"]["salt"])
    nonce = from_base64(container["cipher"]["nonce"])
    ciphertext = from_base64(container["cipher"]["ciphertext"])

    session_key = derive_key_argon2(password, salt)
    aad = AAD_TEMPLATE.format(fp=fp, version=container["version"]).encode("utf-8")

    try:
        priv_pem_bytes = aes_decrypt(session_key, nonce, ciphertext, aad=aad)
    except ValueError as e:
        raise ValueError("Не удалось расшифровать приватный ключ") from e

    # Финальная сверка fingerprint
    priv_pem = priv_pem_bytes.decode("utf-8")
    pub_from_priv = _pub_from_priv(priv_pem)
    if fingerprint(pub_from_priv) != fp:
        raise ValueError("Fingerprint не совпал — файл повреждён или подменён")

    return priv_pem


# ============================================================================
# Смена пароля
# ============================================================================

def change_password(
    shared_folder: Path | str,
    login: str,
    old_password: str,
    new_password: str,
) -> None:
    """Меняет пароль, не перегенерируя RSA-ключи.

    Raises:
        FileNotFoundError, ValueError.
    """
    if not new_password or not isinstance(new_password, str):
        raise ValueError("new_password должен быть непустой строкой")

    priv_pem, fp16 = authenticate(shared_folder, login, old_password)

    # Обновляем .auth
    save_auth(shared_folder, _load_fp(shared_folder, login), hash_password(new_password))

    # Обновляем .identities
    _save_encrypted_priv(shared_folder, _load_fp(shared_folder, login), priv_pem, new_password)

    logger.info(f"Пароль изменён: {login}")


# ============================================================================
# Проверка / поиск
# ============================================================================

def identity_exists(shared_folder: Path | str, login: str) -> bool:
    """Есть ли пользователь с таким логином?"""
    return login_exists(shared_folder, login)


def get_fp16(shared_folder: Path | str, login: str) -> str | None:
    """Возвращает fp16 для логина, или None."""
    try:
        marker = load_login_marker(shared_folder, login)
        return marker["fp"][:16]
    except (FileNotFoundError, ValueError):
        return None


# ============================================================================
# Помощники
# ============================================================================

def _pub_from_priv(priv_pem: str) -> str:
    key = load_private_key(priv_pem)
    return key.publickey().export_key().decode("ascii")


def _load_fp(shared_folder: Path | str, login: str) -> str:
    return load_login_marker(shared_folder, login)["fp"]


def _validate_container(container: dict, expected_fp: str) -> None:
    """Проверяет структуру JSON-контейнера identity."""
    for key in ["version", "fp", "kdf", "cipher"]:
        if key not in container:
            raise ValueError(f"В файле отсутствует поле '{key}'")

    if container["version"] != IDENTITY_VERSION:
        raise ValueError(f"Неподдерживаемая версия: {container['version']}")

    if container["fp"] != expected_fp:
        raise ValueError("Fingerprint в файле не совпадает с ожидаемым")

    if container["kdf"].get("algo") != KDF_ALGO:
        raise ValueError(f"Неподдерживаемый KDF: {container['kdf'].get('algo')}")

    for key in ["salt"]:
        if key not in container["kdf"]:
            raise ValueError(f"В kdf нет '{key}'")

    for key in ["nonce", "ciphertext"]:
        if key not in container["cipher"]:
            raise ValueError(f"В cipher нет '{key}'")