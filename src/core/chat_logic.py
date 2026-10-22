"""Логика чатов Pygram."""

from __future__ import annotations

import json
import time
from pathlib import Path

from loguru import logger

from src.core.admin import is_admin, load_admins_verified, can_read_all_chats
from src.core.crypto import aes_encrypt, generate_aes_key, generate_uuid, rsa_encrypt, to_base64
from src.core.identity import get_fp16
from src.storage.shared_store import (
    ensure_chat_folders, ensure_shared_structure, load_chat_keys,
    load_chat_meta, load_chat_meta_enc, load_pub_key_by_fp16,
    save_chat_keys, save_chat_meta, save_chat_meta_enc,
)


def _sorted_pair(fp1: str, fp2: str) -> tuple[str, str]:
    return tuple(sorted([fp1, fp2]))


def _get_reading_admin_fp16s(shared_folder: Path | str) -> list[str]:
    """Возвращает fp16 админов, у которых есть право читать все чаты.

    Использует load_admins_verified() — подписи проверяются.
    Злоумышленник не сможет подделать запись в .admins/list.json.
    """
    return [
        a["fp16"] for a in load_admins_verified(shared_folder)
        if a.get("is_super") or a.get("can_read_all_chats")
    ]


def _wrap_group_key_for_users(shared_folder: Path | str, group_key: bytes, participants_fp16: list[str]) -> dict[str, str]:
    wrapped = {}
    recipients = set(participants_fp16) | set(_get_reading_admin_fp16s(shared_folder))
    for fp16 in recipients:
        if not fp16:
            continue
        try:
            pub_pem = load_pub_key_by_fp16(shared_folder, fp16)
        except FileNotFoundError:
            continue
        wrapped[fp16] = to_base64(rsa_encrypt(pub_pem, group_key))
    return wrapped


def create_dm_chat(shared_folder: Path | str, login1: str, login2: str) -> str:
    if login1 == login2:
        raise ValueError("Нельзя создать чат с самим собой")

    fp1 = get_fp16(shared_folder, login1)
    fp2 = get_fp16(shared_folder, login2)
    if not fp1 or not fp2:
        raise ValueError("Один из пользователей не найден")

    fpa, fpb = _sorted_pair(fp1, fp2)
    chat_id = f"dm_{fpa}__{fpb}"

    if (Path(shared_folder) / ".meta" / f"{chat_id}.json").is_file():
        return chat_id

    ensure_shared_structure(shared_folder)

    save_chat_meta(shared_folder, chat_id, {
        "chat_id": chat_id, "type": "dm",
        "created_at": int(time.time() * 1000), "created_by": login1,
    })
    ensure_chat_folders(shared_folder, chat_id)

    meta_enc = {"participants": [fpa, fpb]}
    save_chat_meta_enc(shared_folder, chat_id, json.dumps(meta_enc).encode("utf-8"))

    logger.info(f"DM-чат создан: {chat_id}")
    return chat_id


def create_group_chat(shared_folder: Path | str, creator_login: str, name: str, member_logins: list[str]) -> str:
    if not name or len(name) > 100:
        raise ValueError("Название группы должно быть 1–100 символов")

    all_logins = set([creator_login] + member_logins)
    if len(all_logins) < 3:
        raise ValueError("В группе должно быть минимум 3 участника")

    fp16s = []
    for login in all_logins:
        f = get_fp16(shared_folder, login)
        if not f:
            raise ValueError(f"Пользователь {login} не найден")
        fp16s.append(f)

    creator_fp16 = get_fp16(shared_folder, creator_login)
    chat_id = f"grp_{generate_uuid()}"

    save_chat_meta(shared_folder, chat_id, {
        "chat_id": chat_id, "type": "group", "created_at": int(time.time() * 1000),
    })
    ensure_chat_folders(shared_folder, chat_id)

    group_key = generate_aes_key()
    wrapped = _wrap_group_key_for_users(shared_folder, group_key, fp16s)
    save_chat_keys(shared_folder, chat_id, {"version": 1, "wrapped": wrapped})

    meta_enc = {
        "name": name, "description": "", "members": fp16s,
        "admins": [creator_fp16], "created_by": creator_fp16,
        "creator_fp16": creator_fp16,
        "member_permissions": {},
        "pinned_message": None, "public": False,
    }

    aad = f"chat_id={chat_id}|meta".encode("utf-8")
    nonce, ct = aes_encrypt(group_key, json.dumps(meta_enc).encode("utf-8"), aad=aad)
    save_chat_meta_enc(shared_folder, chat_id, json.dumps({"nonce": to_base64(nonce), "ciphertext": to_base64(ct)}).encode("utf-8"))

    return chat_id


