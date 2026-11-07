"""Тесты доверия и подписей административных записей."""

import json

import pytest

import src.core.admin as admin_module
from src.core.admin import (_validate_entry, admins_path,
                            can_delete_others_messages,
                            can_grant_delete_rights, can_manage_admins,
                            can_read_all_chats, delete_rights_path,
                            has_any_admin, is_admin, is_super, load_admins,
                            load_admins_verified, make_admin, remove_admin,
                            toggle_delete_others_rights,
                            toggle_grant_delete_rights, toggle_manage_rights,
                            toggle_read_rights, verify_signature)
from src.core.crypto import (fingerprint, generate_rsa_keypair, rsa_sign,
                             to_base64)
from src.core.trust import (TrustError, _read_pin, _write_pin,
                            admin_signature_payload, ensure_trusted_root,
                            pin_initial_root, require_trusted_root, trust_path)
from src.storage.shared_store import ensure_shared_structure, save_pub_key


@pytest.mark.parametrize(
    "data",
    [
        {"fp16": "a" * 16, "fingerprint": "a" * 64},
        {"version": 2, "fp16": "a" * 16, "fingerprint": "a" * 64},
        {"version": 1, "fp16": "b" * 16, "fingerprint": "a" * 64},
        {"version": 1, "fp16": "z" * 16, "fingerprint": "a" * 64},
        {"version": 1, "fp16": "a" * 16, "fingerprint": "z" * 64},
    ],
)
def test_read_pin_rejects_invalid_format(local_dir, data):
    trust_path().write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(TrustError):
        _read_pin()


@pytest.mark.parametrize(
    ("fp16", "full_fingerprint"),
    [
        ("z" * 16, "a" * 64),
        ("a" * 16, "invalid"),
        ("a" * 16, "z" * 64),
        ("b" * 16, "a" * 64),
        ("", "a" * 64),
        ("a" * 16, ""),
    ],
)
def test_write_pin_rejects_invalid_fingerprints(local_dir, fp16, full_fingerprint):
    with pytest.raises(TrustError):
        _write_pin(fp16, full_fingerprint)

    assert not trust_path().exists()


@pytest.fixture
def shared(tmp_path):
    path = tmp_path / "share"
    path.mkdir()
    ensure_shared_structure(path)
    return path


@pytest.fixture
def local_dir(tmp_path, monkeypatch):
    path = tmp_path / "local"
    path.mkdir()
    monkeypatch.setattr("src.core.trust.get_local_dir", lambda: path)
    return path


def _bootstrap(shared, priv=None, pub=None):
    if priv is None or pub is None:
        priv, pub = generate_rsa_keypair()
    fp16 = fingerprint(pub)[:16]
    save_pub_key(shared, fp16, pub)
    make_admin(shared, fp16, by=fp16, by_priv=priv, bootstrap=True)
    pin_initial_root(shared, fp16)
    return fp16, priv, pub


def _add_admin(shared, root_fp, root_priv, new_fp, new_pub):
    save_pub_key(shared, new_fp, new_pub)
    make_admin(shared, new_fp, by=root_fp, by_priv=root_priv)


def test_empty_admin_list(shared, local_dir):
    assert load_admins(shared) == []
    assert has_any_admin(shared) is False


def test_first_admin_is_self_signed_and_pinned(shared, local_dir):
    root_fp, _, _ = _bootstrap(shared)
    entries = load_admins(shared)
    assert len(entries) == 1
    assert entries[0]["fp16"] == root_fp
    assert entries[0]["added_by"] == root_fp
    assert entries[0]["is_super"] is True
    assert verify_signature(entries[0], load_pub(shared, root_fp))
    assert require_trusted_root(shared)["fp16"] == root_fp
    assert is_admin(shared, root_fp)
    assert is_super(shared, root_fp)


def load_pub(shared, fp16):
    return (shared / ".keys" / f"{fp16}.pub.pem").read_text(encoding="ascii")


def test_system_bootstrap_is_forbidden(shared, local_dir):
    with pytest.raises(ValueError, match="by='system'"):
        make_admin(shared, "a" * 16, by="system")


