from src.core.crypto import fingerprint, generate_rsa_keypair
from src.core.superadmin_recovery import (
    RecoveryError,
    build_recovery_certificate,
    create_recovery_material,
    sign_recovery_descriptor,
    unlock_recovery_private_key,
    verify_recovery_certificate,
    verify_recovery_descriptor,
    verify_recovery_pair,
)


def test_recovery_package_round_trip_and_wrong_password():
    package, recovery_public, _ = create_recovery_material("correct horse battery staple")
    private = unlock_recovery_private_key(package, "correct horse battery staple")
    assert verify_recovery_pair(private, recovery_public)

    try:
        unlock_recovery_private_key(package, "wrong password")
    except RecoveryError:
        pass
    else:
        raise AssertionError("wrong recovery password must fail")


def test_descriptor_requires_current_root_signature():
    root_private, root_public = generate_rsa_keypair()
    _, recovery_public, unsigned = create_recovery_material("correct horse battery staple")
    descriptor = sign_recovery_descriptor(unsigned, root_private)
    verified = verify_recovery_descriptor(descriptor, root_public)
    assert verified["public_fingerprint"] == fingerprint(recovery_public)

    other_private, other_public = generate_rsa_keypair()
    assert other_private != root_private
    try:
        verify_recovery_descriptor(descriptor, other_public)
    except RecoveryError:
        pass
    else:
        raise AssertionError("descriptor must not validate under another root")


def test_recovery_certificate_binds_exact_new_root():
    recovery_private, recovery_public = generate_rsa_keypair()
    new_root_private, new_root_public = generate_rsa_keypair()
    new_fp = fingerprint(new_root_public)
    old_private, old_public = generate_rsa_keypair()
    old_fp = fingerprint(old_public)
    certificate = build_recovery_certificate(
        recovery_private, new_fp[:16], new_fp, old_fp[:16], old_fp
    )
    verified = verify_recovery_certificate(certificate, recovery_public)
    assert verified["new_root_fingerprint"] == new_fp
    assert verified["old_root_fingerprint"] == old_fp

    other_private, other_public = generate_rsa_keypair()
    assert other_private != recovery_private
    try:
        verify_recovery_certificate(certificate, other_public)
    except RecoveryError:
        pass
    else:
        raise AssertionError("certificate must not validate under another recovery key")


def test_recovery_re_roots_admins_without_touching_chat_data(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    import src.core.user as user_module
    from src.core.admin import make_admin, load_admins_verified
    from src.core.crypto import fingerprint
    from src.core.identity import register_identity
    from src.core.superadmin_recovery import (
        recover_superadmin, save_recovery_files,
    )
    from src.core.trust import _write_pin, require_trusted_root
    from src.storage.shared_store import (
        ensure_shared_structure, load_pub_key_by_fp16,
    )
    from tests.conftest import bootstrap_super_admin

    shared = tmp_path / "share"
    ensure_shared_structure(shared)
    root_fp, root_private = bootstrap_super_admin(
        shared, "old-root", "old-root-password"
    )
    root_public = load_pub_key_by_fp16(shared, root_fp)

    package, recovery_public, descriptor_unsigned = create_recovery_material(
        "a sufficiently long recovery phrase"
    )
    descriptor = sign_recovery_descriptor(descriptor_unsigned, root_private)
    save_recovery_files(shared, package, descriptor)
    _write_pin(root_fp, fingerprint(root_public), recovery_public)

    admin_fp = register_identity(shared, "existing-admin", "admin-password")
    make_admin(
        shared, admin_fp, by=root_fp, by_priv=root_private
    )
    # Настраиваем права существующего администратора до восстановления.
    admin_file = shared / ".admins" / "list.json"
    roster = json.loads(admin_file.read_text(encoding="utf-8"))
    admin_entry = next(e for e in roster["admins"] if e["fp16"] == admin_fp)
    admin_entry["can_manage_admins"] = True
    admin_entry["can_read_all_chats"] = True
    from src.core.trust import admin_signature_payload
    from src.core.crypto import rsa_sign, to_base64
    admin_entry["signature"] = to_base64(
        rsa_sign(root_private, admin_signature_payload(admin_entry))
    )
    admin_file.write_text(json.dumps(roster), encoding="utf-8")

    # Эти данные должны остаться побайтно неизменными.
    message_dir = shared / "message" / "existing-chat"
    media_dir = shared / "files" / "existing-chat"
    message_dir.mkdir(parents=True)
    media_dir.mkdir(parents=True)
    (message_dir / "message.bin").write_bytes(b"encrypted-message")
    (media_dir / "photo.bin").write_bytes(b"encrypted-media")

    monkeypatch.setattr(user_module, "login_user", lambda *a, **k: "logged-in-new-root")
    result = recover_superadmin(
        shared,
        "newroot",
        "new-root-password",
        "a sufficiently long recovery phrase",
    )
    assert result == "logged-in-new-root"

    trusted = require_trusted_root(shared)
    assert trusted["fp16"] != root_fp
    verified = load_admins_verified(shared)
    new_root = next(e for e in verified if e["is_super"] is True)
    preserved_admin = next(e for e in verified if e["fp16"] == admin_fp)
    assert new_root["fp16"] == trusted["fp16"]
    assert preserved_admin["can_manage_admins"] is True
    assert preserved_admin["can_read_all_chats"] is True
    assert (message_dir / "message.bin").read_bytes() == b"encrypted-message"
    assert (media_dir / "photo.bin").read_bytes() == b"encrypted-media"

    # Второй компьютер со старым pin должен принять новый root только по
    # recovery-сертификату, без ручного подтверждения нового fingerprint.
    import src.core.trust as trust_module
    second_local = tmp_path / "second-computer"
    second_local.mkdir()
    monkeypatch.setattr(trust_module, "get_local_dir", lambda: second_local)
    _write_pin(root_fp, fingerprint(root_public), recovery_public)
    migrated = trust_module.ensure_trusted_root(shared, lambda _: False)
    assert migrated["fp16"] == trusted["fp16"]
    assert trust_module._read_pin()["recovery_fingerprint"] == fingerprint(recovery_public)


def test_existing_root_can_enroll_recovery_key(tmp_path):
    from tests.conftest import bootstrap_super_admin
    from src.storage.shared_store import ensure_shared_structure

    shared = tmp_path / "share"
    ensure_shared_structure(shared)
    from src.core.superadmin_recovery import (
        load_recovery_descriptor,
        load_recovery_package,
        setup_recovery_for_current_root,
        unlock_recovery_private_key,
        verify_recovery_descriptor,
        verify_recovery_pair,
    )
    from src.core.trust import _read_pin
    from src.storage.shared_store import load_pub_key_by_fp16

    root_fp, root_private = bootstrap_super_admin(
        shared, "existing-root", "existing-root-password"
    )
    setup_recovery_for_current_root(
        shared, root_fp, root_private, "another long recovery passphrase"
    )

    pin = _read_pin()
    assert pin["recovery_public_key"]
    root_public = load_pub_key_by_fp16(shared, root_fp)
    descriptor = verify_recovery_descriptor(
        load_recovery_descriptor(shared), root_public
    )
    assert descriptor["public_fingerprint"] == pin["recovery_fingerprint"]
    private = unlock_recovery_private_key(
        load_recovery_package(shared), "another long recovery passphrase"
    )
    assert verify_recovery_pair(private, pin["recovery_public_key"])
