"""Сообщения Pygram."""

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
    unwrap_key, hybrid_encrypt, hybrid_decrypt, fingerprint, load_private_key
)
from src.core.admin import load_admins, can_read_all_chats
from src.storage.shared_store import (
    chat_message_dir, chat_files_dir, load_chat_keys, load_chat_meta, load_chat_meta_enc,
    load_pub_key_by_fp16, write_bytes_atomic
)


@dataclass
class Message:
    chat_id: str
    sender_fp16: str
    text: str
    ts: int
    msg_id: str


def _get_group_key(shared_folder: Path | str, chat_id: str, my_fp16: str, my_priv_pem: str) -> bytes:
    keys_data = load_chat_keys(shared_folder, chat_id)
    wrapped_keys = keys_data.get("wrapped", {})
    if my_fp16 not in wrapped_keys:
        raise ValueError(f"У вас нет доступа к чату {chat_id}")
    return unwrap_key(wrapped_keys, my_fp16, my_priv_pem)


def send_message(shared_folder: Path | str, chat_id: str, sender_fp16: str, sender_priv_pem: str, text: str) -> str:
    if not text or not isinstance(text, str):
        raise ValueError("Текст сообщения не может быть пустым")

    meta = load_chat_meta(shared_folder, chat_id)
    chat_type = meta["type"]

    ts = int(time.time() * 1000)
    msg_uuid = str(uuid.uuid4())[:8]
    msg_id = f"{ts}_{sender_fp16}_{msg_uuid}"

    aad = f"chat_id={chat_id}|sender={sender_fp16}|ts={ts}".encode("utf-8")

    if chat_type == "dm":
        enc = load_chat_meta_enc(shared_folder, chat_id)
        participants = json.loads(enc.decode("utf-8")).get("participants", [])

        # ЧЕСТНОСТЬ: Заворачиваем ключи не только для участников, но и для всех админов с правами
        admins_data = load_admins(shared_folder)
        admin_fps = [a["fp16"] for a in admins_data if a.get("is_super") or a.get("can_read_all_chats")]

        all_recipients = set(participants) | set(admin_fps)

        recipients = {}
        for p_fp in all_recipients:
            try:
                recipients[p_fp] = load_pub_key_by_fp16(shared_folder, p_fp)
            except FileNotFoundError:
                pass

        pkg = hybrid_encrypt(text.encode("utf-8"), recipients, aad=aad)
        container = {
            "version": 1, "sender_fp16": sender_fp16, "ts": ts,
            "nonce": pkg["nonce"], "ciphertext": pkg["ciphertext"],
            "wrapped_keys": pkg["wrapped_keys"],
        }
        data_to_sign = from_base64(pkg["nonce"]) + from_base64(pkg["ciphertext"])
        container["signature"] = to_base64(rsa_sign(sender_priv_pem, data_to_sign))
    else:
        group_key = _get_group_key(shared_folder, chat_id, sender_fp16, sender_priv_pem)
        nonce, ciphertext = aes_encrypt(group_key, text.encode("utf-8"), aad=aad)
        signature = rsa_sign(sender_priv_pem, nonce + ciphertext)

        container = {
            "version": 1, "sender_fp16": sender_fp16, "ts": ts,
            "nonce": to_base64(nonce), "ciphertext": to_base64(ciphertext),
            "signature": to_base64(signature),
        }

    msg_dir = chat_message_dir(shared_folder, chat_id)
    msg_dir.mkdir(parents=True, exist_ok=True)
    write_bytes_atomic(msg_dir / f"{msg_id}.bin", json.dumps(container).encode("utf-8"))

    return msg_id


