"""Тесты для src/storage/shared_store.py."""

import json
from pathlib import Path

import pytest

import src.storage.shared_store as shared_store
from src.core.crypto import fingerprint, generate_rsa_keypair
from src.storage.shared_store import (
    ALL_DIRS,
    auth_path,
    ensure_shared_structure,
    identity_path,
    load_auth,
    load_identity_blob,
    load_login_marker,
    load_pub_key,
    login_exists,
    login_marker_path,
    pub_key_path,
    read_json,
    save_auth,
    save_identity_blob,
    save_login_marker,
    save_pub_key,
    sha256_login,
    short_fp,
    write_bytes_atomic,
    write_json_atomic,
)


@pytest.fixture
def shared(tmp_path):
    """Создаёт пустую шару и возвращает путь."""
    d = tmp_path / "share"
    d.mkdir()
    ensure_shared_structure(d)
    return d


# ============================================================================
# Структура
# ============================================================================


class TestStructure:
    def test_creates_all_dirs(self, shared):
        for d in ALL_DIRS:
            assert (shared / d).is_dir()

    def test_idempotent(self, shared):
        # Повторный вызов не падает
        ensure_shared_structure(shared)


# ============================================================================
# Атомарная запись
# ============================================================================


class TestAtomicWrite:
    def test_write_bytes(self, tmp_path):
        p = tmp_path / "sub" / "file.bin"
        write_bytes_atomic(p, b"hello")
        assert p.read_bytes() == b"hello"
        assert list((tmp_path / "sub").glob("file.bin.*.tmp")) == []

    def test_write_bytes_retries_after_replace_error(self, tmp_path, monkeypatch):
        p = tmp_path / "file.bin"
        original_replace = shared_store.os.replace
        calls = 0

        def flaky_replace(src, dst):
            nonlocal calls
            calls += 1

            if calls == 1:
                raise PermissionError("Временная блокировка файла")

            return original_replace(src, dst)

        monkeypatch.setattr(shared_store.os, "replace", flaky_replace)
        monkeypatch.setattr(shared_store.time, "sleep", lambda _: None)

        write_bytes_atomic(p, b"new", retries=2)

        assert p.read_bytes() == b"new"
        assert calls == 2
        assert list(tmp_path.glob("file.bin.*.tmp")) == []

    def test_write_bytes_preserves_original_after_replace_failures(
        self, tmp_path, monkeypatch
    ):
        p = tmp_path / "file.bin"
        p.write_bytes(b"old")

        def failed_replace(src, dst):
            raise PermissionError("Файл занят")

        monkeypatch.setattr(shared_store.os, "replace", failed_replace)
        monkeypatch.setattr(shared_store.time, "sleep", lambda _: None)

        with pytest.raises(OSError, match="Не удалось атомарно заменить файл"):
            write_bytes_atomic(p, b"new", retries=2)

        assert p.read_bytes() == b"old"
        assert list(tmp_path.glob("file.bin.*.tmp")) == []

    def test_write_bytes_cleans_temp_after_fsync_error(self, tmp_path, monkeypatch):
        p = tmp_path / "file.bin"
        p.write_bytes(b"old")

        def failed_fsync(fd):
            raise OSError("Ошибка fsync")

        monkeypatch.setattr(shared_store.os, "fsync", failed_fsync)

        with pytest.raises(OSError, match="Ошибка fsync"):
            write_bytes_atomic(p, b"new")

        assert p.read_bytes() == b"old"
        assert list(tmp_path.glob("file.bin.*.tmp")) == []

    def test_write_json(self, tmp_path):
        p = tmp_path / "data.json"
        write_json_atomic(p, {"a": 1, "б": "строка"})
        assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1, "б": "строка"}

    def test_read_json_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_json(tmp_path / "none.json")

    def test_read_json_corrupted(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ValueError, match="Некорректный JSON"):
            read_json(p)


# ============================================================================
# Хеши / fingerprint
# ============================================================================


