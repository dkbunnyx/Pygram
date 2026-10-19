"""Тесты для src/core/identity.py."""

import json
from pathlib import Path

import pytest

from src.core.crypto import fingerprint, load_private_key
from src.core.identity import (
    IDENTITY_VERSION,
    authenticate,
    change_password,
    generate_identity,
    get_fp16,
    identity_exists,
    register_identity,
)
from src.storage.shared_store import (
    ensure_shared_structure,
    identity_path,
    load_auth,
    load_identity_blob,
    load_login_marker,
    load_pub_key,
)


@pytest.fixture
def shared(tmp_path):
    """Готовая шара."""
    d = tmp_path / "share"
    d.mkdir()
    ensure_shared_structure(d)
    return d


# ============================================================================
# generate_identity
# ============================================================================

class TestGenerate:
    def test_returns_pems(self):
        priv, pub = generate_identity("vasya", "Passw0rd!")
        assert "PRIVATE KEY" in priv
        assert "PUBLIC KEY" in pub

    def test_different_each_time(self):
        priv1, pub1 = generate_identity("vasya", "Passw0rd!")
        priv2, pub2 = generate_identity("vasya", "Passw0rd!")
        assert priv1 != priv2
        assert pub1 != pub2

    def test_empty_login(self):
        with pytest.raises(ValueError):
            generate_identity("", "Passw0rd!")

    def test_empty_password(self):
        with pytest.raises(ValueError):
            generate_identity("vasya", "")


# ============================================================================
# register_identity
# ============================================================================

class TestRegister:
    def test_creates_all_files(self, shared):
        fp16 = register_identity(shared, "vasya", "Passw0rd!")
        assert len(fp16) == 16

        # Маркер
        marker = load_login_marker(shared, "vasya")
        fp = marker["fp"]
        assert fp[:16] == fp16

        # Публичный ключ
        pub = load_pub_key(shared, fp)
        assert "PUBLIC KEY" in pub

        # Argon2id-хеш
        h = load_auth(shared, fp)
        assert h.startswith("$argon2id$")

        # Зашифрованный приватник
        blob = load_identity_blob(shared, fp)
        container = json.loads(blob.decode("utf-8"))
        assert container["version"] == IDENTITY_VERSION
        assert container["fp"] == fp
        assert container["kdf"]["algo"] == "argon2id"
        assert container["cipher"]["algo"] == "aes-256-gcm"

    def test_login_occupied(self, shared):
        register_identity(shared, "vasya", "Passw0rd!")
        with pytest.raises(FileExistsError):
            register_identity(shared, "vasya", "OtherPass!")

    def test_identity_exists(self, shared):
        assert identity_exists(shared, "vasya") is False
        register_identity(shared, "vasya", "Passw0rd!")
        assert identity_exists(shared, "vasya") is True

    def test_get_fp16(self, shared):
        assert get_fp16(shared, "vasya") is None
        fp16 = register_identity(shared, "vasya", "Passw0rd!")
        assert get_fp16(shared, "vasya") == fp16


# ============================================================================
# authenticate
# ============================================================================

class TestAuth:
    def test_success(self, shared):
        fp16 = register_identity(shared, "vasya", "Passw0rd!")
        priv, got_fp16 = authenticate(shared, "vasya", "Passw0rd!")
        assert got_fp16 == fp16
        assert "PRIVATE KEY" in priv

    def test_returns_same_priv(self, shared):
        # Сохраняем публичный ключ, чтобы сверить fingerprint
        fp16 = register_identity(shared, "vasya", "Passw0rd!")
        marker = load_login_marker(shared, "vasya")
        fp = marker["fp"]
        pub = load_pub_key(shared, fp)

        priv, _ = authenticate(shared, "vasya", "Passw0rd!")
        priv_pub = load_private_key(priv).publickey().export_key().decode("ascii")
        assert fingerprint(priv_pub) == fingerprint(pub)

    def test_wrong_password(self, shared):
        register_identity(shared, "vasya", "Passw0rd!")
        with pytest.raises(ValueError, match="Неверный пароль"):
            authenticate(shared, "vasya", "wrong")

    def test_user_not_found(self, shared):
        with pytest.raises(FileNotFoundError):
            authenticate(shared, "nobody", "Passw0rd!")


