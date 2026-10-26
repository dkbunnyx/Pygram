"""Сообщения Pygram (защищённая версия v2)."""

from __future__ import annotations

import json
import time
import uuid
import shutil
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from src.core.crypto import (
    aes_decrypt, aes_encrypt, from_base64, rsa_sign, rsa_verify, to_base64,
    unwrap_key, hybrid_encrypt, hybrid_decrypt, fingerprint, load_private_key,
    make_message_aad,
)
# П.2: verified — подписи проверены. load_admins (сырой) НЕ используем.
from src.core.admin import load_admins_verified, can_read_all_chats
from src.storage.shared_store import (
    chat_message_dir, chat_files_dir, load_chat_keys, load_chat_meta,
    load_chat_meta_enc, load_pub_key_by_fp16, write_bytes_atomic,
)


MAX_IMAGE_WIDTH = 1920
JPEG_QUALITY = 85
MAX_TEXT_LENGTH = 100_000
MAX_FILE_SIZE = 100 * 1024 * 1024


@dataclass
class Message:
    chat_id: str
    sender_fp16: str
    text: str
    ts: int
    msg_id: str


def _get_group_key(shared_folder, chat_id, my_fp16, my_priv_pem) -> bytes:
    keys_data = load_chat_keys(shared_folder, chat_id)
    wrapped_keys = keys_data.get("wrapped", {})
    if my_fp16 not in wrapped_keys:
        raise ValueError(f"У вас нет доступа к чату {chat_id}")
    return unwrap_key(wrapped_keys, my_fp16, my_priv_pem)


def _build_msg_id(ts: int, sender_fp16: str) -> str:
    msg_uuid = uuid.uuid4().hex[:8]
    return f"{ts}_{sender_fp16}_{msg_uuid}"


def _prepare_chat_keys(shared_folder, chat_id, my_fp16, my_priv_pem):
    meta = load_chat_meta(shared_folder, chat_id)
    chat_type = meta["type"]

    if chat_type == "dm":
        enc = load_chat_meta_enc(shared_folder, chat_id)
        participants = json.loads(enc.decode("utf-8")).get("participants", [])
        if my_fp16 not in participants and not can_read_all_chats(shared_folder, my_fp16):
            raise ValueError(f"У вас нет доступа к чату {chat_id}")
        my_pub_pem = load_private_key(my_priv_pem).publickey().export_key().decode("ascii")
        return chat_type, None, fingerprint(my_pub_pem)

    try:
        group_key = _get_group_key(shared_folder, chat_id, my_fp16, my_priv_pem)
    except ValueError:
        if can_read_all_chats(shared_folder, my_fp16):
            logger.warning(f"Админ {my_fp16} без ключа от {chat_id}")
            return chat_type, None, None
        raise
    return chat_type, group_key, None


def send_message(shared_folder, chat_id, sender_fp16, sender_priv_pem, text) -> str:
    if not text or not isinstance(text, str):
        raise ValueError("Текст сообщения не может быть пустым")
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(f"Сообщение слишком длинное (макс {MAX_TEXT_LENGTH} символов)")

    meta = load_chat_meta(shared_folder, chat_id)
    chat_type = meta["type"]

    ts = int(time.time() * 1000)
    msg_id = _build_msg_id(ts, sender_fp16)
    aad = make_message_aad(chat_id, sender_fp16, ts, msg_id)

    if chat_type == "dm":
        enc = load_chat_meta_enc(shared_folder, chat_id)
        participants = json.loads(enc.decode("utf-8")).get("participants", [])

        # ВАЖНО: verified — подписи проверены. Иначе злоумышленник,
        # дописавший себя в .admins/list.json без подписи, получит ключи.
        admins_data = load_admins_verified(shared_folder)
        admin_fps = [
            a["fp16"] for a in admins_data
            if a.get("is_super") or a.get("can_read_all_chats")
        ]

        all_recipients = set(participants) | set(admin_fps)
        recipients: dict[str, str] = {}
        for p_fp in all_recipients:
            try:
                recipients[p_fp] = load_pub_key_by_fp16(shared_folder, p_fp)
            except FileNotFoundError:
                pass

        if not recipients:
            raise ValueError("Нет получателей с известными ключами")

        pkg = hybrid_encrypt(text.encode("utf-8"), recipients, aad=aad)

        sign_payload = (
            from_base64(pkg["nonce"])
            + from_base64(pkg["ciphertext"])
            + b"|"
            + msg_id.encode("utf-8")
        )
        container = {
            "version": 2, "sender_fp16": sender_fp16, "ts": ts, "msg_id": msg_id,
            "nonce": pkg["nonce"], "ciphertext": pkg["ciphertext"],
            "wrapped_keys": pkg["wrapped_keys"],
            "signature": to_base64(rsa_sign(sender_priv_pem, sign_payload)),
        }
    else:
        group_key = _get_group_key(shared_folder, chat_id, sender_fp16, sender_priv_pem)
        nonce, ciphertext = aes_encrypt(group_key, text.encode("utf-8"), aad=aad)
        sign_payload = nonce + ciphertext + b"|" + msg_id.encode("utf-8")
        signature = rsa_sign(sender_priv_pem, sign_payload)

        container = {
            "version": 2, "sender_fp16": sender_fp16, "ts": ts, "msg_id": msg_id,
            "nonce": to_base64(nonce), "ciphertext": to_base64(ciphertext),
            "signature": to_base64(signature),
        }

    msg_dir = chat_message_dir(shared_folder, chat_id)
    msg_dir.mkdir(parents=True, exist_ok=True)
    write_bytes_atomic(msg_dir / f"{msg_id}.bin", json.dumps(container).encode("utf-8"))

    return msg_id


