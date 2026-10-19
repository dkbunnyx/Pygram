"""Тесты для src/core/user.py."""
import json
import pytest
from src.core.user import User, list_saved_sessions, load_saved_session, login_user, logout_user, register_user, _session_path
from src.storage.shared_store import ensure_shared_structure

@pytest.fixture
def shared(tmp_path):
    d = tmp_path / "share"; d.mkdir(); ensure_shared_structure(d); return d

@pytest.fixture(autouse=True)
def isolate_local_dir(tmp_path, monkeypatch):
    local = tmp_path / "local"; local.mkdir()
    monkeypatch.setattr("src.core.user.get_local_dir", lambda: local)
    return local

class TestRegister:
    def test_first_user_is_admin(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        assert user.is_admin is True and user.role == "admin"
    def test_second_user_not_admin(self, shared):
        register_user(shared, "vasya", "Passw0rd!")
        assert register_user(shared, "petya", "Passw0rd!").is_admin is False

class TestLogin:
    def test_success(self, shared):
        register_user(shared, "vasya", "Passw0rd!")
        assert "PRIVATE KEY" in login_user(shared, "vasya", "Passw0rd!").priv_pem

class TestSession:
    def test_saved_after_register(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        assert list_saved_sessions()[0]["login"] == "vasya"
    def test_logout_removes(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!"); logout_user(user); assert list_saved_sessions() == []
    def test_load_saved(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        assert load_saved_session(user.fp16)["login"] == "vasya"
    def test_expired_session(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        p = _session_path(user.fp16); data = json.loads(p.read_text()); data["expires_at"] = 1
        p.write_text(json.dumps(data)); assert load_saved_session(user.fp16) is None and not p.exists()
    def test_reboot_invalidates_session(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        p = _session_path(user.fp16); data = json.loads(p.read_text()); data["boot_time"] = 12345
        p.write_text(json.dumps(data)); assert load_saved_session(user.fp16) is None and not p.exists()
    def test_no_priv_in_session(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        assert "PRIVATE KEY" not in _session_path(user.fp16).read_text()
