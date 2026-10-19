"""Логика чатов Pygram: DM, группы, избранное, админ-чат.

Схема:
    - DM: chat_id = dm_<fp16_a>__<fp16_b> (sorted). Гибридное шифрование.
    - Группа: chat_id = grp_<uuid4>. group_key заворачивается для каждого.
    - Избранное: chat_id = fav_<fp16_owner>. Гибридное шифрование.
    - Админ-чат: chat_id = admin_chat. Гибридное шифрование для всех админов.

В метаданных храним ТОЛЬКО fp16 (без логинов).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from loguru import logger

from src.core.admin import is_admin, load_admins
from src.core.crypto import (
    aes_encrypt,
    generate_aes_key,
    generate_uuid,
    rsa_encrypt,
    to_base64,
)
from src.core.identity import get_fp16
from src.storage.shared_store import (
    ensure_chat_folders,
    ensure_shared_structure,
    load_chat_keys,
    load_chat_meta,
    load_pub_key_by_fp16,
    save_chat_keys,
    save_chat_meta,
    save_chat_meta_enc,
)


# ============================================================================
# Утилиты
# ============================================================================

def _sorted_pair(fp1: str, fp2: str) -> tuple[str, str]:
    return tuple(sorted([fp1, fp2]))  # type: ignore


def _get_all_admin_fp16s(shared_folder: Path | str) -> list[str]:
    """Возвращает fp16 всех системных админов."""
    return [a["fp16"] for a in load_admins(shared_folder)]


def _wrap_group_key_for_users(
    shared_folder: Path | str,
    group_key: bytes,
    participants_fp16: list[str],
) -> dict[str, str]:
    """Заворачивает group_key для списка участников + всех админов."""
    wrapped = {}
    recipients = set(participants_fp16) | set(_get_all_admin_fp16s(shared_folder))

    for fp16 in recipients:
        if not fp16:
            continue
        try:
            pub_pem = load_pub_key_by_fp16(shared_folder, fp16)
        except FileNotFoundError:
            logger.warning(f"Публичный ключ для {fp16} не найден, пропускаем")
            continue
        wrapped[fp16] = to_base64(rsa_encrypt(pub_pem, group_key))
    return wrapped


# ============================================================================
# СОЗДАНИЕ ЧАТОВ
# ============================================================================

def create_dm_chat(
    shared_folder: Path | str,
    login1: str,
    login2: str,
) -> str:
    """Создаёт или возвращает личный чат между двумя пользователями."""
    if login1 == login2:
        raise ValueError("Нельзя создать чат с самим собой")

    fp1 = get_fp16(shared_folder, login1)
    fp2 = get_fp16(shared_folder, login2)
    if not fp1 or not fp2:
        raise ValueError("Один из пользователей не найден")

    fpa, fpb = _sorted_pair(fp1, fp2)
    chat_id = f"dm_{fpa}__{fpb}"

    if (shared_folder / ".meta" / f"{chat_id}.json").is_file():
        return chat_id  # Уже существует

    ensure_shared_structure(shared_folder)

    # Открытые метаданные (минимум)
    save_chat_meta(shared_folder, chat_id, {
        "chat_id": chat_id,
        "type": "dm",
        "created_at": int(time.time() * 1000),
        "created_by": login1,
    })
    ensure_chat_folders(shared_folder, chat_id)

    # Для DM используем гибридное шифрование каждого сообщения,
    # но для метаданных создаём "фиктивный" group_key, чтобы
    # структура была единой.
    group_key = generate_aes_key()
    wrapped = _wrap_group_key_for_users(shared_folder, group_key, [fpa, fpb])
    save_chat_keys(shared_folder, chat_id, {"version": 1, "wrapped": wrapped})

    # Зашифрованные метаданные (участники)
    meta_enc = {"participants": [fpa, fpb]}
    save_chat_meta_enc(
        shared_folder, chat_id,
        json.dumps(meta_enc).encode("utf-8"),
    )

    logger.info(f"DM-чат создан: {chat_id}")
    return chat_id


def create_group_chat(
    shared_folder: Path | str,
    creator_login: str,
    name: str,
    member_logins: list[str],
) -> str:
    """Создаёт групповой чат."""
    if not name or len(name) > 100:
        raise ValueError("Название группы должно быть 1–100 символов")

    all_logins = set([creator_login] + member_logins)
    if len(all_logins) < 3:
        raise ValueError("В группе должно быть минимум 3 участника (создатель + 2)")

    # Собираем fp16
    fp16s = []
    for login in all_logins:
        f = get_fp16(shared_folder, login)
        if not f:
            raise ValueError(f"Пользователь {login} не найден")
        fp16s.append(f)

    creator_fp16 = get_fp16(shared_folder, creator_login)
    chat_id = f"grp_{generate_uuid()}"

    save_chat_meta(shared_folder, chat_id, {
        "chat_id": chat_id,
        "type": "group",
        "created_at": int(time.time() * 1000),
    })
    ensure_chat_folders(shared_folder, chat_id)

    # Генерируем group_key
    group_key = generate_aes_key()

    # Заворачиваем group_key для всех
    wrapped = _wrap_group_key_for_users(shared_folder, group_key, fp16s)
    save_chat_keys(shared_folder, chat_id, {"version": 1, "wrapped": wrapped})

    # Зашифрованные метаданные (название, участники)
    meta_enc = {
        "name": name,
        "description": "",
        "members": fp16s,
        "admins": [creator_fp16],
        "created_by": creator_fp16,
        "pinned_message": None,
        "public": False,
    }

    # Шифруем group_key-ом (AES-GCM)
    aad = f"chat_id={chat_id}|meta".encode("utf-8")
    nonce, ct = aes_encrypt(group_key, json.dumps(meta_enc).encode("utf-8"), aad=aad)
    enc_blob = {"nonce": to_base64(nonce), "ciphertext": to_base64(ct)}

    save_chat_meta_enc(
        shared_folder, chat_id,
        json.dumps(enc_blob).encode("utf-8"),
    )

    logger.info(f"Группа создана: {chat_id} ({name})")
    return chat_id


def create_favorites(shared_folder: Path | str, login: str) -> str:
    """Создаёт или возвращает чат «Избранное»."""
    fp16 = get_fp16(shared_folder, login)
    if not fp16:
        raise ValueError("Пользователь не найден")

    chat_id = f"fav_{fp16}"
    if (shared_folder / ".meta" / f"{chat_id}.json").is_file():
        return chat_id

    save_chat_meta(shared_folder, chat_id, {
        "chat_id": chat_id,
        "type": "favorites",
        "created_at": int(time.time() * 1000),
    })
    ensure_chat_folders(shared_folder, chat_id)

    group_key = generate_aes_key()
    wrapped = _wrap_group_key_for_users(shared_folder, group_key, [fp16])
    save_chat_keys(shared_folder, chat_id, {"version": 1, "wrapped": wrapped})

    meta_enc = {"owner": fp16}
    save_chat_meta_enc(shared_folder, chat_id, json.dumps(meta_enc).encode("utf-8"))

    logger.info(f"Избранное создано: {chat_id}")
    return chat_id


def create_admin_chat(shared_folder: Path | str) -> str:
    """Создаёт админ-чат (если его нет)."""
    chat_id = "admin_chat"
    if (shared_folder / ".meta" / f"{chat_id}.json").is_file():
        return chat_id

    save_chat_meta(shared_folder, chat_id, {
        "chat_id": chat_id,
        "type": "admin_chat",
        "created_at": int(time.time() * 1000),
    })
    ensure_chat_folders(shared_folder, chat_id)

    # Создаём ключ и заворачиваем для всех текущих админов
    group_key = generate_aes_key()
    wrapped = _wrap_group_key_for_users(shared_folder, group_key, [])
    save_chat_keys(shared_folder, chat_id, {"version": 1, "wrapped": wrapped})

    save_chat_meta_enc(shared_folder, chat_id, json.dumps({"type": "admin_chat"}).encode("utf-8"))
    logger.info("Админ-чат создан")
    return chat_id


# ============================================================================
# ЧТЕНИЕ И ВИДИМОСТЬ
# ============================================================================

def get_chat_meta(shared_folder: Path | str, chat_id: str) -> dict:
    """Возвращает открытые метаданные."""
    return load_chat_meta(shared_folder, chat_id)


def is_chat_visible(shared_folder: Path | str, chat_id: str, fp16: str) -> bool:
    """Проверяет, виден ли чат пользователю с данным fp16."""
    try:
        meta = load_chat_meta(shared_folder, chat_id)
    except FileNotFoundError:
        return False

    t = meta["type"]
    if t == "admin_chat":
        return is_admin(shared_folder, fp16)

    # Для остальных проверяем наличие обёртки ключа
    try:
        keys = load_chat_keys(shared_folder, chat_id)
        return fp16 in keys.get("wrapped", {})
    except FileNotFoundError:
        return False


def list_user_chats(shared_folder: Path | str, fp16: str) -> list[dict]:
    """Возвращает список открытых метаданных чатов, видимых пользователю."""
    meta_dir = shared_folder / ".meta"
    if not meta_dir.is_dir():
        return []

    result = []
    for entry in meta_dir.glob("*.json"):
        if entry.name.endswith(".keys.json"):
            continue
        chat_id = entry.stem
        if is_chat_visible(shared_folder, chat_id, fp16):
            try:
                result.append(load_chat_meta(shared_folder, chat_id))
            except (FileNotFoundError, ValueError):
                continue
    return sorted(result, key=lambda m: m.get("created_at", 0), reverse=True)


def get_chat_recipients(shared_folder: Path | str, chat_id: str) -> list[str]:
    """Возвращает fp16 получателей для чата (участники + админы)."""
    meta = load_chat_meta(shared_folder, chat_id)
    t = meta["type"]

    recipients = []

    if t == "admin_chat":
        recipients = _get_all_admin_fp16s(shared_folder)
    else:
        try:
            keys = load_chat_keys(shared_folder, chat_id)
            recipients = list(keys.get("wrapped", {}).keys())
        except FileNotFoundError:
            pass

    # Всегда добавляем всех админов
    for admin_fp in _get_all_admin_fp16s(shared_folder):
        if admin_fp not in recipients:
            recipients.append(admin_fp)

    return recipients
