"""Тесты для src/storage/local_db.py."""

import pytest

from src.storage.local_db import LocalDB


@pytest.fixture
def db(tmp_path):
    """Создаёт временную БД (не трогает реальную)."""
    db_path = tmp_path / "test.db"
    db = LocalDB(db_path)
    yield db
    db.close()


class TestMessages:
    def test_save_and_get(self, db):
        db.save_message("msg1", "chat1", "sender1", "Привет", 1000)
        msgs = db.get_messages("chat1")
        assert len(msgs) == 1
        assert msgs[0]["text"] == "Привет"
        assert msgs[0]["msg_id"] == "msg1"

    def test_multiple(self, db):
        db.save_message("m1", "c1", "s1", "A", 100)
        db.save_message("m2", "c1", "s1", "B", 200)
        db.save_message("m3", "c2", "s1", "C", 300)

        c1_msgs = db.get_messages("c1")
        assert len(c1_msgs) == 2
        assert [m["text"] for m in c1_msgs] == ["A", "B"]

    def test_mark_read(self, db):
        db.save_message("m1", "c1", "s1", "A", 100)
        assert db.get_messages("c1")[0]["is_read"] == 0
        db.mark_read("c1")
        assert db.get_messages("c1")[0]["is_read"] == 1


class TestDrafts:
    def test_save_and_get(self, db):
        db.save_draft("chat1", "Незаконченное сообщение")
        assert db.get_draft("chat1") == "Незаконченное сообщение"

    def test_overwrite(self, db):
        db.save_draft("chat1", "Старый")
        db.save_draft("chat1", "Новый")
        assert db.get_draft("chat1") == "Новый"

    def test_delete_on_empty(self, db):
        db.save_draft("chat1", "Текст")
        db.save_draft("chat1", "")
        assert db.get_draft("chat1") == ""

    def test_empty_default(self, db):
        assert db.get_draft("unknown") == ""


class TestSettings:
    def test_set_get(self, db):
        db.set_setting("theme", "dark")
        assert db.get_setting("theme") == "dark"

    def test_default(self, db):
        assert db.get_setting("unknown", "default_val") == "default_val"

    def test_overwrite(self, db):
        db.set_setting("k", "v1")
        db.set_setting("k", "v2")
        assert db.get_setting("k") == "v2"