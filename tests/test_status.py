"""Тесты для src/core/status.py."""

import pytest
from src.core.status import (
    set_online, get_status,
    set_typing,
    mark_messages_read, get_read_messages,
    set_reaction, get_reactions,
    delete_message, get_deleted_messages,
    get_unread_count,
)
from src.storage.shared_store import ensure_shared_structure, chat_message_dir


@pytest.fixture
def shared(tmp_path):
    d = tmp_path / "share"
    d.mkdir()
    ensure_shared_structure(d)
    return d


# ============================================================================
# СТАТУС (онлайн / печатает)
# ============================================================================

class TestStatus:
    def test_default_offline(self, shared):
        status = get_status(shared, "a" * 16)
        assert status["online"] is False

    def test_set_online(self, shared):
        set_online(shared, "a" * 16, True)
        status = get_status(shared, "a" * 16)
        assert status["online"] is True

    def test_set_offline(self, shared):
        set_online(shared, "a" * 16, True)
        set_online(shared, "a" * 16, False)
        status = get_status(shared, "a" * 16)
        assert status["online"] is False

    def test_set_typing(self, shared):
        set_online(shared, "a" * 16, True)
        set_typing(shared, "a" * 16, "chat1", True)
        status = get_status(shared, "a" * 16)
        assert status["typing"] is True
        assert status["typing_chat"] == "chat1"

    def test_stop_typing(self, shared):
        set_online(shared, "a" * 16, True)
        set_typing(shared, "a" * 16, "chat1", True)
        set_typing(shared, "a" * 16, "chat1", False)
        status = get_status(shared, "a" * 16)
        assert status["typing"] is False


# ============================================================================
# ПРОЧТЕНИЕ
# ============================================================================

class TestRead:
    def test_empty(self, shared):
        assert get_read_messages(shared, "chat1", "a" * 16) == []

    def test_mark_read(self, shared):
        mark_messages_read(shared, "chat1", "a" * 16, ["msg1", "msg2"])
        read = get_read_messages(shared, "chat1", "a" * 16)
        assert "msg1" in read
        assert "msg2" in read

    def test_mark_read_duplicates(self, shared):
        mark_messages_read(shared, "chat1", "a" * 16, ["msg1"])
        mark_messages_read(shared, "chat1", "a" * 16, ["msg1", "msg2"])
        read = get_read_messages(shared, "chat1", "a" * 16)
        assert read.count("msg1") == 1
        assert "msg2" in read


# ============================================================================
# РЕАКЦИИ
# ============================================================================

class TestReactions:
    def test_empty(self, shared):
        assert get_reactions(shared, "chat1", "msg1") == {}

    def test_set_reaction(self, shared):
        set_reaction(shared, "chat1", "msg1", "a" * 16, "❤️")
        reactions = get_reactions(shared, "chat1", "msg1")
        assert reactions["a" * 16] == "❤️"

    def test_remove_reaction(self, shared):
        set_reaction(shared, "chat1", "msg1", "a" * 16, "❤️")
        set_reaction(shared, "chat1", "msg1", "a" * 16, None)
        reactions = get_reactions(shared, "chat1", "msg1")
        assert "a" * 16 not in reactions

    def test_multiple_users(self, shared):
        set_reaction(shared, "chat1", "msg1", "a" * 16, "❤️")
        set_reaction(shared, "chat1", "msg1", "b" * 16, "👍")
        reactions = get_reactions(shared, "chat1", "msg1")
        assert len(reactions) == 2


# ============================================================================
# УДАЛЕНИЕ
# ============================================================================

class TestDelete:
    def test_empty(self, shared):
        assert get_deleted_messages(shared, "chat1", "a" * 16) == []

    def test_delete_for_self(self, shared):
        delete_message(shared, "chat1", "msg1", "a" * 16, for_everyone=False)
        deleted = get_deleted_messages(shared, "chat1", "a" * 16)
        assert "msg1" in deleted

    def test_delete_for_self_not_other(self, shared):
        delete_message(shared, "chat1", "msg1", "a" * 16, for_everyone=False)
        deleted = get_deleted_messages(shared, "chat1", "b" * 16)
        assert "msg1" not in deleted

    def test_delete_for_everyone(self, shared):
        delete_message(shared, "chat1", "msg1", "a" * 16, for_everyone=True)
        assert "msg1" in get_deleted_messages(shared, "chat1", "a" * 16)
        assert "msg1" in get_deleted_messages(shared, "chat1", "b" * 16)


# ============================================================================
# НЕПРОЧИТАННЫЕ
# ============================================================================

class TestUnread:
    def _make_msg(self, shared, chat_id: str, sender_fp16: str, ts: int = 1700000000000, uuid8: str = "c" * 8) -> str:
        """Хелпер: создаёт .bin файл с корректным msg_id и возвращает msg_id."""
        msg_dir = chat_message_dir(shared, chat_id)
        msg_dir.mkdir(parents=True, exist_ok=True)
        msg_id = f"{ts}_{sender_fp16}_{uuid8}"
        (msg_dir / f"{msg_id}.bin").write_text("{}")
        return msg_id

    def test_empty(self, shared):
        assert get_unread_count(shared, "chat1", "a" * 16) == 0

    def test_unread(self, shared):
        self._make_msg(shared, "chat1", "b" * 16)
        assert get_unread_count(shared, "chat1", "a" * 16) == 1

    def test_read_not_counted(self, shared):
        msg_id = self._make_msg(shared, "chat1", "b" * 16)
        mark_messages_read(shared, "chat1", "a" * 16, [msg_id])
        assert get_unread_count(shared, "chat1", "a" * 16) == 0

    def test_own_not_counted(self, shared):
        self._make_msg(shared, "chat1", "a" * 16)
        assert get_unread_count(shared, "chat1", "a" * 16) == 0

    def test_malformed_msg_id_ignored(self, shared):
        """Битые msg_id не должны залипать в счётчике."""
        msg_dir = chat_message_dir(shared, "chat1")
        msg_dir.mkdir(parents=True, exist_ok=True)
        (msg_dir / "garbage.bin").write_text("{}")
        assert get_unread_count(shared, "chat1", "a" * 16) == 0

    def test_multiple_unread(self, shared):
        self._make_msg(shared, "chat1", "b" * 16, ts=1700000000001)
        self._make_msg(shared, "chat1", "b" * 16, ts=1700000000002)
        self._make_msg(shared, "chat1", "b" * 16, ts=1700000000003)
        assert get_unread_count(shared, "chat1", "a" * 16) == 3