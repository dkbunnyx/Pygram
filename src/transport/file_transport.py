"""Файловый транспорт для Pygram (работа с SMB-шарой).

Использует watchdog для отслеживания изменений.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from loguru import logger
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from src.transport.base import Transport
from src.utils.validators import safe_join


class _Handler(FileSystemEventHandler):
    """Внутренний обработчик событий watchdog."""

    def __init__(self, base_dir: Path, callback: Callable[[str], None]):
        self.base_dir = base_dir
        self.callback = callback

    def on_any_event(self, event):
        # Нас интересуют только создание и изменение файлов
        if event.is_directory:
            return
        if event.event_type in ("created", "modified"):
            try:
                rel_path = Path(event.src_path).relative_to(self.base_dir)
                # Игнорируем временные файлы (.tmp)
                if not rel_path.name.endswith(".tmp"):
                    self.callback(str(rel_path).replace("\\", "/"))
            except ValueError:
                pass


class FileTransport(Transport):
    """Транспорт на основе локальной/SMB файловой системы."""

    def __init__(self, root_dir: str | Path):
        self.root = Path(root_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._observer: Observer | None = None

    def _abs(self, rel_path: str) -> Path:
        """Преобразует относительный путь в абсолютный с защитой."""
        return safe_join(self.root, rel_path)

    def put(self, path: str, data: bytes) -> None:
        target = self._abs(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)

    def get(self, path: str) -> bytes:
        return self._abs(path).read_bytes()

    def list(self, path: str) -> list[str]:
        d = self._abs(path)
        if not d.is_dir():
            return []
        # Возвращаем только файлы, без папок
        return [p.name for p in d.iterdir() if p.is_file()]

    def delete(self, path: str) -> None:
        self._abs(path).unlink()

    def exists(self, path: str) -> bool:
        return self._abs(path).is_file()

    def watch(self, path: str, callback: Callable[[str], None]) -> None:
        """Запускает watchdog."""
        watch_dir = self._abs(path)
        watch_dir.mkdir(parents=True, exist_ok=True)

        if self._observer:
            self.stop_watch()

        event_handler = _Handler(self.root, callback)
        self._observer = Observer()
        self._observer.schedule(event_handler, str(watch_dir), recursive=True)
        self._observer.start()
        logger.info(f"Watchdog запущен для: {watch_dir}")

    def stop_watch(self) -> None:
        """Останавливает watchdog."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Watchdog остановлен.")