def test_second_admin_signature_and_privileges(shared, local_dir):
    root_fp, root_priv, _ = _bootstrap(shared)
    new_priv, new_pub = generate_rsa_keypair()
    new_fp = fingerprint(new_pub)[:16]
    _add_admin(shared, root_fp, root_priv, new_fp, new_pub)

    entries = load_admins_verified(shared)
    assert len(entries) == 2
    assert entries[1]["fp16"] == new_fp
    assert entries[1]["is_super"] is False
    assert not can_read_all_chats(shared, new_fp)
    assert not can_manage_admins(shared, new_fp)


def test_privilege_tampering_invalidates_signature(shared, local_dir):
    root_fp, root_priv, _ = _bootstrap(shared)
    new_priv, new_pub = generate_rsa_keypair()
    new_fp = fingerprint(new_pub)[:16]
    _add_admin(shared, root_fp, root_priv, new_fp, new_pub)

    data = json.loads((shared / ".admins" / "list.json").read_text(encoding="utf-8"))
    data["admins"][1]["can_read_all_chats"] = True
    (shared / ".admins" / "list.json").write_text(json.dumps(data), encoding="utf-8")

    assert all(entry["fp16"] != new_fp for entry in load_admins_verified(shared))
    assert not can_read_all_chats(shared, new_fp)


def test_root_privilege_tampering_blocks_everything(shared, local_dir):
    root_fp, _, _ = _bootstrap(shared)
    path = shared / ".admins" / "list.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["admins"][0]["can_manage_admins"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TrustError):
        load_admins_verified(shared)


def test_toggle_rights_resigns_entry(shared, local_dir):
    root_fp, root_priv, _ = _bootstrap(shared)
    new_priv, new_pub = generate_rsa_keypair()
    new_fp = fingerprint(new_pub)[:16]
    _add_admin(shared, root_fp, root_priv, new_fp, new_pub)

    toggle_read_rights(shared, new_fp, by=root_fp, by_priv=root_priv)
    assert can_read_all_chats(shared, new_fp)
    toggle_manage_rights(shared, new_fp, by=root_fp, by_priv=root_priv)
    assert can_manage_admins(shared, new_fp)


def test_only_super_can_change_rights(shared, local_dir):
    root_fp, root_priv, _ = _bootstrap(shared)
    new_priv, new_pub = generate_rsa_keypair()
    new_fp = fingerprint(new_pub)[:16]
    _add_admin(shared, root_fp, root_priv, new_fp, new_pub)
    with pytest.raises(ValueError, match="Только супер-админ"):
        toggle_read_rights(shared, new_fp, by=new_fp, by_priv=new_priv)


def test_remove_admin_requires_valid_admin_key(shared, local_dir):
    root_fp, root_priv, _ = _bootstrap(shared)
    new_priv, new_pub = generate_rsa_keypair()
    new_fp = fingerprint(new_pub)[:16]
    _add_admin(shared, root_fp, root_priv, new_fp, new_pub)
    remove_admin(shared, new_fp, by=root_fp, by_priv=root_priv)
    assert not is_admin(shared, new_fp)


def test_entry_signed_by_unknown_key_is_rejected(shared, local_dir):
    _bootstrap(shared)
    attacker_priv, attacker_pub = generate_rsa_keypair()
    attacker_fp = fingerprint(attacker_pub)[:16]
    save_pub_key(shared, attacker_fp, attacker_pub)

    forged = {
        "fp16": "b" * 16,
        "added_at": 123456789,
        "added_by": attacker_fp,
        "is_super": False,
        "can_manage_admins": True,
        "can_read_all_chats": True,
        "can_grant_delete_rights": False,
    }
    forged["signature"] = to_base64(
        rsa_sign(attacker_priv, admin_signature_payload(forged))
    )
    path = shared / ".admins" / "list.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["admins"].append(forged)
    path.write_text(json.dumps(data), encoding="utf-8")

    assert all(entry["fp16"] != "b" * 16 for entry in load_admins_verified(shared))


def test_new_computer_requires_manual_confirmation(shared, tmp_path, monkeypatch):
    root_fp, _, _ = _bootstrap(shared)
    local_two = tmp_path / "computer_two"
    local_two.mkdir()
    monkeypatch.setattr("src.core.trust.get_local_dir", lambda: local_two)

    seen = []
    root = ensure_trusted_root(shared, lambda value: seen.append(value) or True)
    assert root["fp16"] == root_fp
    assert seen == [root["fingerprint"]]
    assert trust_path().is_file()


