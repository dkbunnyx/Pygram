"""Тесты для src/core/admin.py."""

import pytest

from src.core.admin import (
    admins_path,
    has_any_admin,
    is_admin,
    load_admins,
    make_admin,
    remove_admin,
    verify_signature,
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


class TestMakeAdmin:
    def test_first_system(self, shared):
        make_admin(shared, "a" * 16, by="system")
        admins = load_admins(shared)
        assert len(admins) == 1
        assert admins[0]["fp16"] == "a" * 16
        assert admins[0]["added_by"] == "system"
        assert admins[0]["signature"] == ""
        assert has_any_admin(shared) is True
        assert is_admin(shared, "a" * 16) is True

    def test_second_signed(self, shared, keypair):
        priv, _ = keypair
        make_admin(shared, "a" * 16, by="system")
        make_admin(shared, "b" * 16, by="a" * 16, by_priv=priv)

        admins = load_admins(shared)
        assert len(admins) == 2
        assert admins[1]["fp16"] == "b" * 16
        assert admins[1]["signature"] != ""

    def test_duplicate_raises(self, shared):
        make_admin(shared, "a" * 16, by="system")
        with pytest.raises(ValueError, match="уже админ"):
            make_admin(shared, "a" * 16, by="system")

    def test_no_priv_raises(self, shared):
        make_admin(shared, "a" * 16, by="system")
        with pytest.raises(ValueError, match="by_priv"):
            make_admin(shared, "b" * 16, by="a" * 16)  # без by_priv


class TestRemoveAdmin:
    def test_success(self, shared):
        make_admin(shared, "a" * 16, by="system")
        make_admin(shared, "b" * 16, by="system")  # для теста
        remove_admin(shared, "b" * 16, by="a" * 16)
        assert len(load_admins(shared)) == 1
        assert not is_admin(shared, "b" * 16)

    def test_remove_last_raises(self, shared):
        make_admin(shared, "a" * 16, by="system")
        with pytest.raises(ValueError, match="последнего"):
            remove_admin(shared, "a" * 16, by="a" * 16)

    def test_remove_nonexistent_raises(self, shared):
        with pytest.raises(ValueError, match="не админ"):
            remove_admin(shared, "a" * 16, by="b" * 16)


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
        # Подпись проверяем чужим ключом → False
        assert verify_signature(entry, pub_other) is False


class TestFilePath:
    def test_path(self, shared):
        p = admins_path(shared)
        assert p.parent.name == ".admins"
        assert p.name == "list.json"