def create_favorites(shared_folder: Path | str, login: str) -> str:
    fp16 = get_fp16(shared_folder, login)
    if not fp16:
        raise ValueError("Пользователь не найден")

    chat_id = f"fav_{fp16}"
    if (Path(shared_folder) / ".meta" / f"{chat_id}.json").is_file():
        return chat_id

    save_chat_meta(shared_folder, chat_id, {"chat_id": chat_id, "type": "favorites", "created_at": int(time.time() * 1000)})
    ensure_chat_folders(shared_folder, chat_id)

    group_key = generate_aes_key()
    recipients = [fp16] + _get_reading_admin_fp16s(shared_folder)
    wrapped = _wrap_group_key_for_users(shared_folder, group_key, recipients)
    save_chat_keys(shared_folder, chat_id, {"version": 1, "wrapped": wrapped})

    save_chat_meta_enc(shared_folder, chat_id, json.dumps({"owner": fp16}).encode("utf-8"))
    return chat_id


def create_admin_chat(shared_folder: Path | str) -> str:
    chat_id = "admin_chat"
    if (Path(shared_folder) / ".meta" / f"{chat_id}.json").is_file():
        return chat_id

    save_chat_meta(shared_folder, chat_id, {"chat_id": chat_id, "type": "admin_chat", "created_at": int(time.time() * 1000)})
    ensure_chat_folders(shared_folder, chat_id)

    group_key = generate_aes_key()
    wrapped = _wrap_group_key_for_users(shared_folder, group_key, [])
    save_chat_keys(shared_folder, chat_id, {"version": 1, "wrapped": wrapped})

    save_chat_meta_enc(shared_folder, chat_id, json.dumps({"type": "admin_chat"}).encode("utf-8"))
    return chat_id


def get_chat_meta(shared_folder: Path | str, chat_id: str) -> dict:
    return load_chat_meta(shared_folder, chat_id)


def is_chat_visible(shared_folder: Path | str, chat_id: str, fp16: str) -> bool:
    try:
        meta = load_chat_meta(shared_folder, chat_id)
    except FileNotFoundError:
        return False

    t = meta["type"]
    if t == "admin_chat":
        return is_admin(shared_folder, fp16)

    if t == "dm":
        enc = load_chat_meta_enc(shared_folder, chat_id)
        participants = json.loads(enc.decode("utf-8")).get("participants", [])
        if fp16 in participants:
            return True
        # Админ с правом чтения видит DM (как и в _prepare_chat_keys)
        return can_read_all_chats(shared_folder, fp16)

    try:
        keys = load_chat_keys(shared_folder, chat_id)
        return fp16 in keys.get("wrapped", {})
    except FileNotFoundError:
        return False


def list_user_chats(shared_folder: Path | str, fp16: str) -> list[dict]:
    meta_dir = Path(shared_folder) / ".meta"
    if not meta_dir.is_dir():
        return []

    result = []
    for entry in meta_dir.glob("*.json"):
        if entry.name.endswith(".keys.json"):
            continue
        chat_id = entry.stem

        if chat_id.startswith("fav_"):
            owner_fp = chat_id.replace("fav_", "")
            if owner_fp != fp16:
                continue

        if is_chat_visible(shared_folder, chat_id, fp16):
            try:
                result.append(load_chat_meta(shared_folder, chat_id))
            except (FileNotFoundError, ValueError):
                continue
    return sorted(result, key=lambda m: m.get("created_at", 0), reverse=True)


