"""Тесты для src/constants.py."""

import sys
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.constants import APP_NAME, get_app_dir


class TestGetAppDir:
    def test_normal_mode(self):
        """Не frozen: возвращает корень проекта."""
        with patch.object(sys, "frozen", False, create=True):
            d = get_app_dir()
            assert isinstance(d, Path)
            assert (d / "config.py").exists() or (d / "src").exists()

    def test_frozen_mode_appdata(self, tmp_path, monkeypatch):
        """frozen + APPDATA: возвращает %APPDATA%\\Pygram."""
        fake_exe = tmp_path / "pygram.exe"
        fake_exe.touch()
        appdata = tmp_path / "AppData"
        appdata.mkdir()
        monkeypatch.setenv("APPDATA", str(appdata))

        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", str(fake_exe)):
            d = get_app_dir()
            assert d == appdata / APP_NAME
            assert d.is_dir()

    def test_frozen_mode_no_appdata(self, tmp_path, monkeypatch):
        """frozen без APPDATA (Linux/macOS): fallback на ~/.config/Pygram."""
        fake_exe = tmp_path / "pygram.exe"
        fake_exe.touch()

        # Убираем APPDATA, но оставляем HOME, чтобы Path.home() работал
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        with patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "executable", str(fake_exe)):
            d = get_app_dir()
            assert d == tmp_path / ".config" / APP_NAME