# ============================================================================
# Tampering
# ============================================================================

class TestTampering:
    def _get_identity_path(self, shared, login):
        marker = load_login_marker(shared, login)
        return identity_path(shared, marker["fp"])

    def test_tampered_ciphertext(self, shared):
        register_identity(shared, "vasya", "Passw0rd!")
        path = self._get_identity_path(shared, "vasya")
        data = json.loads(path.read_bytes().decode("utf-8"))
        # Портим первый символ base64
        ct = data["cipher"]["ciphertext"]
        data["cipher"]["ciphertext"] = ("A" if ct[0] != "A" else "B") + ct[1:]
        path.write_bytes(json.dumps(data).encode("utf-8"))

        with pytest.raises(ValueError):
            authenticate(shared, "vasya", "Passw0rd!")

    def test_tampered_fp(self, shared):
        register_identity(shared, "vasya", "Passw0rd!")
        path = self._get_identity_path(shared, "vasya")
        data = json.loads(path.read_bytes().decode("utf-8"))
        data["fp"] = "0" * 64
        path.write_bytes(json.dumps(data).encode("utf-8"))

        with pytest.raises(ValueError, match="Fingerprint"):
            authenticate(shared, "vasya", "Passw0rd!")

    def test_tampered_version(self, shared):
        register_identity(shared, "vasya", "Passw0rd!")
        path = self._get_identity_path(shared, "vasya")
        data = json.loads(path.read_bytes().decode("utf-8"))
        data["version"] = 99
        path.write_bytes(json.dumps(data).encode("utf-8"))

        with pytest.raises(ValueError, match="версия"):
            authenticate(shared, "vasya", "Passw0rd!")

    def test_missing_field(self, shared):
        register_identity(shared, "vasya", "Passw0rd!")
        path = self._get_identity_path(shared, "vasya")
        data = json.loads(path.read_bytes().decode("utf-8"))
        del data["cipher"]
        path.write_bytes(json.dumps(data).encode("utf-8"))

        with pytest.raises(ValueError, match="cipher"):
            authenticate(shared, "vasya", "Passw0rd!")

    def test_broken_json(self, shared):
        register_identity(shared, "vasya", "Passw0rd!")
        path = self._get_identity_path(shared, "vasya")
        path.write_bytes(b"{not valid json")
        with pytest.raises(ValueError):
            authenticate(shared, "vasya", "Passw0rd!")


# ============================================================================
# change_password
# ============================================================================

class TestChangePassword:
    def test_success(self, shared):
        register_identity(shared, "vasya", "OldPass1!")
        change_password(shared, "vasya", "OldPass1!", "NewPass2!")

        # Старый не работает
        with pytest.raises(ValueError, match="Неверный пароль"):
            authenticate(shared, "vasya", "OldPass1!")

        # Новый работает
        priv, _ = authenticate(shared, "vasya", "NewPass2!")
        assert "PRIVATE KEY" in priv

    def test_priv_pem_preserved(self, shared):
        """Ключи не перегенерируются."""
        register_identity(shared, "vasya", "OldPass1!")
        priv_before, _ = authenticate(shared, "vasya", "OldPass1!")

        change_password(shared, "vasya", "OldPass1!", "NewPass2!")

        priv_after, _ = authenticate(shared, "vasya", "NewPass2!")
        assert priv_before == priv_after

    def test_wrong_old_password(self, shared):
        register_identity(shared, "vasya", "OldPass1!")
        with pytest.raises(ValueError):
            change_password(shared, "vasya", "WrongPass", "NewPass2!")

    def test_empty_new_password(self, shared):
        register_identity(shared, "vasya", "OldPass1!")
        with pytest.raises(ValueError):
            change_password(shared, "vasya", "OldPass1!", "")