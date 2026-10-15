"""Тесты для src/core/crypto.py.

Покрывают:
- AES-256-GCM: round-trip, AAD, детект подмены
- RSA-3072: генерация, OAEP round-trip, PSS sign/verify
- Argon2id: hash/verify, needs_rehash
- PBKDF2: derive_key детерминизм
- Base64/Hex: round-trip, ошибки
- UUID/random: формат, длина
- Fingerprint: детерминизм, разные ключи → разные отпечатки
- Hybrid: round-trip на 2 получателя, недоступность чужому
"""

import pytest

from src.core.crypto import (
    # Утилиты
    to_base64, from_base64,
    to_hex, from_hex,
    generate_uuid, generate_random_string,
    # AES
    AES_KEY_SIZE, AES_NONCE_SIZE,
    generate_aes_key, generate_nonce,
    aes_encrypt, aes_decrypt,
    # RSA
    generate_rsa_keypair,
    load_private_key, load_public_key,
    fingerprint,
    rsa_encrypt, rsa_decrypt,
    rsa_sign, rsa_verify,
    # Argon2
    hash_password, verify_password, needs_rehash,
    # PBKDF2
    generate_salt, derive_key,
    # Hybrid
    wrap_key_for_recipients, unwrap_key,
    hybrid_encrypt, hybrid_decrypt,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(scope="module")
def rsa_keypair():
    """Одна пара RSA на весь модуль (генерация ~1 сек)."""
    priv, pub = generate_rsa_keypair()
    return priv, pub


@pytest.fixture(scope="module")
def rsa_keypair_other():
    """Вторая пара — для проверки, что чужой не расшифрует."""
    priv, pub = generate_rsa_keypair()
    return priv, pub


# ============================================================================
# BASE64 / HEX
# ============================================================================

class TestBase64:
    def test_round_trip(self):
        assert from_base64(to_base64(b"hello")) == b"hello"
        assert from_base64(to_base64(b"")) == b""
        assert from_base64(to_base64(b"\x00\xff\xfe")) == b"\x00\xff\xfe"

    def test_to_base64_type_error(self):
        with pytest.raises(TypeError):
            to_base64("not bytes")
        with pytest.raises(TypeError):
            to_base64(123)

    def test_from_base64_invalid(self):
        with pytest.raises((ValueError, Exception)):
            from_base64("not valid base64!!!")
        with pytest.raises(TypeError):
            from_base64(b"bytes not str")


class TestHex:
    def test_round_trip(self):
        assert from_hex(to_hex(b"hi")) == b"hi"
        assert from_hex(to_hex(b"")) == b""
        assert from_hex(to_hex(b"\x00\xff")) == b"\x00\xff"

    def test_to_hex_type_error(self):
        with pytest.raises(TypeError):
            to_hex("not bytes")

    def test_from_hex_invalid(self):
        with pytest.raises(ValueError):
            from_hex("xyz")


# ============================================================================
# UUID / RANDOM
# ============================================================================

class TestUuidRandom:
    def test_uuid_format(self):
        u = generate_uuid()
        assert isinstance(u, str)
        assert len(u) == 36
        assert u.count("-") == 4

    def test_uuid_unique(self):
        assert generate_uuid() != generate_uuid()

    def test_random_string_length(self):
        assert len(generate_random_string(32)) == 32
        assert len(generate_random_string(2)) == 2

    def test_random_string_hex(self):
        s = generate_random_string(32)
        int(s, 16)  # не бросит — значит hex

    def test_random_string_unique(self):
        assert generate_random_string(32) != generate_random_string(32)

    def test_random_string_invalid(self):
        with pytest.raises(ValueError):
            generate_random_string(0)
        with pytest.raises(ValueError):
            generate_random_string(3)  # нечётная


# ============================================================================
# AES-256-GCM
# ============================================================================

class TestAes:
    def test_constants(self):
        assert AES_KEY_SIZE == 32
        assert AES_NONCE_SIZE == 12

    def test_generate_aes_key(self):
        k = generate_aes_key()
        assert isinstance(k, bytes)
        assert len(k) == AES_KEY_SIZE
        assert generate_aes_key() != generate_aes_key()

    def test_generate_nonce(self):
        n = generate_nonce()
        assert isinstance(n, bytes)
        assert len(n) == AES_NONCE_SIZE
        assert generate_nonce() != generate_nonce()

    def test_encrypt_decrypt_round_trip(self):
        key = generate_aes_key()
        nonce, ct = aes_encrypt(key, b"secret")
        assert aes_decrypt(key, nonce, ct) == b"secret"

    def test_encrypt_decrypt_empty(self):
        key = generate_aes_key()
        nonce, ct = aes_encrypt(key, b"")
        assert aes_decrypt(key, nonce, ct) == b""

    def test_encrypt_decrypt_large(self):
        key = generate_aes_key()
        data = b"x" * 100_000
        nonce, ct = aes_encrypt(key, data)
        assert aes_decrypt(key, nonce, ct) == data

    def test_aad_round_trip(self):
        key = generate_aes_key()
        nonce, ct = aes_encrypt(key, b"data", aad=b"chat1")
        assert aes_decrypt(key, nonce, ct, aad=b"chat1") == b"data"

    def test_aad_mismatch(self):
        key = generate_aes_key()
        nonce, ct = aes_encrypt(key, b"data", aad=b"chat1")
        with pytest.raises(ValueError):
            aes_decrypt(key, nonce, ct, aad=b"chat2")

    def test_aad_missing_but_was_set(self):
        key = generate_aes_key()
        nonce, ct = aes_encrypt(key, b"data", aad=b"chat1")
        with pytest.raises(ValueError):
            aes_decrypt(key, nonce, ct)  # не передали AAD

    def test_wrong_key(self):
        k1 = generate_aes_key()
        k2 = generate_aes_key()
        nonce, ct = aes_encrypt(k1, b"data")
        with pytest.raises(ValueError):
            aes_decrypt(k2, nonce, ct)

    def test_tampered_ciphertext(self):
        key = generate_aes_key()
        nonce, ct = aes_encrypt(key, b"data")
        tampered = bytearray(ct)
        tampered[0] ^= 0xFF
        with pytest.raises(ValueError):
            aes_decrypt(key, nonce, bytes(tampered))

    def test_tampered_nonce(self):
        key = generate_aes_key()
        nonce, ct = aes_encrypt(key, b"data")
        bad_nonce = bytes(b ^ 0xFF for b in nonce)
        with pytest.raises(ValueError):
            aes_decrypt(key, bad_nonce, ct)

    def test_wrong_key_size(self):
        with pytest.raises(ValueError):
            aes_encrypt(b"short", b"data")
        with pytest.raises(ValueError):
            aes_encrypt(b"x" * 33, b"data")

    def test_wrong_nonce_size(self):
        key = generate_aes_key()
        nonce, ct = aes_encrypt(key, b"data")
        with pytest.raises(ValueError):
            aes_decrypt(key, b"short", ct)


# ============================================================================
# RSA-3072
# ============================================================================

class TestRsaKeys:
    def test_generate_keypair_pem(self, rsa_keypair):
        priv, pub = rsa_keypair
        assert isinstance(priv, str)
        assert isinstance(pub, str)
        assert "BEGIN RSA PRIVATE KEY" in priv or "BEGIN PRIVATE KEY" in priv
        assert "BEGIN PUBLIC KEY" in pub

    def test_two_keypairs_differ(self, rsa_keypair, rsa_keypair_other):
        priv1, pub1 = rsa_keypair
        priv2, pub2 = rsa_keypair_other
        assert priv1 != priv2
        assert pub1 != pub2

    def test_load_private(self, rsa_keypair):
        priv, _ = rsa_keypair
        k = load_private_key(priv)
        assert k.has_private()

    def test_load_public(self, rsa_keypair):
        _, pub = rsa_keypair
        k = load_public_key(pub)
        assert not k.has_private()

    def test_load_public_from_private_returns_pub(self, rsa_keypair):
        priv, _ = rsa_keypair
        k = load_public_key(priv)
        assert not k.has_private()

    def test_load_invalid_pem(self):
        with pytest.raises(ValueError):
            load_private_key("not a pem")
        with pytest.raises(ValueError):
            load_public_key("not a pem")


class TestFingerprint:
    def test_deterministic(self, rsa_keypair):
        _, pub = rsa_keypair
        assert fingerprint(pub) == fingerprint(pub)

    def test_different_keys_different_fp(self, rsa_keypair, rsa_keypair_other):
        _, pub1 = rsa_keypair
        _, pub2 = rsa_keypair_other
        assert fingerprint(pub1) != fingerprint(pub2)

    def test_length(self, rsa_keypair):
        _, pub = rsa_keypair
        fp = fingerprint(pub)
        assert len(fp) == 64  # SHA-256 hex
        int(fp, 16)  # валидный hex


class TestRsaOaep:
    def test_round_trip(self, rsa_keypair):
        priv, pub = rsa_keypair
        data = b"secret 32 bytes or less"
        ct = rsa_encrypt(pub, data)
        assert rsa_decrypt(priv, ct) == data

    def test_round_trip_max_size(self, rsa_keypair):
        priv, pub = rsa_keypair
        data = b"x" * 318
        ct = rsa_encrypt(pub, data)
        assert rsa_decrypt(priv, ct) == data

    def test_too_large(self, rsa_keypair):
        _, pub = rsa_keypair
        with pytest.raises(ValueError):
            rsa_encrypt(pub, b"x" * 319)

    def test_wrong_private_key(self, rsa_keypair, rsa_keypair_other):
        _, pub = rsa_keypair
        priv2, _ = rsa_keypair_other
        ct = rsa_encrypt(pub, b"data")
        with pytest.raises(ValueError):
            rsa_decrypt(priv2, ct)

    def test_encrypt_type_error(self, rsa_keypair):
        _, pub = rsa_keypair
        with pytest.raises(TypeError):
            rsa_encrypt(pub, "not bytes")


class TestRsaPss:
    def test_sign_verify_ok(self, rsa_keypair):
        priv, pub = rsa_keypair
        sig = rsa_sign(priv, b"message")
        assert rsa_verify(pub, b"message", sig) is True

    def test_verify_tampered_data(self, rsa_keypair):
        priv, pub = rsa_keypair
        sig = rsa_sign(priv, b"message")
        assert rsa_verify(pub, b"tampered", sig) is False

    def test_verify_tampered_signature(self, rsa_keypair):
        priv, pub = rsa_keypair
        sig = rsa_sign(priv, b"message")
        bad_sig = bytes(b ^ 0xFF for b in sig)
        assert rsa_verify(pub, b"message", bad_sig) is False

    def test_verify_wrong_key(self, rsa_keypair, rsa_keypair_other):
        priv1, _ = rsa_keypair
        _, pub2 = rsa_keypair_other
        sig = rsa_sign(priv1, b"message")
        assert rsa_verify(pub2, b"message", sig) is False

    def test_sign_verify_empty(self, rsa_keypair):
        priv, pub = rsa_keypair
        sig = rsa_sign(priv, b"")
        assert rsa_verify(pub, b"", sig) is True


# ============================================================================
# ARGON2ID
# ============================================================================

class TestArgon2:
    def test_hash_returns_string(self):
        h = hash_password("password123")
        assert isinstance(h, str)
        assert h.startswith("$argon2id$")

    def test_hash_different_salt(self):
        h1 = hash_password("password123")
        h2 = hash_password("password123")
        assert h1 != h2  # разные соли

    def test_verify_ok(self):
        h = hash_password("password123")
        assert verify_password("password123", h) is True

    def test_verify_wrong(self):
        h = hash_password("password123")
        assert verify_password("wrong", h) is False

    def test_hash_empty_raises(self):
        with pytest.raises(ValueError):
            hash_password("")

    def test_hash_not_str(self):
        with pytest.raises(TypeError):
            hash_password(123)

    def test_needs_rehash_false(self):
        h = hash_password("password123")
        assert needs_rehash(h) is False

    def test_needs_rehash_invalid_hash(self):
        assert needs_rehash("$invalid$hash") is True


# ============================================================================
# PBKDF2 (derive_key)
# ============================================================================

class TestPbkdf2:
    def test_derive_deterministic(self):
        salt = generate_salt()
        k1 = derive_key("password", salt)
        k2 = derive_key("password", salt)
        assert k1 == k2

    def test_derive_different_salt(self):
        k1 = derive_key("password", generate_salt())
        k2 = derive_key("password", generate_salt())
        assert k1 != k2

    def test_derive_different_password(self):
        salt = generate_salt()
        k1 = derive_key("password1", salt)
        k2 = derive_key("password2", salt)
        assert k1 != k2

    def test_derive_key_length(self):
        k = derive_key("password", generate_salt())
        assert len(k) == 32

    def test_derive_empty_password(self):
        with pytest.raises(ValueError):
            derive_key("", generate_salt())

    def test_derive_short_salt(self):
        with pytest.raises(ValueError):
            derive_key("password", b"short")

    def test_generate_salt_length(self):
        assert len(generate_salt()) == 16
        assert len(generate_salt(32)) == 32

    def test_generate_salt_min(self):
        with pytest.raises(ValueError):
            generate_salt(4)


# ============================================================================
# HYBRID (AES + RSA)
# ============================================================================

class TestHybrid:
    def test_wrap_unwrap(self, rsa_keypair):
        priv, pub = rsa_keypair
        key = generate_aes_key()
        wrapped = wrap_key_for_recipients(key, {"vasya": pub})
        fp = fingerprint(pub)
        assert unwrap_key(wrapped, fp, priv) == key

    def test_wrap_two_recipients(self, rsa_keypair, rsa_keypair_other):
        priv1, pub1 = rsa_keypair
        priv2, pub2 = rsa_keypair_other
        key = generate_aes_key()
        wrapped = wrap_key_for_recipients(key, {"a": pub1, "b": pub2})
        assert unwrap_key(wrapped, fingerprint(pub1), priv1) == key
        assert unwrap_key(wrapped, fingerprint(pub2), priv2) == key

    def test_unwrap_missing_fp(self, rsa_keypair):
        priv, pub = rsa_keypair
        wrapped = wrap_key_for_recipients(generate_aes_key(), {"a": pub})
        with pytest.raises(ValueError):
            unwrap_key(wrapped, "0" * 64, priv)

    def test_hybrid_round_trip(self, rsa_keypair):
        priv, pub = rsa_keypair
        pkg = hybrid_encrypt(b"secret message", {"vasya": pub})
        fp = fingerprint(pub)
        assert hybrid_decrypt(pkg, fp, priv) == b"secret message"

    def test_hybrid_round_trip_with_aad(self, rsa_keypair):
        priv, pub = rsa_keypair
        pkg = hybrid_encrypt(b"data", {"vasya": pub}, aad=b"chat1")
        fp = fingerprint(pub)
        assert hybrid_decrypt(pkg, fp, priv, aad=b"chat1") == b"data"

    def test_hybrid_wrong_aad(self, rsa_keypair):
        priv, pub = rsa_keypair
        pkg = hybrid_encrypt(b"data", {"vasya": pub}, aad=b"chat1")
        fp = fingerprint(pub)
        with pytest.raises(ValueError):
            hybrid_decrypt(pkg, fp, priv, aad=b"chat2")

    def test_hybrid_two_recipients(self, rsa_keypair, rsa_keypair_other):
        priv1, pub1 = rsa_keypair
        priv2, pub2 = rsa_keypair_other
        pkg = hybrid_encrypt(b"hello both", {"a": pub1, "b": pub2})
        assert hybrid_decrypt(pkg, fingerprint(pub1), priv1) == b"hello both"
        assert hybrid_decrypt(pkg, fingerprint(pub2), priv2) == b"hello both"

    def test_hybrid_stranger_cannot_decrypt(self, rsa_keypair, rsa_keypair_other):
        _, pub1 = rsa_keypair
        priv2, pub2 = rsa_keypair_other
        pkg = hybrid_encrypt(b"top secret", {"a": pub1})
        with pytest.raises(ValueError):
            hybrid_decrypt(pkg, fingerprint(pub2), priv2)

    def test_hybrid_package_structure(self, rsa_keypair):
        _, pub = rsa_keypair
        pkg = hybrid_encrypt(b"data", {"a": pub})
        assert "nonce" in pkg
        assert "ciphertext" in pkg
        assert "wrapped_keys" in pkg
        assert len(pkg["wrapped_keys"]) == 1

    def test_wrap_empty_recipients(self):
        with pytest.raises(ValueError):
            wrap_key_for_recipients(generate_aes_key(), {})

    def test_wrap_wrong_key_size(self, rsa_keypair):
        _, pub = rsa_keypair
        with pytest.raises(ValueError):
            wrap_key_for_recipients(b"short", {"a": pub})
# ============================================================================
# EDGE CASES: непокрытые ветки
# ============================================================================

class TestEdgeCases:
    """Добиваем непокрытые строки: защитные проверки типов."""

    def test_from_base64_wrong_type(self):
        with pytest.raises(TypeError):
            from_base64(b"bytes")

    def test_aes_encrypt_wrong_plaintext_type(self):
        key = generate_aes_key()
        with pytest.raises(TypeError):
            aes_encrypt(key, "not bytes")

    def test_aes_encrypt_wrong_key_type(self):
        with pytest.raises(TypeError):
            aes_encrypt("not bytes", b"data")

    def test_aes_decrypt_wrong_ciphertext_type(self):
        key = generate_aes_key()
        nonce, _ = aes_encrypt(key, b"data")
        with pytest.raises(TypeError):
            aes_decrypt(key, nonce, "not bytes")

    def test_aes_decrypt_short_ciphertext(self):
        key = generate_aes_key()
        nonce = generate_nonce()
        with pytest.raises(ValueError):
            aes_decrypt(key, nonce, b"short")  # < 16 байт

    def test_load_private_wrong_type(self):
        with pytest.raises(TypeError):
            load_private_key(b"bytes")

    def test_load_public_wrong_type(self):
        with pytest.raises(TypeError):
            load_public_key(123)

    def test_fingerprint_wrong_type(self):
        with pytest.raises(TypeError):
            fingerprint(b"bytes")

    def test_rsa_encrypt_wrong_type(self, rsa_keypair):
        _, pub = rsa_keypair
        with pytest.raises(TypeError):
            rsa_encrypt(pub, "not bytes")

    def test_rsa_decrypt_wrong_type(self, rsa_keypair):
        priv, _ = rsa_keypair
        with pytest.raises(TypeError):
            rsa_decrypt(priv, "not bytes")

    def test_rsa_sign_wrong_type(self, rsa_keypair):
        priv, _ = rsa_keypair
        with pytest.raises(TypeError):
            rsa_sign(priv, "not bytes")

    def test_rsa_verify_wrong_types(self, rsa_keypair):
        priv, pub = rsa_keypair
        sig = rsa_sign(priv, b"msg")
        with pytest.raises(TypeError):
            rsa_verify(pub, "not bytes", sig)
        with pytest.raises(TypeError):
            rsa_verify(pub, b"msg", "not bytes")

    def test_rsa_verify_signature_wrong_length(self, rsa_keypair):
        """Битая подпись неверной длины — не должна падать."""
        _, pub = rsa_keypair
        # Слишком короткая подпись
        assert rsa_verify(pub, b"msg", b"short") is False
        # Слишком длинная
        assert rsa_verify(pub, b"msg", b"x" * 1000) is False

    def test_verify_password_wrong_type(self):
        h = hash_password("password123")
        with pytest.raises(TypeError):
            verify_password(123, h)
        with pytest.raises(TypeError):
            verify_password("password123", 123)

    def test_verify_password_invalid_hash(self):
        """Битый хеш → ValueError, а не False."""
        with pytest.raises(ValueError):
            verify_password("password123", "$invalid$hash$format")

    def test_hash_password_empty(self):
        with pytest.raises(ValueError):
            hash_password("")

    def test_hash_password_wrong_type(self):
        with pytest.raises(TypeError):
            hash_password(123)

    def test_derive_key_empty_password(self):
        with pytest.raises(ValueError):
            derive_key("", generate_salt())

    def test_derive_key_wrong_type(self):
        with pytest.raises(TypeError):
            derive_key(123, generate_salt())
        with pytest.raises(TypeError):
            derive_key("pass", "not bytes")

    def test_derive_key_short_salt(self):
        with pytest.raises(ValueError):
            derive_key("password", b"short")

    def test_wrap_key_empty_recipients(self):
        with pytest.raises(ValueError):
            wrap_key_for_recipients(generate_aes_key(), {})

    def test_wrap_key_wrong_size(self, rsa_keypair):
        _, pub = rsa_keypair
        with pytest.raises(ValueError):
            wrap_key_for_recipients(b"short", {"a": pub})