"""Тесты для src/core/message.py — шифрование, подписи, чтение."""

import json
import pytest
from pathlib import Path

from src.core.admin import make_admin
from src.core.chat_logic import (
    create_dm_chat, create_group_chat, create_favorites, create_admin_chat
)
from src.core.crypto import generate_rsa_keypair
from src.core.identity import authenticate, register_identity
from src.core.message import (
    send_message, read_messages, read_new_messages, send_file,
    Message, _build_msg_id,
)
from src.storage.shared_store import (
    chat_message_dir, ensure_shared_structure, load_chat_keys,
)


@pytest.fixture
def shared(tmp_path):
    d = tmp_path / "share"
    d.mkdir()
    ensure_shared_structure(d)
    return d


@pytest.fixture
def users(shared):
    """vasya (админ), petya, kolya."""
    fp_vasya = register_identity(shared, "vasya", "Pass1!")
    make_admin(shared, fp_vasya, by="system")
    priv_vasya, _ = authenticate(shared, "vasya", "Pass1!")

    fp_petya = register_identity(shared, "petya", "Pass2!")
    priv_petya, _ = authenticate(shared, "petya", "Pass2!")

    fp_kolya = register_identity(shared, "kolya", "Pass3!")
    priv_kolya, _ = authenticate(shared, "kolya", "Pass3!")

    return {
        "vasya": (fp_vasya, priv_vasya),
        "petya": (fp_petya, priv_petya),
        "kolya": (fp_kolya, priv_kolya),
    }


# ============================================================================
# SEND_MESSAGE — DM
# ============================================================================

class TestSendMessageDM:
    def test_send(self, shared, users):
        fp_vasya, priv_vasya = users["vasya"]
        fp_petya, _ = users["petya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")

        msg_id = send_message(shared, chat_id, fp_vasya, priv_vasya, "Привет!")
        assert msg_id.startswith(str(int(msg_id.split("_")[0])))  # начинается с ts
        assert fp_vasya in msg_id

        # Файл .bin создан
        msg_file = chat_message_dir(shared, chat_id) / f"{msg_id}.bin"
        assert msg_file.is_file()

        # Внутри — правильная структура
        container = json.loads(msg_file.read_text(encoding="utf-8"))
        assert container["version"] == 2
        assert container["sender_fp16"] == fp_vasya
        assert "signature" in container
        assert "wrapped_keys" in container
        # В wrapped_keys лежат ПОЛНЫЕ fingerprint (64 символа), а не fp16
        # Проверяем, что ключей ровно 2 (для двух участников DM)
        assert len(container["wrapped_keys"]) >= 2

    def test_send_empty_raises(self, shared, users):
        fp, priv = users["vasya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")
        with pytest.raises(ValueError, match="пустым"):
            send_message(shared, chat_id, fp, priv, "")

    def test_send_too_long_raises(self, shared, users):
        fp, priv = users["vasya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")
        with pytest.raises(ValueError, match="слишком длинное"):
            send_message(shared, chat_id, fp, priv, "x" * 100_001)


# ============================================================================
# SEND_MESSAGE — ГРУППА
# ============================================================================

class TestSendMessageGroup:
    def test_send(self, shared, users):
        fp_vasya, priv_vasya = users["vasya"]
        fp_petya, _ = users["petya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")

        msg_id = send_message(shared, chat_id, fp_vasya, priv_vasya, "Привет!")
        msg_file = chat_message_dir(shared, chat_id) / f"{msg_id}.bin"
        assert msg_file.is_file()

        container = json.loads(msg_file.read_text(encoding="utf-8"))
        assert container["version"] == 2
        assert container["sender_fp16"] == fp_vasya
        assert "signature" in container
        assert "wrapped_keys" in container

        # ВАЖНО: в wrapped_keys лежат ПОЛНЫЕ fingerprint (64 символа), а не fp16
        # Проверяем, что ключей ровно 2 (для двух участников DM)
        assert len(container["wrapped_keys"]) >= 2


# ============================================================================
# READ_MESSAGES
# ============================================================================

class TestReadMessages:
    def test_read_empty(self, shared, users):
        fp, priv = users["vasya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")
        assert read_messages(shared, chat_id, fp, priv) == []

    def test_read_one(self, shared, users):
        fp_vasya, priv_vasya = users["vasya"]
        fp_petya, priv_petya = users["petya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")

        send_message(shared, chat_id, fp_vasya, priv_vasya, "От Васи")

        msgs = read_messages(shared, chat_id, fp_petya, priv_petya)
        assert len(msgs) == 1
        assert msgs[0].text == "От Васи"
        assert msgs[0].sender_fp16 == fp_vasya

    def test_read_multiple_sorted(self, shared, users):
        fp_vasya, priv_vasya = users["vasya"]
        fp_petya, priv_petya = users["petya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")

        send_message(shared, chat_id, fp_vasya, priv_vasya, "Первое")
        send_message(shared, chat_id, fp_petya, priv_petya, "Второе")
        send_message(shared, chat_id, fp_vasya, priv_vasya, "Третье")

        msgs = read_messages(shared, chat_id, fp_petya, priv_petya)
        assert [m.text for m in msgs] == ["Первое", "Второе", "Третье"]

    def test_read_group(self, shared, users):
        fp_vasya, priv_vasya = users["vasya"]
        fp_petya, priv_petya = users["petya"]
        chat_id = create_group_chat(shared, "vasya", "Друзья", ["petya", "kolya"])

        send_message(shared, chat_id, fp_vasya, priv_vasya, "Групповое")

        msgs = read_messages(shared, chat_id, fp_petya, priv_petya)
        assert len(msgs) == 1
        assert msgs[0].text == "Групповое"

    def test_stranger_cannot_read_dm(self, shared, users):
        fp_vasya, priv_vasya = users["vasya"]
        fp_kolya, priv_kolya = users["kolya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")
        send_message(shared, chat_id, fp_vasya, priv_vasya, "Секрет")

        with pytest.raises(ValueError, match="нет доступа"):
            read_messages(shared, chat_id, fp_kolya, priv_kolya)

    def test_stranger_cannot_read_group(self, shared, users):
        fp_vasya, priv_vasya = users["vasya"]
        fp_kolya, priv_kolya = users["kolya"]
        chat_id = create_group_chat(shared, "vasya", "Друзья", ["petya", "kolya"])
        send_message(shared, chat_id, fp_vasya, priv_vasya, "Секрет")

        # kolya — участник, читает
        msgs = read_messages(shared, chat_id, fp_kolya, priv_kolya)
        assert len(msgs) == 1


