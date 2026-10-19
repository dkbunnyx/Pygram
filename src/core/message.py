"""Сообщения Pygram: отправка, чтение, шифрование.

Схема:
    1. Сообщение шифруется group_key (AES-256-GCM).
    2. Шифротекст подписывается RSA-PSS приватником отправителя.
    3. Сохраняется в message/<chat_id>/<ts>_<fp16>_<uuid>.bin
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from loguru import logger

from src.core.crypto import (
    aes_decrypt,
    aes_encrypt,
    from_base64,
    rsa_sign,
    rsa_verify,
    to_base64,
    unwrap_key,
)
from src.storage.shared_store import (
    chat_message_dir,
    load_chat_keys,
    load_pub_key_by_fp16,
    write_bytes_atomic,
)


class Message:
    """Расшифрованное сообщение."""

    def __init__(
        self,
        chat_id: str,
        sender_fp16: str,
        text: str,
        ts: int,
        msg_id: str,
    ):
        self.chat_id = chat_id
        self.sender_fp16 = sender_fp16
        self.text = text
        self.ts = ts
        self.msg_id = msg_id

    def __repr__(self) -> str:
        return f"<Message {self.msg_id} from {self.sender_fp16}: {self.text[:20]}>"


def _get_group_key(
    shared_folder: Path | str,
    chat_id: str,
    my_fp16: str,
    my_priv_pem: str,
) -> bytes:
    """Достаёт и расшифровывает group_key для текущего пользователя."""
    keys_data = load_chat_keys(shared_folder, chat_id)
    wrapped_keys = keys_data.get("wrapped", {})

    if my_fp16 not in wrapped_keys:
        raise ValueError(f"У вас нет доступа к чату {chat_id}")

    return unwrap_key(wrapped_keys, my_fp16, my_priv_pem)


def send_message(
    shared_folder: Path | str,
    chat_id: str,
    sender_fp16: str,
    sender_priv_pem: str,
    text: str,
) -> str:
    """Шифрует, подписывает и сохраняет сообщение.

    Returns:
        msg_id (имя файла без .bin).
    """
    if not text or not isinstance(text, str):
        raise ValueError("Текст сообщения не может быть пустым")

    group_key = _get_group_key(shared_folder, chat_id, sender_fp16, sender_priv_pem)

    ts = int(time.time() * 1000)
    msg_uuid = str(uuid.uuid4())[:8]
    msg_id = f"{ts}_{sender_fp16}_{msg_uuid}"

    # Шифрование
    aad = f"chat_id={chat_id}|sender={sender_fp16}|ts={ts}".encode("utf-8")
    nonce, ciphertext = aes_encrypt(group_key, text.encode("utf-8"), aad=aad)

    # Подпись (подписываем nonce+ciphertext, чтобы никто не подменил)
    data_to_sign = nonce + ciphertext
    signature = rsa_sign(sender_priv_pem, data_to_sign)

    container = {
        "version": 1,
        "sender_fp16": sender_fp16,
        "ts": ts,
        "nonce": to_base64(nonce),
        "ciphertext": to_base64(ciphertext),
        "signature": to_base64(signature),
    }

    # Сохранение
    msg_dir = chat_message_dir(shared_folder, chat_id)
    msg_dir.mkdir(parents=True, exist_ok=True)
    msg_path = msg_dir / f"{msg_id}.bin"

    write_bytes_atomic(msg_path, json.dumps(container).encode("utf-8"))
    logger.debug(f"Сообщение отправлено: {chat_id}/{msg_id}")
    return msg_id


def read_messages(
    shared_folder: Path | str,
    chat_id: str,
    my_fp16: str,
    my_priv_pem: str,
) -> list[Message]:
    """Читает, расшифровывает и проверяет все сообщения в чате."""
    group_key = _get_group_key(shared_folder, chat_id, my_fp16, my_priv_pem)

    msg_dir = chat_message_dir(shared_folder, chat_id)
    if not msg_dir.is_dir():
        return []

    messages = []
    for msg_file in msg_dir.glob("*.bin"):
        try:
            container = json.loads(msg_file.read_text(encoding="utf-8"))
            sender = container["sender_fp16"]
            ts = container["ts"]
            nonce = from_base64(container["nonce"])
            ciphertext = from_base64(container["ciphertext"])
            signature = from_base64(container["signature"])

            # 1. Проверяем подпись
            try:
                sender_pub = load_pub_key_by_fp16(shared_folder, sender)
            except FileNotFoundError:
                logger.warning(f"Ключ отправителя {sender} не найден")
                continue

            if not rsa_verify(sender_pub, nonce + ciphertext, signature):
                logger.warning(f"Подпись не совпала (подмена?): {msg_file.name}")
                continue

            # 2. Расшифровываем
            aad = f"chat_id={chat_id}|sender={sender}|ts={ts}".encode("utf-8")
            plaintext = aes_decrypt(group_key, nonce, ciphertext, aad=aad)

            messages.append(Message(
                chat_id=chat_id,
                sender_fp16=sender,
                text=plaintext.decode("utf-8"),
                ts=ts,
                msg_id=msg_file.stem,
            ))
        except Exception as e:
            logger.error(f"Ошибка чтения сообщения {msg_file.name}: {e}")
            continue

    return sorted(messages, key=lambda m: m.ts)