def _process_image(file_path: Path, dest_path: Path) -> None:
    from PIL import Image
    img = Image.open(file_path)
    ext = file_path.suffix.lower()

    if img.width > MAX_IMAGE_WIDTH:
        ratio = MAX_IMAGE_WIDTH / img.width
        new_size = (MAX_IMAGE_WIDTH, max(1, int(img.height * ratio)))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    if ext == ".png":
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            img.save(dest_path, "PNG", optimize=True)
        else:
            img.convert("RGB").save(dest_path, "PNG", optimize=True)
    elif ext in (".jpg", ".jpeg"):
        img.convert("RGB").save(dest_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
    else:
        shutil.copy2(file_path, dest_path)


def send_file(shared_folder, chat_id, sender_fp16, sender_priv_pem, file_path) -> str:
    file_path = Path(file_path)
    if not file_path.is_file():
        raise ValueError("Файл не найден")
    if file_path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(f"Файл больше {MAX_FILE_SIZE // (1024 * 1024)} МБ")

    files_dir = chat_files_dir(shared_folder, chat_id)
    files_dir.mkdir(parents=True, exist_ok=True)

    original_name = file_path.name
    ext = file_path.suffix.lower()
    stored_name = f"{uuid.uuid4().hex}_{original_name}"
    dest_path = files_dir / stored_name

    if ext in ('.png', '.jpg', '.jpeg'):
        try:
            _process_image(file_path, dest_path)
        except Exception as e:
            logger.error(f"Ошибка сжатия картинки {original_name}: {e}. Копирую как есть.")
            shutil.copy2(file_path, dest_path)
    else:
        shutil.copy2(file_path, dest_path)

    text = f"[FILE]{stored_name}|{original_name}[/FILE]"
    return send_message(shared_folder, chat_id, sender_fp16, sender_priv_pem, text)


def _decrypt_message_file(shared_folder, chat_id, my_fp16, my_priv_pem, msg_file, chat_type, group_key, my_full_fp) -> Message | None:
    try:
        container = json.loads(msg_file.read_text(encoding="utf-8"))
        sender = container["sender_fp16"]
        ts = container["ts"]
        signature = from_base64(container["signature"])
        msg_id = container.get("msg_id", msg_file.stem)
        version = container.get("version", 1)

        try:
            sender_pub = load_pub_key_by_fp16(shared_folder, sender)
        except FileNotFoundError:
            logger.warning(f"Отправитель {sender} не найден, пропуск {msg_file.name}")
            return None

        if version >= 2:
            aad = make_message_aad(chat_id, sender, ts, msg_id)
        else:
            aad = f"chat_id={chat_id}|sender={sender}|ts={ts}".encode("utf-8")

        if chat_type == "dm":
            if my_full_fp is None:
                return None
            pkg = {
                "nonce": container["nonce"], "ciphertext": container["ciphertext"],
                "wrapped_keys": container["wrapped_keys"],
            }
            nonce_b = from_base64(pkg["nonce"])
            ct_b = from_base64(pkg["ciphertext"])

            if version >= 2:
                sign_payload = nonce_b + ct_b + b"|" + msg_id.encode("utf-8")
            else:
                sign_payload = nonce_b + ct_b

            if not rsa_verify(sender_pub, sign_payload, signature):
                logger.warning(f"Невалидная подпись (DM): {msg_file.name}")
                return None

            plaintext = hybrid_decrypt(pkg, my_full_fp, my_priv_pem, aad=aad)
        else:
            if group_key is None:
                return None
            nonce = from_base64(container["nonce"])
            ciphertext = from_base64(container["ciphertext"])

            if version >= 2:
                sign_payload = nonce + ciphertext + b"|" + msg_id.encode("utf-8")
            else:
                sign_payload = nonce + ciphertext

            if not rsa_verify(sender_pub, sign_payload, signature):
                logger.warning(f"Невалидная подпись (группа): {msg_file.name}")
                return None

            plaintext = aes_decrypt(group_key, nonce, ciphertext, aad=aad)

        return Message(chat_id, sender, plaintext.decode("utf-8"), ts, msg_file.stem)
    except Exception as e:
        logger.error(f"Ошибка чтения {msg_file.name}: {e}")
        return None


def read_messages(shared_folder, chat_id, my_fp16, my_priv_pem) -> list[Message]:
    chat_type, group_key, my_full_fp = _prepare_chat_keys(shared_folder, chat_id, my_fp16, my_priv_pem)
    msg_dir = chat_message_dir(shared_folder, chat_id)
    if not msg_dir.is_dir():
        return []

    messages = []
    for msg_file in msg_dir.glob("*.bin"):
        m = _decrypt_message_file(shared_folder, chat_id, my_fp16, my_priv_pem, msg_file, chat_type, group_key, my_full_fp)
        if m is not None:
            messages.append(m)

    messages.sort(key=lambda m: m.ts)
    return messages


def read_new_messages(shared_folder, chat_id, my_fp16, my_priv_pem, known_msg_ids) -> list[Message]:
    chat_type, group_key, my_full_fp = _prepare_chat_keys(shared_folder, chat_id, my_fp16, my_priv_pem)
    msg_dir = chat_message_dir(shared_folder, chat_id)
    if not msg_dir.is_dir():
        return []

    new_msgs = []
    for msg_file in msg_dir.glob("*.bin"):
        if msg_file.stem in known_msg_ids:
            continue
        m = _decrypt_message_file(shared_folder, chat_id, my_fp16, my_priv_pem, msg_file, chat_type, group_key, my_full_fp)
        if m is not None:
            new_msgs.append(m)

    new_msgs.sort(key=lambda m: m.ts)
    return new_msgs


def _read_single_message(shared_folder, chat_id, my_fp16, my_priv_pem, msg_file):
    chat_type, group_key, my_full_fp = _prepare_chat_keys(shared_folder, chat_id, my_fp16, my_priv_pem)
    return _decrypt_message_file(shared_folder, chat_id, my_fp16, my_priv_pem, msg_file, chat_type, group_key, my_full_fp)


# ============================================================================
# СИНХРОНИЗАЦИЯ С ЛОКАЛЬНОЙ БД
# ============================================================================

def sync_messages_to_db(shared_folder, chat_id, my_fp16, my_priv_pem):
    """Синхронизирует новые сообщения из шары в локальную SQLite.
    Также удаляет из локальной БД те сообщения, файлов которых больше нет на шаре.
    """
    from src.storage.local_db import LocalDB
    from src.storage.shared_store import chat_message_dir

    db = LocalDB()

    # 1. Получаем список файлов, которые РЕАЛЬНО есть на шаре
    msg_dir = chat_message_dir(shared_folder, chat_id)
    actual_msg_ids = set()
    if msg_dir.is_dir():
        actual_msg_ids = {f.stem for f in msg_dir.glob("*.bin")}

    # 2. Получаем то, что лежит в локальной БД
    existing_msgs = db.get_messages(chat_id)
    known_ids = {m["msg_id"] for m in existing_msgs}

    # 3. УДАЛЕНИЕ: если сообщение есть в БД, но файла на шаре нет — удаляем из БД
    for m in existing_msgs:
        mid = m["msg_id"]
        # Игнорируем временные сообщения (pending_), которые еще не отправились
        if mid.startswith("pending_"):
            continue

        if mid not in actual_msg_ids:
            db.delete_message(mid)
            logger.debug(f"Сообщение {mid} удалено с шары, чистим локальную БД")

    # 4. ДОБАВЛЕНИЕ: читаем новые сообщения с шары
    new_msgs = read_new_messages(shared_folder, chat_id, my_fp16, my_priv_pem, known_ids)
    for msg in new_msgs:
        db.save_message(msg.msg_id, chat_id, msg.sender_fp16, msg.text, msg.ts)