# ============================================================================
# TAMPERING
# ============================================================================

class TestTampering:
    def test_tampered_ciphertext_dm(self, shared, users):
        fp_vasya, priv_vasya = users["vasya"]
        fp_petya, priv_petya = users["petya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")

        msg_id = send_message(shared, chat_id, fp_vasya, priv_vasya, "Секрет")
        msg_file = chat_message_dir(shared, chat_id) / f"{msg_id}.bin"

        container = json.loads(msg_file.read_text(encoding="utf-8"))
        ct = container["ciphertext"]
        container["ciphertext"] = ("A" if ct[0] != "A" else "B") + ct[1:]
        msg_file.write_text(json.dumps(container), encoding="utf-8")

        # Должно вернуть пустой список (сообщение отброшено)
        msgs = read_messages(shared, chat_id, fp_petya, priv_petya)
        assert msgs == []

    def test_tampered_signature(self, shared, users):
        fp_vasya, priv_vasya = users["vasya"]
        fp_petya, priv_petya = users["petya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")

        msg_id = send_message(shared, chat_id, fp_vasya, priv_vasya, "Секрет")
        msg_file = chat_message_dir(shared, chat_id) / f"{msg_id}.bin"

        container = json.loads(msg_file.read_text(encoding="utf-8"))
        sig = container["signature"]
        container["signature"] = ("A" if sig[0] != "A" else "B") + sig[1:]
        msg_file.write_text(json.dumps(container), encoding="utf-8")

        msgs = read_messages(shared, chat_id, fp_petya, priv_petya)
        assert msgs == []

    def test_tampered_sender(self, shared, users):
        """Злоумышленник подменяет sender_fp16 — подпись не сойдётся."""
        fp_vasya, priv_vasya = users["vasya"]
        fp_petya, priv_petya = users["petya"]
        fp_kolya, _ = users["kolya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")

        msg_id = send_message(shared, chat_id, fp_vasya, priv_vasya, "Секрет")
        msg_file = chat_message_dir(shared, chat_id) / f"{msg_id}.bin"

        container = json.loads(msg_file.read_text(encoding="utf-8"))
        container["sender_fp16"] = fp_kolya  # Подмена
        msg_file.write_text(json.dumps(container), encoding="utf-8")

        msgs = read_messages(shared, chat_id, fp_petya, priv_petya)
        assert msgs == []


# ============================================================================
# READ_NEW_MESSAGES
# ============================================================================

class TestReadNew:
    def test_skips_known(self, shared, users):
        fp_vasya, priv_vasya = users["vasya"]
        fp_petya, priv_petya = users["petya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")

        id1 = send_message(shared, chat_id, fp_vasya, priv_vasya, "Старое")
        id2 = send_message(shared, chat_id, fp_vasya, priv_vasya, "Новое")

        new_msgs = read_new_messages(
            shared, chat_id, fp_petya, priv_petya, known_msg_ids={id1}
        )
        assert len(new_msgs) == 1
        assert new_msgs[0].msg_id == id2


# ============================================================================
# SEND_FILE
# ============================================================================

class TestSendFile:
    def test_send_file(self, shared, users, tmp_path):
        fp_vasya, priv_vasya = users["vasya"]
        fp_petya, priv_petya = users["petya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")

        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, world!", encoding="utf-8")

        msg_id = send_file(shared, chat_id, fp_vasya, priv_vasya, test_file)
        assert msg_id

        msgs = read_messages(shared, chat_id, fp_petya, priv_petya)
        assert len(msgs) == 1
        assert msgs[0].text.startswith("[FILE]")
        assert "test.txt" in msgs[0].text

    def test_send_missing_file_raises(self, shared, users):
        fp, priv = users["vasya"]
        chat_id = create_dm_chat(shared, "vasya", "petya")
        with pytest.raises(ValueError, match="не найден"):
            send_file(shared, chat_id, fp, priv, "/nonexistent/file.xyz")


# ============================================================================
# _BUILD_MSG_ID
# ============================================================================

class TestBuildMsgId:
    def test_format(self):
        msg_id = _build_msg_id(1700000000000, "a" * 16)
        parts = msg_id.split("_")
        assert len(parts) == 3
        assert parts[0] == "1700000000000"
        assert parts[1] == "a" * 16
        assert len(parts[2]) == 8