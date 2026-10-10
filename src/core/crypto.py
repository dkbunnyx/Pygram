"""Криптография Pygram: AES-256-GCM, RSA-3072, Argon2id, HKDF.

Все функции работают с bytes. Для сериализации — base64/hex.
"""

import base64
import hashlib
import secrets
import uuid
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
from Crypto.Hash import SHA256
from Crypto.Signature import pss
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from Crypto.Protocol.KDF import PBKDF2


# ============================================================================
# Утилиты: base64, hex, uuid, случайные строки
# ============================================================================

def to_base64(data: bytes) -> str:
    """Кодирует bytes в base64-строку (ASCII).

    Пример:
        >>> to_base64(b"hello")
        'aGVsbG8='
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data должен быть bytes")
    return base64.b64encode(data).decode("ascii")


def from_base64(s: str) -> bytes:
    """Декодирует base64-строку в bytes.

    Пример:
        >>> from_base64("aGVsbG8=")
        b'hello'
    """
    if not isinstance(s, str):
        raise TypeError("s должен быть строкой")
    return base64.b64decode(s, validate=True)


def to_hex(data: bytes) -> str:
    """Кодирует bytes в hex-строку.

    Пример:
        >>> to_hex(b"hi")
        '6869'
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data должен быть bytes")
    return data.hex()


def from_hex(s: str) -> bytes:
    """Декодирует hex-строку в bytes.

    Пример:
        >>> from_hex("6869")
        b'hi'
    """
    if not isinstance(s, str):
        raise TypeError("s должен быть строкой")
    return bytes.fromhex(s)


def generate_uuid() -> str:
    """Генерирует UUID4 в виде строки.

    Пример:
        >>> generate_uuid()
        '7f3a2b1c-4d5e-6f7a-8b9c-0d1e2f3a4b5c'
    """
    return str(uuid.uuid4())


def generate_random_string(length: int = 32) -> str:
    """Генерирует криптостойкую случайную hex-строку.

    Args:
        length: Количество hex-символов (длина итоговой строки).

    Returns:
        Строка из `length` hex-символов.

    Raises:
        ValueError: если length < 1 или нечётный.
    """
    if length < 1:
        raise ValueError("length должен быть >= 1")
    if length % 2 != 0:
        raise ValueError("length должен быть чётным (hex = 2 символа на байт)")
    return secrets.token_hex(length // 2)

# ============================================================================
# AES-256-GCM (симметричное шифрование)
# ============================================================================

AES_KEY_SIZE = 32     # 256 бит
AES_NONCE_SIZE = 12   # 96 бит (рекомендация NIST для GCM)

# PBKDF2 — производные ключи
PBKDF2_ITERATIONS = 600_000   # рекомендация OWASP для PBKDF2-SHA256
PBKDF2_SALT_SIZE = 16         # 16 байт соли
PBKDF2_KEY_SIZE = 32          # 32 байта = AES-256

def generate_aes_key() -> bytes:
    """Генерирует случайный AES-256 ключ (32 байта)."""
    return get_random_bytes(AES_KEY_SIZE)


def generate_nonce() -> bytes:
    """Генерирует случайный nonce для GCM (12 байт)."""
    return get_random_bytes(AES_NONCE_SIZE)


def aes_encrypt(key: bytes, plaintext: bytes, aad: bytes | None = None) -> tuple[bytes, bytes]:
    """Шифрует данные AES-256-GCM.

    Args:
        key: 32-байтовый ключ.
        plaintext: Данные для шифрования.
        aad: Additional Authenticated Data (не шифруется, но проверяется).

    Returns:
        Кортеж (nonce, ciphertext). ciphertext включает тег (последние 16 байт).

    Raises:
        ValueError: если key неверного размера.
    """
    if not isinstance(key, (bytes, bytearray)):
        raise TypeError("key должен быть bytes")
    if len(key) != AES_KEY_SIZE:
        raise ValueError(f"key должен быть {AES_KEY_SIZE} байт, получено {len(key)}")
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError("plaintext должен быть bytes")

    nonce = generate_nonce()
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)

    if aad is not None:
        cipher.update(aad)

    ciphertext, tag = cipher.encrypt_and_digest(plaintext)

    # Склеиваем ciphertext + tag (16 байт) в один blob
    return nonce, ciphertext + tag


