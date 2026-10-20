"""Тесты для src/core/admin.py."""

import pytest
from src.core.admin import (
    admins_path, has_any_admin, is_admin, is_super,
    load_admins, make_admin, remove_admin, verify_signature,
    can_read_all_chats, can_manage_admins,
    toggle_manage_rights, toggle_read_rights,
)
from src.core.crypto import generate_rsa_keypair
from src.storage.shared_store import ensure_shared_structure


@pytest.fixture
def shared(tmp_path):
    d = tmp_path / "share"
    d.mkdir()
    ensure_shared_structure(d)
    return d


@pytest.fixture
def keypair():
    priv, pub = generate_rsa_keypair()
    return priv, pub


class TestLoad:
    def test_empty(self, shared):
        assert load_admins(shared) == []
        assert has_any_admin(shared) is False

    def test_not_admin(self, shared):
        assert is_admin(shared, "a" * 16) is False
        assert is_super(shared, "a" * 16) is False


class TestMakeAdmin:
    def test_first_system(self, shared):
        make_admin(shared, "a" * 16, by="system")
        admins = load_admins(shared)
        assert len(admins) == 1
        assert admins[0]["fp16"] == "a" * 16
        assert admins[0]["is_super"] is True
        assert has_any_admin(shared) is True
        assert is_admin(shared, "a" * 16) is True
        assert is_super(shared, "a" * 16) is True

    def test_second_signed(self, shared, keypair):
        priv, _ = keypair
        make_admin(shared, "a" * 16, by="system")
        make_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)

        admins = load_admins(shared)
        assert len(admins) == 2
        assert admins[1]["fp16"] == "b" * 16
        assert admins[1]["is_super"] is False
        assert is_admin(shared, "b" * 16) is True
        assert is_super(shared, "b" * 16) is False

    def test_duplicate_raises(self, shared):
        make_admin(shared, "a" * 16, by="system")
        with pytest.raises(ValueError, match="уже админ"):
            make_admin(shared, "a" * 16, by="system")

    def test_no_priv_raises(self, shared):
        make_admin(shared, "a" * 16, by="system")
        with pytest.raises(ValueError, match="by_priv"):
            make_admin(shared, "b" * 16, by="a" * 16)

    def test_not_super_raises(self, shared, keypair):
        priv, _ = keypair
        make_admin(shared, "a" * 16, by="system")
        make_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)
        # Теперь "b" пытается назначить "c"
        with pytest.raises(ValueError, match="У вас нет прав"):
            make_admin(shared, "c" * 16, by="b" * 16, by_priv=priv)


class TestRemoveAdmin:
    def test_success(self, shared, keypair):
        priv, _ = keypair
        make_admin(shared, "a" * 16, by="system")
        make_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)

        remove_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)
        assert len(load_admins(shared)) == 1
        assert not is_admin(shared, "b" * 16)

    def test_remove_super_raises(self, shared, keypair):
        priv, _ = keypair
        make_admin(shared, "a" * 16, by="system")
        make_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)

        with pytest.raises(ValueError, match="Нельзя снять супер-админа"):
            remove_admin(shared, "a" * 16, by="b" * 16, by_priv=priv)

    def test_remove_not_super_raises(self, shared, keypair):
        priv, _ = keypair
        make_admin(shared, "a" * 16, by="system")  # Супер-админ
        make_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)  # Обычный админ
        make_admin(shared, "c" * 16, by="a" * 16, by_priv=priv)  # Ещё один обычный

        # "b" пытается снять "c" (но "b" не супер)
        with pytest.raises(ValueError, match="У вас нет прав"):
            remove_admin(shared, "c" * 16, by="b" * 16, by_priv=priv)

    def test_remove_nonexistent_raises(self, shared, keypair):
        priv, _ = keypair
        make_admin(shared, "a" * 16, by="system")
        with pytest.raises(ValueError, match="не админ"):
            remove_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)


class TestRights:
    def test_can_read_all_chats_super(self, shared):
        make_admin(shared, "a" * 16, by="system")
        assert can_read_all_chats(shared, "a" * 16) is True

    def test_can_read_all_chats_default_false(self, shared, keypair):
        priv, _ = keypair
        make_admin(shared, "a" * 16, by="system")
        make_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)
        assert can_read_all_chats(shared, "b" * 16) is False

    def test_toggle_read_rights(self, shared, keypair):
        priv, _ = keypair
        make_admin(shared, "a" * 16, by="system")
        make_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)

        toggle_read_rights(shared, "b" * 16, by="a" * 16)
        assert can_read_all_chats(shared, "b" * 16) is True

        toggle_read_rights(shared, "b" * 16, by="a" * 16)
        assert can_read_all_chats(shared, "b" * 16) is False

    def test_toggle_manage_rights(self, shared, keypair):
        priv, _ = keypair
        make_admin(shared, "a" * 16, by="system")
        make_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)

        toggle_manage_rights(shared, "b" * 16, by="a" * 16)
        assert can_manage_admins(shared, "b" * 16) is True

    def test_toggle_rights_only_super(self, shared, keypair):
        priv, _ = keypair
        make_admin(shared, "a" * 16, by="system")
        make_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)

        with pytest.raises(ValueError, match="Только супер-админ"):
            toggle_read_rights(shared, "b" * 16, by="b" * 16)


class TestVerifySignature:
    def test_system_always_valid(self, shared, keypair):
        _, pub = keypair
        make_admin(shared, "a" * 16, by="system")
        entry = load_admins(shared)[0]
        assert verify_signature(entry, pub) is True

    def test_signed_valid(self, shared, keypair):
        priv, pub = keypair
        make_admin(shared, "a" * 16, by="system")
        make_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)
        entry = load_admins(shared)[1]
        assert verify_signature(entry, pub) is True

    def test_signed_invalid(self, shared, keypair):
        priv, _ = keypair
        _, pub_other = generate_rsa_keypair()
        make_admin(shared, "a" * 16, by="system")
        make_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)
        entry = load_admins(shared)[1]
        assert verify_signature(entry, pub_other) is False


class TestFilePath:
    def test_path(self, shared):
        p = admins_path(shared)
        assert p.parent.name == ".admins"
        assert p.name == "list.json"