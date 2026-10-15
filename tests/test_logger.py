"""Тесты для src/utils/logger.py."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.logger import setup_logging


class TestLogger:
    def test_setup_logging_runs(self):
        """Не падает при обычном вызове."""
        setup_logging("DEBUG")

    def test_setup_logging_twice(self):
        """Повторный вызов не падает (logger.remove() внутри)."""
        setup_logging("INFO")
        setup_logging("DEBUG")

    def test_setup_logging_no_stderr(self):
        """PyInstaller --noconsole: sys.stderr is None — не падаем."""
        with patch.object(sys, "stderr", None):
            setup_logging("DEBUG")

    def test_setup_logging_creates_log_file(self, tmp_path, monkeypatch):
        from loguru import logger

        fake_app_dir = tmp_path / "app"
        fake_app_dir.mkdir()

        monkeypatch.setattr(
            "src.utils.logger.get_app_dir",
            lambda: fake_app_dir,
        )

        setup_logging("INFO")
        logger.info("test message")
        logger.complete()  # дождаться, пока enqueue-поток всё запишет

        assert (fake_app_dir / "logs").exists()
        assert (fake_app_dir / "logs" / "pygram.log").exists()