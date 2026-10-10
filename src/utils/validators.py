"""Валидаторы Pygram: проверка логина, пароля, путей.

Все функции бросают ValueError при невалидных данных.
"""

import re
from pathlib import Path


# Зарезервированные логины: нельзя использовать (конфликтуют с системой)
RESERVED_LOGINS = {"admin", "system", "root", "me", "self", "admin_chat"}

# Логин: 3–32 символа, начинается с буквы, только a-z и 0-9
LOGIN_RE = re.compile(r"^[a-z][a-z0-9]{2,31}$")

# Пароль: минимум 8 символов
PASSWORD_MIN_LENGTH = 8

# Разрешённые символы пароля: латиница, цифры, безопасные спецсимволы
PASSWORD_ALLOWED_RE = re.compile(r"^[a-zA-Z0-9!@#$%^&*()\-_=+.,?]+$")


def validate_login(login: str) -> str:
    """Проверяет логин. Возвращает нормализованный (lowercase, без пробелов).

    Raises:
        ValueError: если логин невалиден.
    """
    if not isinstance(login, str):
        raise ValueError("Логин должен быть строкой")

    login = login.strip().lower()

    if not login:
        raise ValueError("Логин не может быть пустым")

    if not LOGIN_RE.match(login):
        raise ValueError(
            "Логин: 3–32 символа, только a-z и 0-9, "
            "начинается с буквы"
        )

    if login in RESERVED_LOGINS:
        raise ValueError(f"Логин '{login}' зарезервирован")

    return login

def validate_password(password: str) -> None:
    """Проверяет пароль. Бросает ValueError, если невалиден.

    Требования:
        - минимум 8 символов;
        - только латиница, цифры, безопасные спецсимволы;
        - кириллица, пробелы, эмодзи запрещены.

    Raises:
        ValueError: если пароль невалиден.
    """
    if not isinstance(password, str):
        raise ValueError("Пароль должен быть строкой")

    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Пароль должен быть не короче {PASSWORD_MIN_LENGTH} символов"
        )

    if not PASSWORD_ALLOWED_RE.match(password):
        raise ValueError(
            "Пароль может содержать только латиницу, цифры "
            "и символы: !@#$%^&*()-_=+.,?"
        )


def validate_path(path: str | Path) -> Path:
    """Проверяет, что путь существует и доступен.

    Args:
        path: Путь в виде строки или Path.

    Returns:
        Path: Нормализованный (resolve) объект Path.

    Raises:
        ValueError: если путь невалиден.
        FileNotFoundError: если путь не существует.
    """
    if not isinstance(path, (str, Path)):
        raise ValueError("Путь должен быть строкой или Path")

    p = Path(path).expanduser().resolve()

    if not p.exists():
        raise FileNotFoundError(f"Путь не существует: {p}")

    return p


def safe_join(base: Path | str, *parts: str) -> Path:
    """Безопасно соединяет пути, защищая от path traversal.

    Проверяет, что итоговый путь находится ВНУТРИ base.
    Если нет — бросает ValueError.

    Args:
        base: Базовая папка (например, shared_folder).
        *parts: Компоненты пути (например, "dm_vasya", "file.bin").

    Returns:
        Path: Нормализованный путь внутри base.

    Raises:
        ValueError: если путь выходит за пределы base.
    """
    if not isinstance(base, (str, Path)):
        raise ValueError("base должен быть строкой или Path")

    base_path = Path(base).expanduser().resolve()

    if not base_path.exists():
        raise FileNotFoundError(f"base не существует: {base_path}")

    result = (base_path / Path(*parts)).resolve()

    if not result.is_relative_to(base_path):
        raise ValueError(
            f"Path traversal detected: {result} вне {base_path}"
        )

    return result