def aes_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes | None = None) -> bytes:
    """Расшифровывает данные AES-256-GCM.

    Args:
        key: 32-байтовый ключ.
        nonce: 12-байтовый nonce (тот же, что при шифровании).
        ciphertext: Зашифрованные данные + тег.
        aad: Те же AAD, что при шифровании.

    Returns:
        Расшифрованные данные.

    Raises:
        ValueError: если ключ/nonce неверного размера или тег не совпал.
    """
    if not isinstance(key, (bytes, bytearray)):
        raise TypeError("key должен быть bytes")
    if len(key) != AES_KEY_SIZE:
        raise ValueError(f"key должен быть {AES_KEY_SIZE} байт, получено {len(key)}")
    if not isinstance(nonce, (bytes, bytearray)):
        raise TypeError("nonce должен быть bytes")
    if len(nonce) != AES_NONCE_SIZE:
        raise ValueError(f"nonce должен быть {AES_NONCE_SIZE} байт, получено {len(nonce)}")
    if not isinstance(ciphertext, (bytes, bytearray)):
        raise TypeError("ciphertext должен быть bytes")
    if len(ciphertext) < 16:
        raise ValueError("ciphertext слишком короткий (нет тега)")

    tag = ciphertext[-16:]
    actual_ciphertext = ciphertext[:-16]

    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)

    if aad is not None:
        cipher.update(aad)

    try:
        plaintext = cipher.decrypt_and_verify(actual_ciphertext, tag)
    except ValueError as e:
        raise ValueError(
            "Не удалось расшифровать: тег не совпал (данные повреждены или подменены)"
        ) from e

    return plaintext

# ============================================================================
# RSA-3072 (асимметричное шифрование)
# ============================================================================

RSA_KEY_SIZE = 3072   # бит


def generate_rsa_keypair() -> tuple[str, str]:
    """Генерирует пару RSA-3072 ключей.

    Returns:
        Кортеж (private_pem, public_pem) — обе строки в PEM-формате.

    Note:
        Генерация RSA-3072 занимает ~1 секунду.
    """
    key = RSA.generate(RSA_KEY_SIZE)
    private_pem = key.export_key().decode("ascii")
    public_pem = key.publickey().export_key().decode("ascii")
    return private_pem, public_pem


def load_private_key(pem: str) -> RSA.RsaKey:
    """Загружает приватный RSA-ключ из PEM-строки.

    Raises:
        ValueError: если PEM некорректен.
    """
    if not isinstance(pem, str):
        raise TypeError("pem должен быть строкой")
    try:
        return RSA.import_key(pem)
    except (ValueError, IndexError) as e:
        raise ValueError("Не удалось загрузить приватный ключ: некорректный PEM") from e


def load_public_key(pem: str) -> RSA.RsaKey:
    """Загружает публичный RSA-ключ из PEM-строки.

    Raises:
        ValueError: если PEM некорректен.
    """
    if not isinstance(pem, str):
        raise TypeError("pem должен быть строкой")
    try:
        key = RSA.import_key(pem)
        # Если случайно передали приватный — вернём публичную часть
        return key.publickey() if key.has_private() else key
    except (ValueError, IndexError) as e:
        raise ValueError("Не удалось загрузить публичный ключ: некорректный PEM") from e


def fingerprint(pub_pem: str) -> str:
    """Возвращает SHA-256 отпечаток публичного ключа в hex.

    Используется для идентификации получателя в wrapped_keys.

    Args:
        pub_pem: Публичный ключ в PEM-формате.

    Returns:
        Hex-строка (64 символа) — SHA-256 отпечаток.

    Пример:
        >>> fp = fingerprint(pub_pem)
        >>> len(fp)
        64
    """
    if not isinstance(pub_pem, str):
        raise TypeError("pub_pem должен быть строкой")

    # Нормализуем PEM: убираем пробелы, приводим к каноническому виду
    key = load_public_key(pub_pem)
    canonical_pem = key.export_key().decode("ascii")

    digest = hashlib.sha256(canonical_pem.encode("ascii")).digest()
    return to_hex(digest)

# ============================================================================
# RSA-OAEP (шифрование ключей)
# ============================================================================

RSA_OAEP_MAX_PLAINTEXT = 318  # 3072/8 - 2*32 - 2 = 384 - 66 = 318