def send_file(shared_folder: Path | str, chat_id: str, sender_fp16: str, sender_priv_pem: str,
              file_path: str | Path) -> str:
    file_path = Path(file_path)
    if not file_path.is_file():
        raise ValueError("Файл не найден")

    files_dir = chat_files_dir(shared_folder, chat_id)
    files_dir.mkdir(parents=True, exist_ok=True)

    original_name = file_path.name
    ext = file_path.suffix.lower()

    # Если это картинка — сжимаем
    if ext in ('.png', '.jpg', '.jpeg'):
        try:
            from PIL import Image
            import io

            img = Image.open(file_path)
            # Если картинка больше 1920px по ширине, уменьшаем
            if img.width > 1920:
                ratio = 1920 / img.width
                new_size = (1920, int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            new_filename = f"{uuid.uuid4().hex}_{original_name}"
            dest_path = files_dir / new_filename
            # Сохраняем как JPEG с качеством 85 (чтобы уменьшить вес)
            img.convert('RGB').save(dest_path, "JPEG", quality=85)
        except Exception as e:
            logger.error(f"Ошибка сжатия картинки: {e}")
            # Если не удалось сжать, копируем как есть
            new_filename = f"{uuid.uuid4().hex}_{original_name}"
            dest_path = files_dir / new_filename
            shutil.copy2(file_path, dest_path)
    else:
        # Обычный файл — просто копируем
        new_filename = f"{uuid.uuid4().hex}_{original_name}"
        dest_path = files_dir / new_filename
        shutil.copy2(file_path, dest_path)

    text = f"[FILE]{new_filename}|{original_name}[/FILE]"
    return send_message(shared_folder, chat_id, sender_fp16, sender_priv_pem, text)


def read_messages(shared_folder: Path | str, chat_id: str, my_fp16: str, my_priv_pem: str) -> list[Message]:
    meta = load_chat_meta(shared_folder, chat_id)
    chat_type = meta["type"]

    # 1. Проверка для DM
    if chat_type == "dm":
        enc = load_chat_meta_enc(shared_folder, chat_id)
        participants = json.loads(enc.decode("utf-8")).get("participants", [])

        if my_fp16 not in participants and not can_read_all_chats(shared_folder, my_fp16):
            raise ValueError(f"У вас нет доступа к чату {chat_id}")

    # 2. Получение ключа для групп и избранного
    group_key = None
    if chat_type != "dm":
        try:
            group_key = _get_group_key(shared_folder, chat_id, my_fp16, my_priv_pem)
        except ValueError:
            # Если это админ, но у него нет ключа (например, старое избранное) — просто возвращаем пустой список
            if can_read_all_chats(shared_folder, my_fp16):
                logger.warning(f"Админ {my_fp16} без ключа от {chat_id}. Пропускаем.")
                return []
            raise

    # 3. Чтение файлов
    msg_dir = chat_message_dir(shared_folder, chat_id)
    if not msg_dir.is_dir(): return []

    messages = []
    for msg_file in msg_dir.glob("*.bin"):
        try:
            container = json.loads(msg_file.read_text(encoding="utf-8"))
            sender = container["sender_fp16"]
            ts = container["ts"]
            signature = from_base64(container["signature"])

            try:
                sender_pub = load_pub_key_by_fp16(shared_folder, sender)
            except FileNotFoundError:
                continue

            aad = f"chat_id={chat_id}|sender={sender}|ts={ts}".encode("utf-8")

            if chat_type == "dm":
                pkg = {
                    "nonce": container["nonce"], "ciphertext": container["ciphertext"],
                    "wrapped_keys": container["wrapped_keys"]
                }
                data_to_check = from_base64(pkg["nonce"]) + from_base64(pkg["ciphertext"])
                if not rsa_verify(sender_pub, data_to_check, signature):
                    continue

                my_pub_pem = load_private_key(my_priv_pem).publickey().export_key().decode("ascii")
                my_full_fp = fingerprint(my_pub_pem)

                plaintext = hybrid_decrypt(pkg, my_full_fp, my_priv_pem, aad=aad)
            else:
                nonce = from_base64(container["nonce"])
                ciphertext = from_base64(container["ciphertext"])
                if not rsa_verify(sender_pub, nonce + ciphertext, signature):
                    continue
                plaintext = aes_decrypt(group_key, nonce, ciphertext, aad=aad)

            messages.append(Message(chat_id, sender, plaintext.decode("utf-8"), ts, msg_file.stem))
        except Exception as e:
            logger.error(f"Ошибка чтения {msg_file.name}: {e}")

    return sorted(messages, key=lambda m: m.ts)