"""Роли Pygram."""

from __future__ import annotations


ROLE_USER = "user"
ROLE_ADMIN = "admin"

ALL_ROLES = {ROLE_USER, ROLE_ADMIN}


def validate_role(role: str) -> str:
    """Проверяет, что роль валидна. Возвращает нормализованную.

    Raises:
        ValueError: если роль неизвестна.
    """
    if not isinstance(role, str):
        raise ValueError("role должен быть строкой")
    role = role.lower().strip()
    if role not in ALL_ROLES:
        raise ValueError(f"Неизвестная роль: {role}. Допустимые: {ALL_ROLES}")
    return role


def is_admin_role(role: str) -> bool:
    """True, если роль — админ."""
    try:
        return validate_role(role) == ROLE_ADMIN
    except ValueError:
        return False
