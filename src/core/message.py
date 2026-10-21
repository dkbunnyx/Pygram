"""Сообщения Pygram (защищённая версия v2).

Формат сообщения v2:
    {
      "version": 2,
      "sender_fp16": "...",
      "ts": 1234567890000,
      "msg_id": "<ts>_<sender_fp16>_<uuid8>",
      "nonce": "base64...",
      "ciphertext": "base64...",
      "signature": "base64...",       # подпись покрывает nonce||ct||"|"||msg_id
      "wrapped_keys": {fp: "base64..."}  # только для DM
    }

AAD v2: b"pygram-aad-v2|chat_id=...|sender=...|ts=...|msg_id=..."

Защита:
- msg_id включён в подпись → нельзя переименовать файл.
- AAD включает msg_id → нельзя переложить сообщение в другой контекст.
- Регулярная проверка подписи отправителя при каждом чтении.
- Лимиты на размер сообщения и файла.
- Инкрементальное чтение (read_new_messages) — не парсит известные файлы.
"""

from __future__ import annotations

import json
import time
import uuid
import shutil
from dataclasses import dataclass
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
    hybrid_encrypt,
    hybrid_decrypt,
    fingerprint,
    load_private_key,
    make_message_aad,
)
from src.core.admin import load_admins, can_read_all_chats
from src.storage.shared_store import (
    chat_message_dir,
    chat_files_dir,
    load_chat_keys,
    load_chat_meta,
    load_chat_meta_enc,
    load_pub_key_by_fp16,
    write_bytes_atomic,
)
from src.storage.local_db import get_db


# Максимальная ширина картинки при отправке (px). Высота — пропорционально.
MAX_IMAGE_WIDTH = 1920
# Качество JPEG при пересохранении (только если картинка была JPEG)
JPEG_QUALITY = 85
# Лимиты безопасности
MAX_TEXT_LENGTH = 100_000           # символов
MAX_FILE_SIZE = 100 * 1024 * 1024   # 100 МБ


@dataclass
class Message:
    chat_id: str
    sender_fp16: str
    text: str
    ts: int
    msg_id: str


# ============================================================================
# ВНУТРЕННИЕ ХЕЛПЕРЫ
# ============================================================================

def _get_group_key(
    shared_folder: Path | str,
    chat_id: str,
    my_fp16: str,
    my_priv_pem: str,
) -> bytes:
    """Разворачивает group_key для меня. Бросает, если нет обёртки."""
    keys_data = load_chat_keys(shared_folder, chat_id)
    wrapped_keys = keys_data.get("wrapped", {})
    if my_fp16 not in wrapped_keys:
        raise ValueError(f"У вас нет доступа к чату {chat_id}")
    return unwrap_key(wrapped_keys, my_fp16, my_priv_pem)


def _build_msg_id(ts: int, sender_fp16: str) -> str:
    """Формирует msg_id: <ts>_<sender_fp16>_<uuid8>."""
    msg_uuid = uuid.uuid4().hex[:8]
    return f"{ts}_{sender_fp16}_{msg_uuid}"


def _prepare_chat_keys(
    shared_folder: Path | str,
    chat_id: str,
    my_fp16: str,
    my_priv_pem: str,
) -> tuple[str, bytes | None, str | None]:
    """Возвращает (chat_type, group_key, my_full_fp).

    - Для DM: (dm, None, full_fp)
    - Для групп: (group, group_key, None)
    - Для админа без ключа: (group, None, None) — читать не сможет, но не падаем.

    Raises:
        ValueError: если у пользователя нет доступа.
    """
    meta = load_chat_meta(shared_folder, chat_id)
    chat_type = meta["type"]

    if chat_type == "dm":
        enc = load_chat_meta_enc(shared_folder, chat_id)
        participants = json.loads(enc.decode("utf-8")).get("participants", [])
        if my_fp16 not in participants and not can_read_all_chats(shared_folder, my_fp16):
            raise ValueError(f"У вас нет доступа к чату {chat_id}")
        my_pub_pem = load_private_key(my_priv_pem).publickey().export_key().decode("ascii")
        return chat_type, None, fingerprint(my_pub_pem)

    # group / favorites / admin_chat
    try:
        group_key = _get_group_key(shared_folder, chat_id, my_fp16, my_priv_pem)
    except ValueError:
        if can_read_all_chats(shared_folder, my_fp16):
            logger.warning(f"Админ {my_fp16} без ключа от {chat_id}")
            return chat_type, None, None
        raise
    return chat_type, group_key, None