def test_manual_rejection_does_not_pin(shared, tmp_path, monkeypatch):
    _bootstrap(shared)
    local_two = tmp_path / "computer_two"
    local_two.mkdir()
    monkeypatch.setattr("src.core.trust.get_local_dir", lambda: local_two)

    with pytest.raises(TrustError, match="не подтверждён"):
        ensure_trusted_root(shared, lambda _: False)
    assert not trust_path().exists()


def test_changed_root_key_is_detected(shared, local_dir):
    root_fp, _, _ = _bootstrap(shared)
    _, replacement_pub = generate_rsa_keypair()

    # Имитируем подмену файла извне, минуя защищённую save_pub_key().
    path = shared / ".keys" / f"{root_fp}.pub.pem"
    path.write_text(replacement_pub, encoding="ascii")

    with pytest.raises(TrustError):
        require_trusted_root(shared)


def test_missing_root_after_pin_is_detected(shared, local_dir):
    root_fp, _, _ = _bootstrap(shared)
    (shared / ".admins" / "list.json").write_text('{"admins": []}', encoding="utf-8")
    with pytest.raises(TrustError):
        require_trusted_root(shared)


def test_corrupted_trusted_root_json_is_rejected(shared, local_dir):
    _bootstrap(shared)

    trust_file = trust_path()
    trust_file.write_text("{invalid json", encoding="utf-8")

    with pytest.raises(TrustError):
        require_trusted_root(shared)


@pytest.mark.parametrize(
    "data",
    [
        {"version": 1, "fp16": "z" * 16, "fingerprint": "a" * 64},
        {"version": 1, "fp16": "a" * 16, "fingerprint": "invalid"},
        {"version": 1, "fp16": "a" * 16, "fingerprint": "z" * 64},
    ],
)
def test_invalid_trusted_root_data_is_rejected(shared, local_dir, data):
    _bootstrap(shared)

    trust_path().write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    with pytest.raises(TrustError):
        require_trusted_root(shared)


@pytest.mark.parametrize(
    "data",
    [
        # Отсутствует версия формата.
        {
            "fp16": "a" * 16,
            "fingerprint": "a" * 64,
        },
        # Неподдерживаемая версия.
        {
            "version": 2,
            "fp16": "a" * 16,
            "fingerprint": "a" * 64,
        },
        # Первые 16 символов не совпадают.
        {
            "version": 1,
            "fp16": "b" * 16,
            "fingerprint": "a" * 64,
        },
        # Недопустимые символы в fp16.
        {
            "version": 1,
            "fp16": "z" * 16,
            "fingerprint": "a" * 64,
        },
        # Недопустимые символы в полном fingerprint.
        {
            "version": 1,
            "fp16": "a" * 16,
            "fingerprint": "z" * 64,
        },
    ],
)
def test_invalid_trusted_root_format_is_rejected(shared, local_dir, data):
    _bootstrap(shared)

    trust_path().write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    with pytest.raises(TrustError):
        require_trusted_root(shared)


def test_change_right_rejects_unverified_admin(shared, local_dir):
    root_fp, root_priv, _ = _bootstrap(shared)

    admin_priv, admin_pub = generate_rsa_keypair()
    admin_fp = fingerprint(admin_pub)[:16]
    _add_admin(shared, root_fp, root_priv, admin_fp, admin_pub)

    # Намеренно портим подпись администратора.
    path = admins_path(shared)
    data = json.loads(path.read_text(encoding="utf-8"))

    target = next(a for a in data["admins"] if a["fp16"] == admin_fp)
    target["signature"] = "invalid-signature"

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )

    # Недоверенную запись нельзя исправить изменением её прав.
    with pytest.raises(ValueError, match="не является проверенным администратором"):
        toggle_manage_rights(shared, admin_fp, root_fp, root_priv)

    # Запись должна остаться нетронутой.
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved_target = next(a for a in saved["admins"] if a["fp16"] == admin_fp)

    assert saved_target["signature"] == "invalid-signature"


