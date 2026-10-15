from pathlib import Path
import pytest

# Функции импортируются из файла validators.py, который лежит в той же папе
from src.utils.validators import (
    RESERVED_LOGINS,
    safe_join,
    validate_login,
    validate_password,
    validate_path,
)


# =====================================================================
# ТЕСТЫ ДЛЯ validate_login
# =====================================================================

@pytest.mark.parametrize("valid_login, expected", [
    ("user123", "user123"),
    ("  User123  ", "user123"),  # Проверка strip() и lower()
    ("abc", "abc"),  # Минимальная длина (3 символа)
    ("a" * 32, "a" * 32),  # Максимальная длина (32 символа)
])
def test_validate_login_success(valid_login, expected):
    assert validate_login(valid_login) == expected


@pytest.mark.parametrize("invalid_type", [123, ["user"], None, True])
def test_validate_login_not_a_string(invalid_type):
    with pytest.raises(ValueError, match="Логин должен быть строкой"):
        validate_login(invalid_type)


@pytest.mark.parametrize("empty_login", ["", "   "])
def test_validate_login_empty(empty_login):
    with pytest.raises(ValueError, match="Логин не может быть пустым"):
        validate_login(empty_login)


@pytest.mark.parametrize("invalid_format, match_str", [
    ("123user", "Логин: 3–32 символа"),  # Начинается с цифры
    ("us", "Логин: 3–32 символа"),  # Слишком короткий (2 символа)
    ("a" * 33, "Логин: 3–32 символа"),  # Слишком длинный (33 символа)
    ("user_name", "Логин: 3–32 символа"),  # Запрещенный символ (_)
    ("user-name", "Логин: 3–32 символа"),  # Запрещенный символ (-)
])
def test_validate_login_invalid_format(invalid_format, match_str):
    with pytest.raises(ValueError, match=match_str):
        validate_login(invalid_format)


@pytest.mark.parametrize("reserved", list(RESERVED_LOGINS))
def test_validate_login_reserved(reserved):
    with pytest.raises(ValueError, match="Логин '.*' зарезервирован"):
        validate_login(reserved)
    with pytest.raises(ValueError, match="Логин '.*' зарезервирован"):
        validate_login(reserved.upper())


# =====================================================================
# ТЕСТЫ ДЛЯ validate_password
# =====================================================================

@pytest.mark.parametrize("valid_password", [
    "p@ssword123",
    "Short_8!",
    "!@#$%^&*()-_=+.,?",  # Все разрешенные спецсимволы
])
def test_validate_password_success(valid_password):
    assert validate_password(valid_password) is None


@pytest.mark.parametrize("invalid_type", [123, ["pass"], None, False])
def test_validate_password_not_a_string(invalid_type):
    with pytest.raises(ValueError, match="Пароль должен быть строкой"):
        validate_password(invalid_type)


def test_validate_password_too_short():
    with pytest.raises(ValueError, match="Пароль должен быть не короче 8 символов"):
        validate_password("short7")


@pytest.mark.parametrize("invalid_password, match_str", [
    ("password с пробелом", "Пароль может содержать только латиницу"),
    ("парольКириллица", "Пароль может содержать только латиницу"),
    ("password😊", "Пароль может содержать только латиницу"),  # Эмодзи
    ("password~", "Пароль может содержать только латиницу"),  # Запрещенный спецсимвол
])
def test_validate_password_invalid_characters(invalid_password, match_str):
    with pytest.raises(ValueError, match=match_str):
        validate_password(invalid_password)


# =====================================================================
# ТЕСТЫ ДЛЯ validate_path
# =====================================================================

def test_validate_path_success(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.touch()

    assert validate_path(str(test_file)) == test_file.resolve()
    assert validate_path(test_file) == test_file.resolve()


@pytest.mark.parametrize("invalid_type", [123, None, ["path"]])
def test_validate_path_not_string_or_path(invalid_type):
    with pytest.raises(ValueError, match="Путь должен быть строкой или Path"):
        validate_path(invalid_type)


def test_validate_path_not_found():
    non_existent = Path("non_existent_file_12345.txt")
    with pytest.raises(FileNotFoundError, match="Путь не существует"):
        validate_path(non_existent)


# =====================================================================
# ТЕСТЫ ДЛЯ safe_join
# =====================================================================

def test_safe_join_success(tmp_path):
    base = tmp_path / "base_dir"
    base.mkdir()

    result = safe_join(base, "sub_dir", "file.txt")
    assert result == (base / "sub_dir" / "file.txt").resolve()

    result_str = safe_join(str(base), "file.txt")
    assert result_str == (base / "file.txt").resolve()


@pytest.mark.parametrize("invalid_type", [123, None, ["base"]])
def test_safe_join_base_not_string_or_path(invalid_type):
    with pytest.raises(ValueError, match="base должен быть строкой или Path"):
        safe_join(invalid_type, "parts")


def test_safe_join_base_not_found():
    non_existent = Path("non_existent_base_dir_12345")
    with pytest.raises(FileNotFoundError, match="base не существует"):
        safe_join(non_existent, "file.txt")


def test_safe_join_path_traversal_attack(tmp_path):
    base = tmp_path / "base_dir"
    base.mkdir()

    with pytest.raises(ValueError, match="Path traversal detected"):
        safe_join(base, "..", "outside.txt")

    with pytest.raises(ValueError, match="Path traversal detected"):
        safe_join(base, "/etc/passwd")