# ============================================================================
# ОТПРАВКА
# ============================================================================

def send_message(
    shared_folder: Path | str,
    chat_id: str,
    sender_fp16: str,
    sender_priv_pem: str,
    text: str,
) -> str:
    """Шифрует и сохраняет сообщение. Возвращает msg_id.

    Raises:
        ValueError: если текст пуст, слишком длинный, или нет получателей.
    """
    if not text or not isinstance(text, str):
        raise ValueError("Текст сообщения не может быть пустым")
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(f"Сообщение слишком длинное (макс {MAX_TEXT_LENGTH} символов)")

    meta = load_chat_meta(shared_folder, chat_id)
    chat_type = meta["type"]

    ts = int(time.time() * 1000)
    msg_id = _build_msg_id(ts, sender_fp16)

    # AAD v2 — включает msg_id
    aad = make_message_aad(chat_id, sender_fp16, ts, msg_id)

    if chat_type == "dm":
        # DM: гибридное шифрование для участников + админов с правом чтения
        enc = load_chat_meta_enc(shared_folder, chat_id)
        participants = json.loads(enc.decode("utf-8")).get("participants", [])

        admins_data = load_admins(shared_folder)
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
                # Пользователь без pub_key — пропускаем (не должен получать)
                pass

        if not recipients:
            raise ValueError("Нет получателей с известными ключами")

        pkg = hybrid_encrypt(text.encode("utf-8"), recipients, aad=aad)

        # Подпись покрывает nonce||ct||"|"||msg_id — нельзя подменить msg_id
        sign_payload = (
            from_base64(pkg["nonce"])
            + from_base64(pkg["ciphertext"])
            + b"|"
            + msg_id.encode("utf-8")
        )
        container = {
            "version": 2,
            "sender_fp16": sender_fp16,
            "ts": ts,
            "msg_id": msg_id,
            "nonce": pkg["nonce"],
            "ciphertext": pkg["ciphertext"],
            "wrapped_keys": pkg["wrapped_keys"],
            "signature": to_base64(rsa_sign(sender_priv_pem, sign_payload)),
        }
    else:
        # Группа / favorites / admin_chat: AES-GCM с group_key
        group_key = _get_group_key(shared_folder, chat_id, sender_fp16, sender_priv_pem)
        nonce, ciphertext = aes_encrypt(group_key, text.encode("utf-8"), aad=aad)
        sign_payload = nonce + ciphertext + b"|" + msg_id.encode("utf-8")
        signature = rsa_sign(sender_priv_pem, sign_payload)

        container = {
            "version": 2,
            "sender_fp16": sender_fp16,
            "ts": ts,
            "msg_id": msg_id,
            "nonce": to_base64(nonce),
            "ciphertext": to_base64(ciphertext),
            "signature": to_base64(signature),
        }

    msg_dir = chat_message_dir(shared_folder, chat_id)
    msg_dir.mkdir(parents=True, exist_ok=True)
    write_bytes_atomic(msg_dir / f"{msg_id}.bin", json.dumps(container).encode("utf-8"))

    return msg_id


# ============================================================================
# ОТПРАВКА ФАЙЛОВ
# ============================================================================

def _process_image(file_path: Path, dest_path: Path) -> None:
    """Ресайзит картинку (если нужно) и сохраняет в ИСХОДНОМ формате."""
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


def send_file(
    shared_folder: Path | str,
    chat_id: str,
    sender_fp16: str,
    sender_priv_pem: str,
    file_path: str | Path,
) -> str:
    """Копирует файл в шару и отправляет сообщение [FILE]...[/FILE]."""
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


# ============================================================================
# ЧТЕНИЕ (единая реализация — без дублирования!)
# ============================================================================