def test_remove_admin_rejects_changed_record(shared, local_dir, monkeypatch):
    import src.core.admin as admin_module

    root_fp, root_priv, _ = _bootstrap(shared)

    admin_priv, admin_pub = generate_rsa_keypair()
    admin_fp = fingerprint(admin_pub)[:16]
    _add_admin(shared, root_fp, root_priv, admin_fp, admin_pub)

    original_load_list = admin_module._load_list
    calls = 0

    def tamper_on_second_read(folder):
        nonlocal calls
        calls += 1

        if calls == 2:
            path = admins_path(shared)
            data = json.loads(path.read_text(encoding="utf-8"))

            target = next(a for a in data["admins"] if a["fp16"] == admin_fp)
            target["signature"] = "tampered-signature"

            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )

        return original_load_list(folder)

    monkeypatch.setattr(
        admin_module,
        "_load_list",
        tamper_on_second_read,
    )

    with pytest.raises(ValueError, match="изменилась"):
        remove_admin(
            shared,
            admin_fp,
            by=root_fp,
            by_priv=root_priv,
        )

    saved = json.loads(admins_path(shared).read_text(encoding="utf-8"))
    saved_target = next(a for a in saved["admins"] if a["fp16"] == admin_fp)

    assert saved_target["signature"] == "tampered-signature"


@pytest.mark.parametrize(
    "field,value",
    [
        ("fp16", "z" * 16),
        ("fp16", "a" * 15),
        ("added_by", "z" * 16),
        ("added_at", True),
        ("added_at", -1),
    ],
)
def test_validate_entry_rejects_invalid_fields(field, value):
    entry = {
        "fp16": "a" * 16,
        "added_at": 123456789,
        "added_by": "b" * 16,
        "is_super": False,
        "can_manage_admins": False,
        "can_read_all_chats": False,
        "can_grant_delete_rights": False,
        field: value,
    }

    assert not _validate_entry(entry)


def test_validate_entry_accepts_valid_entry():
    entry = {
        "fp16": "a" * 16,
        "added_at": 123456789,
        "added_by": "b" * 16,
        "is_super": False,
        "can_manage_admins": False,
        "can_read_all_chats": False,
        "can_grant_delete_rights": False,
    }

    assert _validate_entry(entry)


def test_write_pin_saves_valid_fingerprints(local_dir):
    full_fingerprint = "a" * 64
    fp16 = full_fingerprint[:16]

    _write_pin(fp16, full_fingerprint)

    data = json.loads(trust_path().read_text(encoding="utf-8"))

    assert data == {
        "version": 1,
        "fp16": fp16,
        "fingerprint": full_fingerprint,
    }


