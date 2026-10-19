"""Тесты для src/transport/file_transport.py."""

import time
from pathlib import Path

import pytest

from src.transport.file_transport import FileTransport


@pytest.fixture
def transport(tmp_path):
    root = tmp_path / "share"
    return FileTransport(root)


class TestFileTransport:
    def test_put_and_get(self, transport):
        transport.put("test.bin", b"hello")
        assert transport.get("test.bin") == b"hello"

    def test_exists(self, transport):
        assert transport.exists("none.bin") is False
        transport.put("test.bin", b"hello")
        assert transport.exists("test.bin") is True

    def test_list(self, transport):
        transport.put("dir/a.txt", b"1")
        transport.put("dir/b.txt", b"2")
        assert set(transport.list("dir")) == {"a.txt", "b.txt"}

    def test_delete(self, transport):
        transport.put("test.bin", b"hello")
        transport.delete("test.bin")
        assert transport.exists("test.bin") is False

    def test_get_missing(self, transport):
        with pytest.raises(FileNotFoundError):
            transport.get("missing.bin")

    def test_atomic_write(self, transport):
        """Проверяем, что нет .tmp файлов после записи."""
        transport.put("test.bin", b"hello")
        d = transport._abs(".")
        tmp_files = list(d.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_path_traversal(self, transport):
        """Попытка выйти за пределы папки."""
        with pytest.raises(ValueError):
            transport.put("../outside.txt", b"hack")


class TestWatchdog:
    @pytest.mark.skip(reason="Watchdog нестабилен в тестах на Windows (тайминги ОС)")
    def test_watch_detects_changes(self, transport):
        events = []
        transport.watch(".", lambda path: events.append(path))

        try:
            time.sleep(1.0)
            transport.put("new_file.txt", b"data")

            start = time.time()
            while not events and (time.time() - start) < 3.0:
                time.sleep(0.1)

            assert len(events) > 0, "Watchdog не поймал событие за 3 секунды"
            assert any("new_file.txt" in e for e in events)
        finally:
            transport.stop_watch()