def get_chat_recipients(shared_folder: Path | str, chat_id: str) -> list[str]:
    meta = load_chat_meta(shared_folder, chat_id)
    t = meta["type"]

    if t == "admin_chat":
        return _get_reading_admin_fp16s(shared_folder)

    if t == "dm":
        enc = load_chat_meta_enc(shared_folder, chat_id)
        return json.loads(enc.decode("utf-8")).get("participants", [])

    try:
        keys = load_chat_keys(shared_folder, chat_id)
        recipients = list(keys.get("wrapped", {}).keys())
    except FileNotFoundError:
        recipients = []

    for admin_fp in _get_reading_admin_fp16s(shared_folder):
        if admin_fp not in recipients:
            recipients.append(admin_fp)
    return recipients


def list_all_chats(shared_folder: Path | str) -> list[dict]:
    meta_dir = Path(shared_folder) / ".meta"
    if not meta_dir.is_dir():
        return []

    result = []
    for entry in meta_dir.glob("*.json"):
        if entry.name.endswith(".keys.json"):
            continue
        try:
            result.append(load_chat_meta(shared_folder, entry.stem))
        except Exception:
            continue
    return sorted(result, key=lambda m: m.get("created_at", 0), reverse=True)


def get_all_users_fp16(shared_folder: Path | str) -> list[str]:
    keys_dir = Path(shared_folder) / ".keys"
    if not keys_dir.is_dir():
        return []
    return [f.name.replace(".pub.pem", "") for f in keys_dir.glob("*.pub.pem")]


# ============================================================================
# УПРАВЛЕНИЕ УЧАСТНИКАМИ ГРУППЫ
# ============================================================================

def _load_group_meta(shared_folder: Path | str, chat_id: str, by_fp16: str, by_priv_pem: str) -> tuple[dict, bytes, dict]:
    from src.core.crypto import unwrap_key, aes_decrypt, from_base64
    from src.storage.shared_store import load_chat_keys, load_chat_meta_enc

    keys = load_chat_keys(shared_folder, chat_id)
    wrapped = keys.get("wrapped", {})
    if by_fp16 not in wrapped:
        raise ValueError("У вас нет доступа к группе")

    group_key = unwrap_key(wrapped, by_fp16, by_priv_pem)
    enc = load_chat_meta_enc(shared_folder, chat_id)
    data = json.loads(enc.decode("utf-8"))
    aad = f"chat_id={chat_id}|meta".encode("utf-8")
    decrypted = aes_decrypt(group_key, from_base64(data["nonce"]), from_base64(data["ciphertext"]), aad=aad)
    meta = json.loads(decrypted.decode("utf-8"))

    return meta, group_key, keys


def _save_group_meta(shared_folder: Path | str, chat_id: str, meta: dict, group_key: bytes):
    from src.core.crypto import aes_encrypt, to_base64
    from src.storage.shared_store import save_chat_meta_enc

    aad = f"chat_id={chat_id}|meta".encode("utf-8")
    nonce, ct = aes_encrypt(group_key, json.dumps(meta).encode("utf-8"), aad=aad)
    save_chat_meta_enc(shared_folder, chat_id, json.dumps({"nonce": to_base64(nonce), "ciphertext": to_base64(ct)}).encode("utf-8"))


