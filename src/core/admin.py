"""Управление админами Pygram.

Каждая запись в .admins/list.json подписана тем, кто назначал (RSA-PSS),
кроме самой первой (by="system").
"""

from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

from src.core.crypto import from_base64, rsa_sign, rsa_verify, to_base64
from src.storage.shared_store import (
    DIR_ADMINS,
    ensure_shared_structure,
    load_pub_key_by_fp16,
    read_json,
    safe_join,
    write_json_atomic,
)

ADMINS_FILE = "list.json"


def admins_path(shared_folder: Path | str) -> Path:
    return safe_join(shared_folder, DIR_ADMINS, ADMINS_FILE)


def _load_list(shared_folder: Path | str) -> dict:
    path = admins_path(shared_folder)
    if not path.is_file():
        return {"admins": []}
    try:
        return read_json(path)
    except ValueError as e:
        logger.error(f"Битый .admins/list.json: {e}")
        return {"admins": []}


def _save_list(shared_folder: Path | str, data: dict) -> None:
    write_json_atomic(admins_path(shared_folder), data)


# ============================================================================
# ПУБЛИЧНЫЕ ЧТЕНИЯ
# ============================================================================

def load_admins(shared_folder: Path | str) -> list[dict]:
    """Возвращает сырые записи (без проверки подписей).

    Для внутреннего использования в _save_list/remove_admin.
    Для UI/проверок прав используй load_admins_verified().
    """
    return _load_list(shared_folder)["admins"]


def load_admins_verified(shared_folder: Path | str) -> list[dict]:
    """Загружает админов и проверяет подписи (кроме system).

    Записи с невалидной подписью отбрасываются. Это защищает от
    подмены .admins/list.json злоумышленником с доступом к шаре.
    """
    raw = _load_list(shared_folder)["admins"]
    verified: list[dict] = []
    for entry in raw:
        if entry.get("added_by") == "system":
            verified.append(entry)
            continue
        try:
            by_pub = load_pub_key_by_fp16(shared_folder, entry["added_by"])
        except FileNotFoundError:
            logger.warning(
                f"Админ {entry.get('fp16', '?')}: подписант "
                f"{entry.get('added_by', '?')} не найден, пропущен"
            )
            continue
        if verify_signature(entry, by_pub):
            verified.append(entry)
        else:
            logger.warning(
                f"Админ {entry.get('fp16', '?')}: подпись невалидна, пропущен"
            )
    return verified


def has_any_admin(shared_folder: Path | str) -> bool:
    return len(load_admins_verified(shared_folder)) > 0


def is_admin(shared_folder: Path | str, fp16: str) -> bool:
    return any(a["fp16"] == fp16 for a in load_admins_verified(shared_folder))


def is_super(shared_folder: Path | str, fp16: str) -> bool:
    return any(
        a["fp16"] == fp16 and a.get("is_super", False)
        for a in load_admins_verified(shared_folder)
    )


def get_super(shared_folder: Path | str) -> dict | None:
    for a in load_admins_verified(shared_folder):
        if a.get("is_super", False):
            return a
    return None


# ============================================================================
# НАЗНАЧЕНИЕ / СНЯТИЕ
# ============================================================================

def make_admin(
    shared_folder: Path | str,
    fp16: str,
    by: str,
    by_priv: str | None = None,
) -> None:
    """Назначает админа. Первый (by="system") становится супер-админом."""
    ensure_shared_structure(shared_folder)

    if is_admin(shared_folder, fp16):
        raise ValueError(f"{fp16} уже админ")

    if by != "system":
        admins = load_admins_verified(shared_folder)
        by_entry = next((a for a in admins if a["fp16"] == by), None)
        if not by_entry:
            raise ValueError("Вы не админ")
        if not by_entry.get("is_super", False) and not by_entry.get("can_manage_admins", False):
            raise ValueError("У вас нет прав на назначение админов")

    added_at = int(time.time() * 1000)
    payload = f"{fp16}|{added_at}|{by}".encode("utf-8")
    is_super_new = (by == "system")

    if by == "system":
        signature_b64 = ""
    else:
        if by_priv is None:
            raise ValueError("by_priv обязателен")
        signature_b64 = to_base64(rsa_sign(by_priv, payload))

    data = _load_list(shared_folder)
    data["admins"].append({
        "fp16": fp16,
        "added_at": added_at,
        "added_by": by,
        "signature": signature_b64,
        "is_super": is_super_new,
        "can_manage_admins": False,
        "can_read_all_chats": False,
    })
    _save_list(shared_folder, data)
    logger.info(f"Админ назначен: {fp16} (by={by})")


