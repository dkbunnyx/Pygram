"""Тесты для src/core/user.py."""

import time

import pytest

from src.core.admin import is_admin, load_admins
from src.core.user import (
    User,
    list_saved_sessions,
    load_saved_session,
    login_user,
    logout_user,
    register_user,
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
    """Изолируем локальную папку от реальной %USERPROFILE%\\.pygram."""
    local = tmp_path / "local"
    local.mkdir()
    monkeypatch.setattr(
        "src.core.user.get_local_dir",
        lambda: local,
    )
    return local


# ============================================================================
# Регистрация
# ============================================================================

class TestRegister:
    def test_first_user_is_admin(self, shared):
        user = register_user(shared, "vasya", "Passw0rd!")
        assert user.login == "vasya"
        assert user.is_admin is True
        assert user.role == "admin"

    def test_second_user_not_admin(self, shared):
        register_user(shared, "vasya", "Passw0rd!")
        user2 = register_user(shared, "petya", "Passw0rd!")
        assert user2.is_admin is False
        assert user2.role == "user"

    def test_login_occupied(self, shared):
        register_user(shared, "vasya", "Passw0rd!")
        with pytest.raises(FileExistsError):
            register_user(shared, "vasya", "OtherPass!")


# ============================================================================
# Логин
# ============================================================================

class TestLogin:
    def test_success(self, shared):
        register_user(shared, "vasya", "Passw0rd!")
        user = login_user(shared, "vasya", "Passw0rd!")
        assert user.login == "vasya"
        assert "PRIVATE KEY" in user.priv_pem
        assert "PUBLIC KEY" in user.pub_pem

    def test_wrong_password(self, shared):
        register_user(shared, "vasya", "Passw0rd!")
        with pytest.raises(ValueError, match="Неверный пароль"):
            login_user(shared, "vasya", "wrong")

    def test_not_found(self, shared):
        with pytest.raises(FileNotFoundError):
            login_user(shared, "nobody", "Passw0rd!")

    def test_admin_status_preserved(self, shared):
        register_user(shared, "vasya", "Passw0rd!")
        register_user(shared, "petya", "Passw0rd!")
        vasya = login_user(shared, "vasya", "Passw0rd!")
        petya = login_user(shared, "petya", "Passw0rd!")
        assert vasya.is_admin is True
        assert petya.is_admin is False


# ============================================================================
# Сессия
# ============================================================================

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
        # Перезаписываем .session с истёкшим expires_at
        from src.core.user import _session_path
        import json
        p = _session_path(user.fp16)
        data = json.loads(p.read_text(encoding="utf-8"))
        data["expires_at"] = 1  # давно истекла
        p.write_text(json.dumps(data), encoding="utf-8")

        assert load_saved_session(user.fp16) is None
        assert not p.exists()  # должен удалиться

    def test_no_priv_in_session(self, shared):
        """Приватный ключ НЕ должен писаться в .session."""
        user = register_user(shared, "vasya", "Passw0rd!")
        from src.core.user import _session_path
        text = _session_path(user.fp16).read_text(encoding="utf-8")
        assert "PRIVATE KEY" not in text
        assert "priv_pem" not in text


# ============================================================================
# User dataclass
# ============================================================================

class TestUserDataclass:
    def test_fields(self):
        u = User(
            login="vasya",
            fp16="a" * 16,
            priv_pem="priv",
            pub_pem="pub",
            is_admin=True,
        )
        assert u.login == "vasya"
        assert u.role == "admin"

    def test_role_user(self):
        u = User(
            login="vasya", fp16="a" * 16, priv_pem="",
            pub_pem="", is_admin=False,
        )
        assert u.role == "user"