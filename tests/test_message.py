"""Тесты для src/core/chat_logic.py."""

import pytest

from src.core.admin import make_admin
from src.core.chat_logic import (
    create_admin_chat,
    create_dm_chat,
    create_favorites,
    create_group_chat,
    get_chat_recipients,
    is_chat_visible,
    list_user_chats,
)
from src.core.identity import register_identity
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
    fp_petya = register_identity(shared, "petya", "Pass2!")
    fp_kolya = register_identity(shared, "kolya", "Pass3!")
    return fp_vasya, fp_petya, fp_kolya


class TestDM:
    def test_create(self, shared, users):
        fp_vasya, fp_petya, _ = users
        chat_id = create_dm_chat(shared, "vasya", "petya")
        assert chat_id.startswith("dm_")
        assert fp_vasya in chat_id
        assert fp_petya in chat_id

    def test_deterministic(self, shared, users):
        id1 = create_dm_chat(shared, "vasya", "petya")
        id2 = create_dm_chat(shared, "petya", "vasya")
        assert id1 == id2

    def test_self_chat_fails(self, shared, users):
        with pytest.raises(ValueError, match="самим собой"):
            create_dm_chat(shared, "vasya", "vasya")

    def test_user_not_found(self, shared, users):
        with pytest.raises(ValueError, match="не найден"):
            create_dm_chat(shared, "vasya", "nobody")

    def test_visible(self, shared, users):
        fp_vasya, fp_petya, fp_kolya = users
        chat_id = create_dm_chat(shared, "vasya", "petya")
        assert is_chat_visible(shared, chat_id, fp_vasya) is True
        assert is_chat_visible(shared, chat_id, fp_petya) is True
        assert is_chat_visible(shared, chat_id, fp_kolya) is False


class TestGroup:
    def test_create(self, shared, users):
        chat_id = create_group_chat(shared, "vasya", "Друзья", ["petya", "kolya"])
        assert chat_id.startswith("grp_")

    def test_too_few_members(self, shared, users):
        with pytest.raises(ValueError, match="минимум 3"):
            create_group_chat(shared, "vasya", "Группа", ["petya"])

    def test_empty_name(self, shared, users):
        with pytest.raises(ValueError, match="Название"):
            create_group_chat(shared, "vasya", "", ["petya", "kolya"])

    def test_visible_to_all_members(self, shared, users):
        fp_vasya, fp_petya, fp_kolya = users
        chat_id = create_group_chat(shared, "vasya", "Друзья", ["petya", "kolya"])

        assert is_chat_visible(shared, chat_id, fp_vasya) is True
        assert is_chat_visible(shared, chat_id, fp_petya) is True
        assert is_chat_visible(shared, chat_id, fp_kolya) is True

    def test_wrapped_keys_created(self, shared, users):
        chat_id = create_group_chat(shared, "vasya", "Друзья", ["petya", "kolya"])
        recipients = get_chat_recipients(shared, chat_id)
        # 3 участника + админ (vasya — уже в участниках)
        assert len(recipients) == 3


class TestFavorites:
    def test_create(self, shared, users):
        fp_vasya, _, _ = users
        chat_id = create_favorites(shared, "vasya")
        assert chat_id == f"fav_{fp_vasya}"

    def test_idempotent(self, shared, users):
        id1 = create_favorites(shared, "vasya")
        id2 = create_favorites(shared, "vasya")
        assert id1 == id2

    def test_visible_only_to_owner(self, shared, users):
        fp_vasya, fp_petya, _ = users
        chat_id = create_favorites(shared, "vasya")
        assert is_chat_visible(shared, chat_id, fp_vasya) is True
        assert is_chat_visible(shared, chat_id, fp_petya) is False


class TestAdminChat:
    def test_create(self, shared, users):
        chat_id = create_admin_chat(shared)
        assert chat_id == "admin_chat"

    def test_visible_only_to_admins(self, shared, users):
        fp_vasya, fp_petya, _ = users
        chat_id = create_admin_chat(shared)
        assert is_chat_visible(shared, chat_id, fp_vasya) is True
        assert is_chat_visible(shared, chat_id, fp_petya) is False


class TestListChats:
    def test_empty(self, shared, users):
        fp_vasya, _, _ = users
        assert list_user_chats(shared, fp_vasya) == []

    def test_multiple(self, shared, users):
        fp_vasya, _, _ = users
        create_dm_chat(shared, "vasya", "petya")
        create_favorites(shared, "vasya")
        create_admin_chat(shared)

        chats = list_user_chats(shared, fp_vasya)
        types = {c["type"] for c in chats}
        assert "dm" in types
        assert "favorites" in types
        assert "admin_chat" in types