def remove_admin(
    shared_folder: Path | str,
    fp16: str,
    by: str,
    by_priv: str | None = None,
) -> None:
    """Снимает админа. Супер-админа снять нельзя."""
    admins = load_admins_verified(shared_folder)
    target = [a for a in admins if a["fp16"] == fp16]

    if not target:
        raise ValueError(f"{fp16} не админ")
    if target[0].get("is_super", False):
        raise ValueError("Нельзя снять супер-админа")

    if by != "system":
        by_entry = next((a for a in admins if a["fp16"] == by), None)
        if not by_entry:
            raise ValueError("Вы не админ")
        if not by_entry.get("is_super", False) and not by_entry.get("can_manage_admins", False):
            raise ValueError("У вас нет прав на снятие админов")

    data = _load_list(shared_folder)
    data["admins"] = [a for a in data["admins"] if a["fp16"] != fp16]
    _save_list(shared_folder, data)
    logger.info(f"Админ снят: {fp16} (by={by})")


# ============================================================================
# ПРАВА
# ============================================================================

def toggle_manage_rights(shared_folder: Path | str, fp16: str, by: str) -> None:
    """Выдать/забрать право can_manage_admins (только супер-админ)."""
    admins = load_admins_verified(shared_folder)
    by_entry = next((a for a in admins if a["fp16"] == by), None)
    if not by_entry or not by_entry.get("is_super", False):
        raise ValueError("Только супер-админ может менять права")

    data = _load_list(shared_folder)
    for a in data["admins"]:
        if a["fp16"] == fp16:
            a["can_manage_admins"] = not a.get("can_manage_admins", False)
            break
    _save_list(shared_folder, data)


def toggle_read_rights(shared_folder: Path | str, fp16: str, by: str) -> None:
    """Выдать/забрать право can_read_all_chats (только супер-админ)."""
    admins = load_admins_verified(shared_folder)
    by_entry = next((a for a in admins if a["fp16"] == by), None)
    if not by_entry or not by_entry.get("is_super", False):
        raise ValueError("Только супер-админ может менять права")

    data = _load_list(shared_folder)
    for a in data["admins"]:
        if a["fp16"] == fp16:
            a["can_read_all_chats"] = not a.get("can_read_all_chats", False)
            break
    _save_list(shared_folder, data)


def can_read_all_chats(shared_folder: Path | str, fp16: str) -> bool:
    if is_super(shared_folder, fp16):
        return True
    admins = load_admins_verified(shared_folder)
    entry = next((a for a in admins if a["fp16"] == fp16), None)
    return entry.get("can_read_all_chats", False) if entry else False


def can_manage_admins(shared_folder: Path | str, fp16: str) -> bool:
    if is_super(shared_folder, fp16):
        return True
    admins = load_admins_verified(shared_folder)
    entry = next((a for a in admins if a["fp16"] == fp16), None)
    return entry.get("can_manage_admins", False) if entry else False


# ============================================================================
# ПОДПИСИ
# ============================================================================

def verify_signature(entry: dict, by_pub_pem: str) -> bool:
    """Проверяет подпись записи админа. system всегда валиден."""
    if entry.get("added_by") == "system":
        return True
    if not entry.get("signature"):
        return False
    payload = f"{entry['fp16']}|{entry['added_at']}|{entry['added_by']}".encode("utf-8")
    try:
        sig = from_base64(entry["signature"])
    except ValueError:
        return False
    return rsa_verify(by_pub_pem, payload, sig)