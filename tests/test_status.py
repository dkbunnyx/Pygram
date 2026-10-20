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
from src.storage.shared_store import ensure_shared_structure


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
        # Для другого пользователя — не удалено
        deleted = get_deleted_messages(shared, "chat1", "b" * 16)
        assert "msg1" not in deleted

    def test_delete_for_everyone(self, shared):
        delete_message(shared, "chat1", "msg1", "a" * 16, for_everyone=True)
        # Для всех
        assert "msg1" in get_deleted_messages(shared, "chat1", "a" * 16)
        assert "msg1" in get_deleted_messages(shared, "chat1", "b" * 16)


# ============================================================================
# НЕПРОЧИТАННЫЕ
# ============================================================================

class TestUnread:
    def test_empty(self, shared):
        assert get_unread_count(shared, "chat1", "a" * 16) == 0

    def test_unread(self, shared, tmp_path):
        # Создаём фейковый .bin файл
        from src.storage.shared_store import chat_message_dir
        msg_dir = chat_message_dir(shared, "chat1")
        msg_dir.mkdir(parents=True, exist_ok=True)
        (msg_dir / "123_b16_uuid.bin").write_text("{}")

        count = get_unread_count(shared, "chat1", "a" * 16)
        assert count == 1

    def test_read_not_counted(self, shared):
        from src.storage.shared_store import chat_message_dir
        msg_dir = chat_message_dir(shared, "chat1")
        msg_dir.mkdir(parents=True, exist_ok=True)
        (msg_dir / "123_b16_uuid.bin").write_text("{}")

        mark_messages_read(shared, "chat1", "a" * 16, ["123_b16_uuid"])
        count = get_unread_count(shared, "chat1", "a" * 16)
        assert count == 0

    def test_own_not_counted(self, shared):
        from src.storage.shared_store import chat_message_dir
        msg_dir = chat_message_dir(shared, "chat1")
        msg_dir.mkdir(parents=True, exist_ok=True)
        (msg_dir / f"123_{'a' * 16}_uuid.bin").write_text("{}")

        # Это наше сообщение — не считается
        count = get_unread_count(shared, "chat1", "a" * 16)
        assert count == 0
