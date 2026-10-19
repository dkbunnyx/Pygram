"""Тесты для src/core/roles.py."""

import pytest

from src.core.roles import (
    ROLE_ADMIN,
    ROLE_USER,
    ALL_ROLES,
    is_admin_role,
    validate_role,
)


class TestRoles:
    def test_constants(self):
        assert ROLE_USER == "user"
        assert ROLE_ADMIN == "admin"
        assert ALL_ROLES == {"user", "admin"}

    def test_validate_user(self):
        assert validate_role("user") == "user"

    def test_validate_admin(self):
        assert validate_role("admin") == "admin"

    def test_validate_normalizes(self):
        assert validate_role("  ADMIN  ") == "admin"

    def test_validate_unknown(self):
        with pytest.raises(ValueError):
            validate_role("superadmin")

    def test_validate_not_str(self):
        with pytest.raises(ValueError):
            validate_role(123)

    def test_is_admin_role_true(self):
        assert is_admin_role("admin") is True
        assert is_admin_role("ADMIN") is True

    def test_is_admin_role_false(self):
        assert is_admin_role("user") is False
        assert is_admin_role("unknown") is False
        assert is_admin_role(None) is False