class TestHashes:
    def test_sha256_login(self):
        h = sha256_login("vasya")
        assert len(h) == 64
        int(h, 16)  # валидный hex

    def test_sha256_deterministic(self):
        assert sha256_login("vasya") == sha256_login("vasya")

    def test_sha256_different(self):
        assert sha256_login("vasya") != sha256_login("petya")

    def test_sha256_not_reversible(self):
        h = sha256_login("secret_login")
        assert "secret_login" not in h

    def test_sha256_empty_raises(self):
        with pytest.raises(ValueError):
            sha256_login("")

    def test_sha256_wrong_type(self):
        with pytest.raises(ValueError):
            sha256_login(123)

    def test_short_fp(self):
        full = "a" * 64
        assert short_fp(full) == "a" * 16
        assert short_fp(full, length=8) == "a" * 8
        assert short_fp(full, length=32) == "a" * 32

    def test_short_fp_invalid_length(self):
        full = "a" * 64
        with pytest.raises(ValueError):
            short_fp(full, length=7)  # < 8
        with pytest.raises(ValueError):
            short_fp(full, length=65)  # > len


# ============================================================================
# .logins/
# ============================================================================


class TestLogins:
    def test_marker_path(self, shared):
        p = login_marker_path(shared, "vasya")
        assert p.parent.name == ".logins"
        assert len(p.name) == 64  # sha256

    def test_marker_not_exists(self, shared):
        assert login_exists(shared, "vasya") is False

    def test_save_and_exists(self, shared):
        save_login_marker(shared, "vasya", "a" * 64)
        assert login_exists(shared, "vasya") is True

    def test_save_twice_raises(self, shared):
        save_login_marker(shared, "vasya", "a" * 64)
        with pytest.raises(FileExistsError):
            save_login_marker(shared, "vasya", "b" * 64)

    def test_load_marker(self, shared):
        save_login_marker(shared, "vasya", "a" * 64)
        marker = load_login_marker(shared, "vasya")
        assert marker["fp"] == "a" * 64
        assert "created_at" in marker

    def test_load_missing(self, shared):
        with pytest.raises(FileNotFoundError):
            load_login_marker(shared, "nobody")


# ============================================================================
# .keys/ .auth/ .identities/
# ============================================================================


class TestKeysAuthIdentity:
    def test_pub_key_round_trip(self, shared):
        _, pem = generate_rsa_keypair()
        fp = fingerprint(pem)

        path = save_pub_key(shared, fp, pem)

        assert path.is_file()
        assert load_pub_key(shared, fp) == pem

    def test_pub_key_rejects_wrong_fingerprint(self, shared):
        _, pem = generate_rsa_keypair()
        wrong_fp = "a" * 64

        with pytest.raises(ValueError):
            save_pub_key(shared, wrong_fp, pem)

    def test_pub_key_rejects_tampered_file(self, shared):
        _, pem = generate_rsa_keypair()
        fp = fingerprint(pem)

        save_pub_key(shared, fp, pem)

        path = pub_key_path(shared, fp)
        _, another_pem = generate_rsa_keypair()
        path.write_text(another_pem, encoding="ascii")

        with pytest.raises(ValueError):
            load_pub_key(shared, fp)

    def test_pub_key_missing(self, shared):
        with pytest.raises(FileNotFoundError):
            load_pub_key(shared, "a" * 64)

    def test_auth_round_trip(self, shared):
        fp = "a" * 64
        h = "$argon2id$v=19$m=65536,t=3,p=4$salt$hash"
        save_auth(shared, fp, h)
        assert load_auth(shared, fp) == h

    def test_auth_missing(self, shared):
        with pytest.raises(FileNotFoundError):
            load_auth(shared, "a" * 64)

    def test_identity_round_trip(self, shared):
        fp = "a" * 64
        blob = b'{"test": "data"}'
        save_identity_blob(shared, fp, blob)
        assert load_identity_blob(shared, fp) == blob

    def test_identity_missing(self, shared):
        with pytest.raises(FileNotFoundError):
            load_identity_blob(shared, "a" * 64)


# ============================================================================
# Безопасность путей
# ============================================================================


class TestSecurity:
    def test_path_traversal_in_sha256(self, shared):
        # sha256_login кидает ValueError на пустой/None, но не на "../"
        # Проверим, что результат — только hex, без слэшей
        h = sha256_login("../../etc/passwd")
        assert "/" not in h
        assert "\\" not in h
        assert len(h) == 64

    def test_pub_key_path_no_traversal(self, shared):
        # short_fp берёт только hex, слэши невозможны
        p = pub_key_path(shared, "a" * 64)
        assert p.parent == shared / ".keys"