def rsa_encrypt(pub_pem: str, data: bytes) -> bytes:
    """Шифрует короткие данные публичным RSA-ключом (OAEP-SHA256).

    Подходит для шифрования AES-ключей (32 байта).
    НЕ подходит для больших данных.

    Args:
        pub_pem: Публичный ключ в PEM.
        data: Данные для шифрования (не больше ~318 байт).

    Returns:
        Зашифрованные байты.

    Raises:
        ValueError: если данные слишком большие или ключ невалиден.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data должен быть bytes")
    if len(data) > RSA_OAEP_MAX_PLAINTEXT:
        raise ValueError(
            f"data слишком большие для RSA-OAEP: {len(data)} байт, "
            f"максимум {RSA_OAEP_MAX_PLAINTEXT}"
        )

    pub_key = load_public_key(pub_pem)
    cipher = PKCS1_OAEP.new(pub_key, hashAlgo=SHA256)

    try:
        return cipher.encrypt(data)
    except ValueError as e:
        raise ValueError(f"RSA-OAEP шифрование не удалось: {e}") from e


def rsa_decrypt(priv_pem: str, ciphertext: bytes) -> bytes:
    """Расшифровывает данные приватным RSA-ключом (OAEP-SHA256).

    Args:
        priv_pem: Приватный ключ в PEM.
        ciphertext: Зашифрованные байты.

    Returns:
        Расшифрованные данные.

    Raises:
        ValueError: если ключ/данные невалидны или не подходят.
    """
    if not isinstance(ciphertext, (bytes, bytearray)):
        raise TypeError("ciphertext должен быть bytes")

    priv_key = load_private_key(priv_pem)
    cipher = PKCS1_OAEP.new(priv_key, hashAlgo=SHA256)

    try:
        return cipher.decrypt(ciphertext)
    except ValueError as e:
        raise ValueError("RSA-OAEP расшифровка не удалась: неверный ключ или повреждены данные") from e

# ============================================================================
# RSA-PSS (цифровые подписи)
# ============================================================================

def rsa_sign(priv_pem: str, data: bytes) -> bytes:
    """Подписывает данные приватным RSA-ключом (PSS-SHA256).

    Args:
        priv_pem: Приватный ключ в PEM.
        data: Данные для подписи.

    Returns:
        Подпись (байты, размер = размер ключа = 384 байта).

    Raises:
        ValueError: если ключ невалиден.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data должен быть bytes")

    priv_key = load_private_key(priv_pem)
    h = SHA256.new(data)
    signature = pss.new(priv_key, salt_bytes=32).sign(h)
    return signature


