"""Тесты для src/core/user.py."""
import json
import pytest
from src.core.user import (
    User, list_saved_sessions, load_saved_session,
    login_user, logout_user, register_user, _session_path
)
from src.storage.shared_store import ensure_shared_structure


@pytest.fixture
def shared(tmp_path):
    d = tmp_path / "share"
    d.mkdir()
    ensure_shared_structure(d)
    return d


@pytest.fixture(autouse=True)
def isolate_local_dir(tmp_path, monkeypatch):
    local = tmp_path / "local"
    local.mkdir()
    monkeypatch.setattr("src.core.user.get_local_dir", lambda: local)
    return local


class TestRegister:
    def test_first_user_is_admin(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        assert user.is_admin is True
        assert user.role == "admin"

    def test_second_user_not_admin(self, shared):
        register_user(shared, "vasya", "Passw0rd!")
        user2 = register_user(shared, "petya", "Passw0rd!")
        assert user2.is_admin is False


class TestLogin:
    def test_success(self, shared):
        register_user(shared, "vasya", "Passw0rd!")
        user = login_user(shared, "vasya", "Passw0rd!")
        assert "PRIVATE KEY" in user.priv_pem


class TestSession:
    def test_saved_after_register(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        sessions = list_saved_sessions()
        assert len(sessions) == 1
        assert sessions[0]["login"] == "vasya"
        assert sessions[0]["fp16"] == user.fp16

    def test_logout_removes(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        logout_user(user)
        assert list_saved_sessions() == []

    def test_load_saved(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        data = load_saved_session(user.fp16)
        assert data is not None
        assert data["login"] == "vasya"

    def test_expired_session(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        p = _session_path(user.fp16)
        data = json.loads(p.read_text(encoding="utf-8"))
        data["expires_at"] = 1
        p.write_text(json.dumps(data), encoding="utf-8")

        assert load_saved_session(user.fp16) is None
        assert not p.exists()

    def test_reboot_invalidates_session(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        p = _session_path(user.fp16)
        data = json.loads(p.read_text(encoding="utf-8"))
        data["boot_time"] = 12345
        p.write_text(json.dumps(data), encoding="utf-8")

        assert load_saved_session(user.fp16) is None
        assert not p.exists()

    def test_no_priv_in_session(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        text = _session_path(user.fp16).read_text(encoding="utf-8")
        assert "PRIVATE KEY" not in text