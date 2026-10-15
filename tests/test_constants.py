"""Тесты для src/constants.py."""

from pathlib import Path
from unittest.mock import patch

import sys

from src.constants import get_app_dir


class TestGetAppDir:
    def test_normal_mode(self):
        """Не frozen: возвращает корень проекта."""
        with patch.object(sys, "frozen", False, create=True):
            d = get_app_dir()
            assert isinstance(d, Path)
            # src/constants.py → src → корень
            assert (d / "config.py").exists() or (d / "src").exists()

    def test_frozen_mode(self, tmp_path):
        """frozen: возвращает папку рядом с .exe."""
        fake_exe = tmp_path / "pygram.exe"
        fake_exe.touch()
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", str(fake_exe)):
            d = get_app_dir()
            assert d == tmp_path