def test_admin_list_rejects_more_than_100_entries(shared, local_dir):
    _bootstrap(shared)

    path = shared / ".admins" / "list.json"
    path.write_text(
        json.dumps({"admins": [{}] * 101}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="превышен лимит"):
        load_admins(shared)


def test_save_admin_list_rejects_more_than_100_entries(shared, local_dir):
    _bootstrap(shared)

    data = {"admins": [{}] * 101}

    with pytest.raises(ValueError, match="больше 100"):
        admin_module._save_list(shared, data)


def test_admin_list_accepts_file_at_size_limit(shared, local_dir):
    _bootstrap(shared)

    path = shared / ".admins" / "list.json"
    valid_json = b'{"admins": []}'
    path.write_bytes(
        valid_json + b" " * (admin_module.MAX_ADMINS_FILE_SIZE - len(valid_json))
    )

    assert load_admins(shared) == []


def test_admin_list_rejects_file_over_size_limit(shared, local_dir):
    _bootstrap(shared)

    path = shared / ".admins" / "list.json"
    path.write_bytes(b" " * (admin_module.MAX_ADMINS_FILE_SIZE + 1))

    with pytest.raises(ValueError, match="превышает допустимый размер"):
        load_admins(shared)


def test_superadmin_can_grant_and_revoke_delete_rights(shared, local_dir):
    root_fp, root_priv, _ = _bootstrap(shared)

    _, user_pub = generate_rsa_keypair()
    user_fp = fingerprint(user_pub)[:16]
    save_pub_key(shared, user_fp, user_pub)

    assert can_delete_others_messages(shared, user_fp) is False

    assert toggle_delete_others_rights(shared, user_fp, root_fp, root_priv) is True

    assert can_delete_others_messages(shared, user_fp) is True

    assert toggle_delete_others_rights(shared, user_fp, root_fp, root_priv) is False

    assert can_delete_others_messages(shared, user_fp) is False


def test_admin_with_grant_permission_can_manage_user_rights(shared, local_dir):
    root_fp, root_priv, _ = _bootstrap(shared)

    admin_priv, admin_pub = generate_rsa_keypair()
    admin_fp = fingerprint(admin_pub)[:16]
    _add_admin(shared, root_fp, root_priv, admin_fp, admin_pub)

    toggle_grant_delete_rights(shared, admin_fp, root_fp, root_priv)

    assert can_grant_delete_rights(shared, admin_fp) is True

    _, user_pub = generate_rsa_keypair()
    user_fp = fingerprint(user_pub)[:16]
    save_pub_key(shared, user_fp, user_pub)

    assert toggle_delete_others_rights(shared, user_fp, admin_fp, admin_priv) is True

    assert can_delete_others_messages(shared, user_fp) is True


def test_admin_without_grant_permission_cannot_manage_user_rights(shared, local_dir):
    root_fp, root_priv, _ = _bootstrap(shared)

    admin_priv, admin_pub = generate_rsa_keypair()
    admin_fp = fingerprint(admin_pub)[:16]
    _add_admin(shared, root_fp, root_priv, admin_fp, admin_pub)

    _, user_pub = generate_rsa_keypair()
    user_fp = fingerprint(user_pub)[:16]
    save_pub_key(shared, user_fp, user_pub)

    assert can_grant_delete_rights(shared, admin_fp) is False

    with pytest.raises(ValueError, match="Недостаточно прав"):
        toggle_delete_others_rights(shared, user_fp, admin_fp, admin_priv)


def test_superadmin_can_grant_and_revoke_admin_grant_right(shared, local_dir):
    root_fp, root_priv, _ = _bootstrap(shared)

    admin_priv, admin_pub = generate_rsa_keypair()
    admin_fp = fingerprint(admin_pub)[:16]
    _add_admin(shared, root_fp, root_priv, admin_fp, admin_pub)

    assert can_grant_delete_rights(shared, admin_fp) is False

    toggle_grant_delete_rights(shared, admin_fp, root_fp, root_priv)

    assert can_grant_delete_rights(shared, admin_fp) is True

    toggle_grant_delete_rights(shared, admin_fp, root_fp, root_priv)

    assert can_grant_delete_rights(shared, admin_fp) is False


def test_admin_cannot_grant_the_grant_permission_to_self(shared, local_dir):
    root_fp, root_priv, _ = _bootstrap(shared)

    admin_priv, admin_pub = generate_rsa_keypair()
    admin_fp = fingerprint(admin_pub)[:16]
    _add_admin(shared, root_fp, root_priv, admin_fp, admin_pub)

    with pytest.raises(ValueError):
        toggle_grant_delete_rights(shared, admin_fp, admin_fp, admin_priv)

    assert can_grant_delete_rights(shared, admin_fp) is False


def test_cannot_grant_user_delete_right_to_admin(shared, local_dir):
    root_fp, root_priv, _ = _bootstrap(shared)

    admin_priv, admin_pub = generate_rsa_keypair()
    admin_fp = fingerprint(admin_pub)[:16]
    _add_admin(shared, root_fp, root_priv, admin_fp, admin_pub)

    with pytest.raises(ValueError):
        toggle_delete_others_rights(shared, admin_fp, root_fp, root_priv)


def test_tampered_delete_right_signature_is_rejected(shared, local_dir):
    root_fp, root_priv, _ = _bootstrap(shared)

    _, user_pub = generate_rsa_keypair()
    user_fp = fingerprint(user_pub)[:16]
    save_pub_key(shared, user_fp, user_pub)

    toggle_delete_others_rights(shared, user_fp, root_fp, root_priv)

    path = delete_rights_path(shared)
    data = json.loads(path.read_text(encoding="utf-8"))

    entry = next(item for item in data["rights"] if item["fp16"] == user_fp)
    entry["granted"] = False

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        can_delete_others_messages(shared, user_fp)