def rsa_verify(pub_pem: str, data: bytes, signature: bytes) -> bool:
    """Проверяет подпись публичным RSA-ключом (PSS-SHA256).

    Args:
        pub_pem: Публичный ключ в PEM.
        data: Данные, которые были подписаны.
        signature: Подпись для проверки.

    Returns:
        True, если подпись валидна. False — если нет.

    Note:
        НЕ бросает ValueError при невалидной подписи — возвращает False.
        Это удобно для проверки «своё/чужое».
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data должен быть bytes")
    if not isinstance(signature, (bytes, bytearray)):
        raise TypeError("signature должен быть bytes")

    pub_key = load_public_key(pub_pem)
    h = SHA256.new(data)

    try:
        pss.new(pub_key, salt_bytes=32).verify(h, signature)
        return True
    except (ValueError, TypeError):
        return False

# ============================================================================
# Argon2id (хеширование паролей)
# ============================================================================

# Параметры из рекомендаций OWASP
_ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,   # 64 МБ
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Хеширует пароль через Argon2id.

    Args:
        password: Пароль в открытом виде.

    Returns:
        Строка-хеш формата $argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>.

    Raises:
        TypeError: если пароль не строка.
        ValueError: если пароль пустой.
    """
    if not isinstance(password, str):
        raise TypeError("password должен быть строкой")
    if not password:
        raise ValueError("Пароль не может быть пустым")
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Проверяет пароль против хеша (timing-safe).

    Args:
        password: Пароль в открытом виде.
        password_hash: Хеш из hash_password.

    Returns:
        True, если пароль подходит. False — если нет.

    Note:
        НЕ бросает исключение при неверном пароле — возвращает False.
        Бросает только при некорректном формате хеша.
    """
    if not isinstance(password, str):
        raise TypeError("password должен быть строкой")
    if not isinstance(password_hash, str):
        raise TypeError("password_hash должен быть строкой")

    try:
        _ph.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False
    except (VerificationError, InvalidHashError) as e:
        raise ValueError(f"Некорректный формат хеша: {e}") from e


def needs_rehash(password_hash: str) -> bool:
    """Проверяет, нужно ли перехешировать пароль (изменились параметры).

    Returns:
        True, если параметры хеша устарели.
    """
    try:
        return _ph.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True

# ============================================================================
# PBKDF2 (производные ключи)
# ============================================================================

def generate_salt(size: int = PBKDF2_SALT_SIZE) -> bytes:
    """Генерирует случайную соль.

    Args:
        size: Размер соли в байтах.

    Returns:
        Случайные байты.
    """
    if size < 8:
        raise ValueError("Соль должна быть не короче 8 байт")
    return get_random_bytes(size)


def derive_key(password: str, salt: bytes) -> bytes:
    """Выводит 32-байтовый ключ из пароля через PBKDF2-HMAC-SHA256.

    Используется для шифрования identity-файла (.identity_<login>.enc).

    Args:
        password: Пароль пользователя.
        salt: Соль (16 байт, хранится рядом с зашифрованными данными).

    Returns:
        32-байтовый ключ для AES-256.

    Raises:
        TypeError: если типы неверные.
        ValueError: если пароль пустой или соль слишком короткая.
    """
    if not isinstance(password, str):
        raise TypeError("password должен быть строкой")
    if not isinstance(salt, (bytes, bytearray)):
        raise TypeError("salt должен быть bytes")
    if not password:
        raise ValueError("Пароль не может быть пустым")
    if len(salt) < 8:
        raise ValueError("Соль должна быть не короче 8 байт")

    key = PBKDF2(
        password,
        salt,
        dkLen=PBKDF2_KEY_SIZE,
        count=PBKDF2_ITERATIONS,
        hmac_hash_module=SHA256,
    )
    return key

# ============================================================================
# Гибридное шифрование (AES + RSA)
# ============================================================================

def wrap_key_for_recipients(aes_key: bytes, recipients: dict[str, str]) -> dict[str, str]:
    """Заворачивает AES-ключ для каждого получателя (RSA-OAEP).

    Args:
        aes_key: 32-байтовый AES-ключ.
        recipients: Словарь {login: pub_pem} — кому заворачивать.

    Returns:
        Словарь {fingerprint: base64(wrapped_key)}.

    Raises:
        ValueError: если aes_key не 32 байта или recipients пуст.
    """
    if not isinstance(aes_key, (bytes, bytearray)):
        raise TypeError("aes_key должен быть bytes")
    if len(aes_key) != AES_KEY_SIZE:
        raise ValueError(f"aes_key должен быть {AES_KEY_SIZE} байт")
    if not recipients:
        raise ValueError("recipients не может быть пустым")

    wrapped: dict[str, str] = {}
    for login, pub_pem in recipients.items():
        fp = fingerprint(pub_pem)
        wrapped_bytes = rsa_encrypt(pub_pem, aes_key)
        wrapped[fp] = to_base64(wrapped_bytes)
    return wrapped


def unwrap_key(
    wrapped_keys: dict[str, str],
    my_fingerprint: str,
    priv_pem: str,
) -> bytes:
    """Разворачивает свой AES-ключ из wrapped_keys.

    Args:
        wrapped_keys: Словарь {fingerprint: base64(wrapped)}.
        my_fingerprint: Мой fingerprint (ищем свою обёртку).
        priv_pem: Мой приватный RSA-ключ.

    Returns:
        32-байтовый AES-ключ.

    Raises:
        ValueError: если обёртки для меня нет или расшифровка не удалась.
    """
    if my_fingerprint not in wrapped_keys:
        raise ValueError(f"Нет обёртки для fingerprint {my_fingerprint[:16]}...")

    wrapped_b64 = wrapped_keys[my_fingerprint]
    wrapped_bytes = from_base64(wrapped_b64)

    aes_key = rsa_decrypt(priv_pem, wrapped_bytes)
    if len(aes_key) != AES_KEY_SIZE:
        raise ValueError(f"Развёрнутый ключ неверного размера: {len(aes_key)}")

    return aes_key


def hybrid_encrypt(
    plaintext: bytes,
    recipients: dict[str, str],
    aad: bytes | None = None,
) -> dict:
    """Полный цикл гибридного шифрования.

    Args:
        plaintext: Данные для шифрования.
        recipients: {login: pub_pem} — кому шифровать.
        aad: Additional Authenticated Data.

    Returns:
        Словарь:
        {
            "nonce": base64,
            "ciphertext": base64,
            "wrapped_keys": {fp: base64},
        }
    """
    aes_key = generate_aes_key()
    nonce, ciphertext = aes_encrypt(aes_key, plaintext, aad)
    wrapped = wrap_key_for_recipients(aes_key, recipients)

    return {
        "nonce": to_base64(nonce),
        "ciphertext": to_base64(ciphertext),
        "wrapped_keys": wrapped,
    }


def hybrid_decrypt(
    package: dict,
    my_fingerprint: str,
    priv_pem: str,
    aad: bytes | None = None,
) -> bytes:
    """Полный цикл расшифровки гибридного пакета.

    Args:
        package: Словарь из hybrid_encrypt.
        my_fingerprint: Мой fingerprint.
        priv_pem: Мой приватный RSA-ключ.
        aad: Те же AAD, что при шифровании.

    Returns:
        Расшифрованные данные.
    """
    nonce = from_base64(package["nonce"])
    ciphertext = from_base64(package["ciphertext"])
    wrapped_keys = package["wrapped_keys"]

    aes_key = unwrap_key(wrapped_keys, my_fingerprint, priv_pem)
    plaintext = aes_decrypt(aes_key, nonce, ciphertext, aad)
    return plaintext