def _decrypt_message_file(
    shared_folder: Path | str,
    chat_id: str,
    my_fp16: str,
    my_priv_pem: str,
    msg_file: Path,
    chat_type: str,
    group_key: bytes | None,
    my_full_fp: str | None,
) -> Message | None:
    """Расшифровывает один .bin. Возвращает None при любой ошибке.

    Не бросает исключений — это критично для инкрементального чтения,
    где один битый файл не должен ломать всю пачку.
    """
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

        # v2 AAD — совместимость со старой схемой v1
        if version >= 2:
            aad = make_message_aad(chat_id, sender, ts, msg_id)
        else:
            aad = f"chat_id={chat_id}|sender={sender}|ts={ts}".encode("utf-8")

        if chat_type == "dm":
            if my_full_fp is None:
                return None

            pkg = {
                "nonce": container["nonce"],
                "ciphertext": container["ciphertext"],
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


def read_messages(
    shared_folder: Path | str,
    chat_id: str,
    my_fp16: str,
    my_priv_pem: str,
) -> list[Message]:
    """Читает ВСЮ историю чата (отсортировано по ts).

    Raises:
        ValueError: если нет доступа к чату.
    """
    chat_type, group_key, my_full_fp = _prepare_chat_keys(
        shared_folder, chat_id, my_fp16, my_priv_pem
    )

    msg_dir = chat_message_dir(shared_folder, chat_id)
    if not msg_dir.is_dir():
        return []

    messages: list[Message] = []
    for msg_file in msg_dir.glob("*.bin"):
        m = _decrypt_message_file(
            shared_folder, chat_id, my_fp16, my_priv_pem,
            msg_file, chat_type, group_key, my_full_fp,
        )
        if m is not None:
            messages.append(m)

    messages.sort(key=lambda m: m.ts)
    return messages


def read_new_messages(
    shared_folder: Path | str,
    chat_id: str,
    my_fp16: str,
    my_priv_pem: str,
    known_msg_ids: set[str],
) -> list[Message]:
    """Инкрементальное чтение: только файлы, которых нет в known_msg_ids.

    Не парсит уже известные .bin — это в разы быстрее для активного чата.
    """
    chat_type, group_key, my_full_fp = _prepare_chat_keys(
        shared_folder, chat_id, my_fp16, my_priv_pem
    )

    msg_dir = chat_message_dir(shared_folder, chat_id)
    if not msg_dir.is_dir():
        return []

    new_msgs: list[Message] = []
    for msg_file in msg_dir.glob("*.bin"):
        if msg_file.stem in known_msg_ids:
            continue
        m = _decrypt_message_file(
            shared_folder, chat_id, my_fp16, my_priv_pem,
            msg_file, chat_type, group_key, my_full_fp,
        )
        if m is not None:
            new_msgs.append(m)

    new_msgs.sort(key=lambda m: m.ts)
    return new_msgs


# ============================================================================
# BACKWARDS-COMPAT
# ============================================================================

def _read_single_message(
    shared_folder: Path | str,
    chat_id: str,
    my_fp16: str,
    my_priv_pem: str,
    msg_file: Path,
) -> Message | None:
    """Старый API (для совместимости). Используй read_new_messages."""
    chat_type, group_key, my_full_fp = _prepare_chat_keys(
        shared_folder, chat_id, my_fp16, my_priv_pem
    )
    return _decrypt_message_file(
        shared_folder, chat_id, my_fp16, my_priv_pem,
        msg_file, chat_type, group_key, my_full_fp,
    )


# ============================================================================
# СИНХРОНИЗАЦИЯ С ЛОКАЛЬНОЙ БД (для быстрого UI)
# ============================================================================

def sync_messages_to_db(shared_folder: Path | str, chat_id: str, my_fp16: str, my_priv_pem: str):
    """Синхронизирует новые сообщения из шары в локальную SQLite.

    Читает только те файлы, которых еще нет в БД (инкрементально).
    Используется фоновым потоком ChatLoadWorker в UI.
    """
    db = get_db()

    # 1. Получаем ID сообщений, которые уже есть в локальной БД
    existing_msgs = db.get_messages(chat_id)
    known_ids = {m["msg_id"] for m in existing_msgs}

    # 2. Читаем только новые (которых нет в known_ids)
    new_msgs = read_new_messages(shared_folder, chat_id, my_fp16, my_priv_pem, known_ids)

    # 3. Сохраняем в БД
    for msg in new_msgs:
        db.save_message(msg.msg_id, chat_id, msg.sender_fp16, msg.text, msg.ts)