def remove_group_member(shared_folder: Path | str, chat_id: str, target_fp16: str, by_fp16: str, by_priv_pem: str) -> None:
    from src.storage.shared_store import save_chat_keys

    meta, group_key, keys = _load_group_meta(shared_folder, chat_id, by_fp16, by_priv_pem)

    is_creator = (meta.get("creator_fp16") == by_fp16)
    perms = meta.get("member_permissions", {}).get(by_fp16, {})
    can_remove = perms.get("can_remove_members", False)

    if not is_creator and not can_remove:
        raise ValueError("У вас нет прав на удаление участников")

    if target_fp16 == meta.get("creator_fp16"):
        raise ValueError("Нельзя удалить создателя группы")

    if target_fp16 not in meta.get("members", []):
        raise ValueError("Этот пользователь не в группе")

    meta["members"] = [m for m in meta["members"] if m != target_fp16]
    meta["admins"] = [a for a in meta.get("admins", []) if a != target_fp16]
    if "member_permissions" in meta:
        meta["member_permissions"].pop(target_fp16, None)

    wrapped = keys.get("wrapped", {})
    if target_fp16 in wrapped:
        del wrapped[target_fp16]
        save_chat_keys(shared_folder, chat_id, {"version": 1, "wrapped": wrapped})

    _save_group_meta(shared_folder, chat_id, meta, group_key)


def toggle_group_admin(shared_folder: Path | str, chat_id: str, target_fp16: str, by_fp16: str, by_priv_pem: str) -> None:
    meta, group_key, keys = _load_group_meta(shared_folder, chat_id, by_fp16, by_priv_pem)

    if meta.get("creator_fp16") != by_fp16:
        raise ValueError("Только создатель может менять админов")

    if target_fp16 not in meta.get("members", []):
        raise ValueError("Этот пользователь не в группе")

    if target_fp16 in meta.get("admins", []):
        meta["admins"] = [a for a in meta["admins"] if a != target_fp16]
    else:
        if "admins" not in meta:
            meta["admins"] = []
        meta["admins"].append(target_fp16)

    _save_group_meta(shared_folder, chat_id, meta, group_key)


def toggle_group_permission(shared_folder: Path | str, chat_id: str, target_fp16: str, perm: str, by_fp16: str, by_priv_pem: str) -> None:
    meta, group_key, keys = _load_group_meta(shared_folder, chat_id, by_fp16, by_priv_pem)

    if meta.get("creator_fp16") != by_fp16:
        raise ValueError("Только создатель может менять права")

    if target_fp16 not in meta.get("members", []):
        raise ValueError("Этот пользователь не в группе")

    if "member_permissions" not in meta:
        meta["member_permissions"] = {}
    if target_fp16 not in meta["member_permissions"]:
        meta["member_permissions"][target_fp16] = {}

    current = meta["member_permissions"][target_fp16].get(perm, False)
    meta["member_permissions"][target_fp16][perm] = not current

    _save_group_meta(shared_folder, chat_id, meta, group_key)


def can_edit_group_profile(shared_folder: Path | str, chat_id: str, fp16: str, priv_pem: str) -> bool:
    try:
        meta, _, _ = _load_group_meta(shared_folder, chat_id, fp16, priv_pem)
        if meta.get("creator_fp16") == fp16:
            return True
        perms = meta.get("member_permissions", {}).get(fp16, {})
        return perms.get("can_edit_profile", False)
    except Exception:
        return False


def delete_group_chat(shared_folder: Path | str, chat_id: str, by_fp16: str, by_priv_pem: str) -> None:
    """Полностью удаляет группу и все её файлы (только создатель)."""
    import shutil
    from src.storage.shared_store import chat_message_dir, chat_files_dir, chat_meta_path, chat_meta_enc_path, \
        chat_keys_path

    meta, _, _ = _load_group_meta(shared_folder, chat_id, by_fp16, by_priv_pem)
    if meta.get("creator_fp16") != by_fp16:
        raise ValueError("Только создатель может удалить группу")

    root = Path(shared_folder)

    msg_dir = chat_message_dir(root, chat_id)
    if msg_dir.exists():
        shutil.rmtree(msg_dir)

    files_dir = chat_files_dir(root, chat_id)
    if files_dir.exists():
        shutil.rmtree(files_dir)

    for p in [chat_meta_path(root, chat_id), chat_meta_enc_path(root, chat_id), chat_keys_path(root, chat_id)]:
        if p.exists():
            p.unlink()

    avatar = root / ".profiles" / f"{chat_id}.png"
    if avatar.exists():
        avatar.unlink()

    logger.info(f"Группа {chat_id} полностью удалена")