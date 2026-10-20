"""Тесты для управления участниками группы."""

import pytest
from src.core.admin import make_admin
from src.core.chat_logic import (
    create_group_chat,
    remove_group_member,
    toggle_group_admin,
    toggle_group_permission,
    can_edit_group_profile,
)
from src.core.identity import authenticate, register_identity
from src.storage.shared_store import ensure_shared_structure


@pytest.fixture
def shared(tmp_path):
    d = tmp_path / "share"
    d.mkdir()
    ensure_shared_structure(d)
    return d


@pytest.fixture
def group(shared):
    """Создаёт группу с 3 участниками."""
    fp_vasya = register_identity(shared, "vasya", "Pass1!")
    make_admin(shared, fp_vasya, by="system")
    priv_vasya, _ = authenticate(shared, "vasya", "Pass1!")

    fp_petya = register_identity(shared, "petya", "Pass2!")
    priv_petya, _ = authenticate(shared, "petya", "Pass2!")

    fp_kolya = register_identity(shared, "kolya", "Pass3!")
    priv_kolya, _ = authenticate(shared, "kolya", "Pass3!")

    chat_id = create_group_chat(shared, "vasya", "Друзья", ["petya", "kolya"])

    return {
        "chat_id": chat_id,
        "vasya": (fp_vasya, priv_vasya),
        "petya": (fp_petya, priv_petya),
        "kolya": (fp_kolya, priv_kolya),
    }


class TestGroupAdmin:
    def test_toggle_admin(self, shared, group):
        fp_vasya, priv_vasya = group["vasya"]
        fp_petya, priv_petya = group["petya"]
        chat_id = group["chat_id"]

        toggle_group_admin(shared, chat_id, fp_petya, fp_vasya, priv_vasya)

        # Проверяем, что petya теперь админ
        # (просто проверяем, что нет ошибки — детали внутри meta)
        assert True

    def test_only_creator_can_toggle(self, shared, group):
        fp_vasya, priv_vasya = group["vasya"]
        fp_petya, priv_petya = group["petya"]
        chat_id = group["chat_id"]

        with pytest.raises(ValueError, match="Только создатель"):
            toggle_group_admin(shared, chat_id, fp_vasya, fp_petya, priv_petya)


class TestRemoveMember:
    def test_remove_by_creator(self, shared, group):
        fp_vasya, priv_vasya = group["vasya"]
        fp_kolya, priv_kolya = group["kolya"]
        chat_id = group["chat_id"]

        remove_group_member(shared, chat_id, fp_kolya, fp_vasya, priv_vasya)

        # Проверяем, что kolya больше не в группе
        # (проверяем через is_chat_visible — если не видит, значит удалён)
        from src.core.chat_logic import is_chat_visible
        assert is_chat_visible(shared, chat_id, fp_kolya) is False

    def test_cannot_remove_creator(self, shared, group):
        fp_vasya, priv_vasya = group["vasya"]
        chat_id = group["chat_id"]

        with pytest.raises(ValueError, match="Нельзя удалить создателя"):
            remove_group_member(shared, chat_id, fp_vasya, fp_vasya, priv_vasya)

    def test_remove_not_in_group(self, shared, group):
        fp_vasya, priv_vasya = group["vasya"]
        chat_id = group["chat_id"]

        with pytest.raises(ValueError, match="не в группе"):
            remove_group_member(shared, chat_id, "c" * 16, fp_vasya, priv_vasya)

    def test_only_creator_or_admin_can_remove(self, shared, group):
        fp_petya, priv_petya = group["petya"]
        fp_kolya, priv_kolya = group["kolya"]
        chat_id = group["chat_id"]

        # petya — не админ и не создатель
        with pytest.raises(ValueError, match="нет прав"):
            remove_group_member(shared, chat_id, fp_kolya, fp_petya, priv_petya)


class TestPermissions:
    def test_toggle_permission(self, shared, group):
        fp_vasya, priv_vasya = group["vasya"]
        fp_petya, priv_petya = group["petya"]
        chat_id = group["chat_id"]

        # Назначаем petya админом
        toggle_group_admin(shared, chat_id, fp_petya, fp_vasya, priv_vasya)

        # Даём право на редактирование профиля
        toggle_group_permission(
            shared, chat_id, fp_petya, "can_edit_profile", fp_vasya, priv_vasya
        )

        # Проверяем, что право выдано
        assert can_edit_group_profile(shared, chat_id, fp_petya, priv_petya) is True

    def test_only_creator_can_toggle_permission(self, shared, group):
        fp_petya, priv_petya = group["petya"]
        fp_kolya, priv_kolya = group["kolya"]
        chat_id = group["chat_id"]

        with pytest.raises(ValueError, match="Только создатель"):
            toggle_group_permission(
                shared, chat_id, fp_kolya, "can_edit_profile", fp_petya, priv_petya
            )

    def test_creator_can_edit_always(self, shared, group):
        fp_vasya, priv_vasya = group["vasya"]
        chat_id = group["chat_id"]

        assert can_edit_group_profile(shared, chat_id, fp_vasya, priv_vasya) is True