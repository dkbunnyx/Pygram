"""Управление админами Pygram.

Список админов хранится в .admins/list.json в шаре.
Каждая запись содержит fp16 (не логин!) и подпись RSA-PSS того,
кто назначил админа.

Формат:
    {
      "admins": [
        {"fp16": "a1b2...", "added_at": 1729..., "added_by": "system",
         "signature": "base64"},
        {"fp16": "c3d4...", "added_at": 1729..., "added_by": "a1b2...",
         "signature": "base64"}
      ]
    }

Подпись: rsa_sign(by_priv, f"{fp16}|{added_at}|{added_by}".encode())
"""

from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

from src.core.crypto import from_base64, rsa_sign, rsa_verify, to_base64
from src.storage.shared_store import (
    DIR_ADMINS,
    ensure_shared_structure,
    read_json,
    safe_join,
    write_json_atomic,
)

ADMINS_FILE = "list.json"


# ============================================================================
# Пути
# ============================================================================

def admins_path(shared_folder: Path | str) -> Path:
    """Путь к .admins/list.json."""
    return safe_join(shared_folder, DIR_ADMINS, ADMINS_FILE)


# ============================================================================
# Чтение / запись
# ============================================================================

def _load_list(shared_folder: Path | str) -> dict:
    """Читает list.json или возвращает {"admins": []}, если его нет."""
    path = admins_path(shared_folder)
    if not path.is_file():
        return {"admins": []}
    return read_json(path)


def _save_list(shared_folder: Path | str, data: dict) -> None:
    """Атомарно пишет list.json."""
    write_json_atomic(admins_path(shared_folder), data)


# ============================================================================
# Публичный API
# ============================================================================

def load_admins(shared_folder: Path | str) -> list[dict]:
    """Возвращает список записей админов (fp16, added_at, added_by, signature)."""
    return _load_list(shared_folder)["admins"]


def has_any_admin(shared_folder: Path | str) -> bool:
    """Есть ли хоть один админ?"""
    return len(load_admins(shared_folder)) > 0


def is_admin(shared_folder: Path | str, fp16: str) -> bool:
    """Проверяет, админ ли пользователь с данным fp16."""
    return any(a["fp16"] == fp16 for a in load_admins(shared_folder))


def make_admin(
        shared_folder: Path | str,
        fp16: str,
        by: str,
        by_priv: str | None = None,
) -> None:
    """Назначает админа.

    Args:
        shared_folder: Корень шары.
        fp16: Fingerprint нового админа.
        by: fp16 того, кто назначает ("system" для первого).
        by_priv: Приватный ключ того, кто назначает.
                 None только для by="system" (первый админ).

    Raises:
        ValueError: если уже админ или подпись невозможна.
    """
    ensure_shared_structure(shared_folder)

    if is_admin(shared_folder, fp16):
        raise ValueError(f"{fp16} уже админ")

    added_at = int(time.time() * 1000)
    payload = f"{fp16}|{added_at}|{by}".encode("utf-8")

    if by == "system":
        # Первый админ — подпись не нужна (или пустая)
        signature_b64 = ""
    else:
        if by_priv is None:
            raise ValueError("by_priv обязателен для by != 'system'")
        signature_b64 = to_base64(rsa_sign(by_priv, payload))

    data = _load_list(shared_folder)
    data["admins"].append({
        "fp16": fp16,
        "added_at": added_at,
        "added_by": by,
        "signature": signature_b64,
    })
    _save_list(shared_folder, data)
    logger.info(f"Админ назначен: {fp16} (by={by})")


def remove_admin(
        shared_folder: Path | str,
        fp16: str,
        by: str,
) -> None:
    """Снимает админку.

    Args:
        shared_folder: Корень шары.
        fp16: Кого снять.
        by: fp16 того, кто снимает.

    Raises:
        ValueError: если не админ или попытка снять последнего.
    """
    admins = load_admins(shared_folder)
    target = [a for a in admins if a["fp16"] == fp16]
    if not target:
        raise ValueError(f"{fp16} не админ")

    if len(admins) <= 1:
        raise ValueError("Нельзя снять последнего админа")

    data = _load_list(shared_folder)
    data["admins"] = [a for a in data["admins"] if a["fp16"] != fp16]
    _save_list(shared_folder, data)
    logger.info(f"Админ снят: {fp16} (by={by})")


def verify_signature(
        entry: dict,
        by_pub_pem: str,
) -> bool:
    """Проверяет подпись записи.

    Args:
        entry: Запись из list.json.
        by_pub_pem: Публичный ключ того, кто назначал.

    Returns:
        True, если подпись валидна (или added_by == "system").
    """
    if entry["added_by"] == "system":
        return True

    if not entry.get("signature"):
        return False

    payload = f"{entry['fp16']}|{entry['added_at']}|{entry['added_by']}".encode("utf-8")
    try:
        sig = from_base64(entry["signature"])
    except ValueError:
        return False
    return rsa_verify(by_pub_pem, payload, sig)
