"""Тесты для src/core/message.py."""

import json
import pytest

from src.core.admin import make_admin
from src.core.chat_logic import create_dm_chat
from src.core.identity import authenticate, register_identity
from src.core.message import read_messages, send_message
from src.storage.shared_store import ensure_shared_structure


@pytest.fixture
def shared(tmp_path):
    d = tmp_path / "share"
    d.mkdir()
    ensure_shared_structure(d)
    return d


@pytest.fixture
def users(shared):
    fp_vasya = register_identity(shared, "vasya", "Pass1!")
    make_admin(shared, fp_vasya, by="system")
    priv_vasya, _ = authenticate(shared, "vasya", "Pass1!")

    fp_petya = register_identity(shared, "petya", "Pass2!")
    priv_petya, _ = authenticate(shared, "petya", "Pass2!")

    return (fp_vasya, priv_vasya), (fp_petya, priv_petya)


class TestMessage:
    def test_send_and_read(self, shared, users):
        (fp_v, priv_v), (fp_p, priv_p) = users
        chat_id = create_dm_chat(shared, "vasya", "petya")

        send_message(shared, chat_id, fp_v, priv_v, "Привет, Петя!")

        msgs_v = read_messages(shared, chat_id, fp_v, priv_v)
        assert len(msgs_v) == 1
        assert msgs_v[0].text == "Привет, Петя!"

        msgs_p = read_messages(shared, chat_id, fp_p, priv_p)
        assert len(msgs_p) == 1
        assert msgs_p[0].text == "Привет, Петя!"

    def test_multiple_messages(self, shared, users):
        (fp_v, priv_v), (fp_p, priv_p) = users
        chat_id = create_dm_chat(shared, "vasya", "petya")

        send_message(shared, chat_id, fp_v, priv_v, "Первое")
        send_message(shared, chat_id, fp_p, priv_p, "Второе")
        send_message(shared, chat_id, fp_v, priv_v, "Третье")

        msgs = read_messages(shared, chat_id, fp_v, priv_v)
        assert len(msgs) == 3
        assert [m.text for m in msgs] == ["Первое", "Второе", "Третье"]

    def test_empty_message(self, shared, users):
        (fp_v, priv_v), _ = users
        chat_id = create_dm_chat(shared, "vasya", "petya")
        with pytest.raises(ValueError):
            send_message(shared, chat_id, fp_v, priv_v, "")

    def test_stranger_cannot_read(self, shared, users):
        (fp_v, priv_v), _ = users
        fp_k = register_identity(shared, "kolya", "Pass3!")
        priv_k, _ = authenticate(shared, "kolya", "Pass3!")

        chat_id = create_dm_chat(shared, "vasya", "petya")
        send_message(shared, chat_id, fp_v, priv_v, "Секрет")

        with pytest.raises(ValueError, match="нет доступа"):
            read_messages(shared, chat_id, fp_k, priv_k)


class TestTampering:
    def test_tampered_signature(self, shared, users):
        (fp_v, priv_v), _ = users
        chat_id = create_dm_chat(shared, "vasya", "petya")
        send_message(shared, chat_id, fp_v, priv_v, "Текст")

        msg_file = next((shared / "message" / chat_id).glob("*.bin"))
        data = json.loads(msg_file.read_text(encoding="utf-8"))
        data["signature"] = "AAAA"
        msg_file.write_text(json.dumps(data), encoding="utf-8")

        msgs = read_messages(shared, chat_id, fp_v, priv_v)
        assert len(msgs) == 0

    def test_tampered_ciphertext(self, shared, users):
        (fp_v, priv_v), _ = users
        chat_id = create_dm_chat(shared, "vasya", "petya")
        send_message(shared, chat_id, fp_v, priv_v, "Текст")

        msg_file = next((shared / "message" / chat_id).glob("*.bin"))
        data = json.loads(msg_file.read_text(encoding="utf-8"))
        ct = data["ciphertext"]
        data["ciphertext"] = ("A" if ct[0] != "A" else "B") + ct[1:]
        msg_file.write_text(json.dumps(data), encoding="utf-8")

        msgs = read_messages(shared, chat_id, fp_v, priv_v)
        assert len(msgs) == 0
