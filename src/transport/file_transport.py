
"""Файловый транспорт для Pygram (работа с SMB-шарой).

Использует watchdog для отслеживания изменений и может публиковать
файловые события в Pygram Event Engine.

Один Observer поддерживает несколько наблюдаемых директорий.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from loguru import logger
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.core.event_engine import EventEngine
from src.storage.shared_store import write_bytes_atomic
from src.transport.base import Transport
from src.utils.validators import safe_join


class _Handler(FileSystemEventHandler):
    """Внутренний обработчик событий watchdog."""

    _SUPPORTED_EVENTS = {"created", "modified", "deleted", "moved"}
    _IGNORED_SUFFIXES = (".tmp", ".lock")

    def __init__(
        self,
        base_dir: Path,
        callback: Callable[[str], None] | None = None,
        event_engine: EventEngine | None = None,
    ):
        self.base_dir = base_dir.resolve()
        self.event_engine = event_engine

        # Callback привязывается к директории наблюдения.
        self._callbacks: list[
            tuple[Path, Callable[[str], None]]
        ] = []

        # Обратная совместимость с прямым созданием _Handler.
        if callback is not None:
            self.add_callback(self.base_dir, callback)

    def add_callback(
        self,
        watch_dir: Path,
        callback: Callable[[str], None],
    ) -> None:
        """Регистрирует callback для конкретной директории."""

        watch_dir = watch_dir.resolve()

        registration = (watch_dir, callback)

        if registration not in self._callbacks:
            self._callbacks.append(registration)

    def _relative_path(self, path: str) -> str | None:
        """Возвращает безопасный относительный путь со слешами."""

        try:
            relative = Path(path).resolve().relative_to(self.base_dir)
        except (ValueError, OSError):
            return None

        normalized = relative.as_posix()

        if not normalized or normalized == ".":
            return None

        return normalized

    @classmethod
    def _is_ignored(cls, path: str | None) -> bool:
        """Проверяет, является ли файл временным или служебным."""

        if path is None:
            return True

        name = Path(path).name.lower()
        return name.endswith(cls._IGNORED_SUFFIXES)

    def _publish(self, event_type: str, **payload: str) -> None:
        """Публикует событие через EventEngine."""

        if self.event_engine is None:
            return

        try:
            self.event_engine.publish(event_type, **payload)
        except Exception:
            logger.exception(
                "Не удалось опубликовать событие файлового транспорта"
            )

    def _invoke_callbacks(self, absolute_path: str, relative_path: str) -> None:
        """Вызывает callback для директории, содержащей изменённый файл."""

        try:
            resolved_path = Path(absolute_path).resolve()
        except (OSError, ValueError):
            return

        for watch_dir, callback in tuple(self._callbacks):
            try:
                resolved_path.relative_to(watch_dir)
            except ValueError:
                continue

            try:
                callback(relative_path)
            except Exception:
                logger.exception(
                    "Ошибка legacy callback файлового транспорта"
                )

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or event.event_type not in self._SUPPORTED_EVENTS:
            return

        src_path = self._relative_path(event.src_path)

        if src_path is None:
            return

        # Перемещение обрабатываем отдельно:
        # исходный файл может иметь суффикс .tmp,
        # но конечный файл уже должен быть опубликован.
        if event.event_type == "moved":
            dest_path = self._relative_path(event.dest_path)

            if dest_path is None or self._is_ignored(dest_path):
                return

            self._publish(
                "file.moved",
                path=dest_path,
                src_path=src_path,
                dest_path=dest_path,
            )

            # Callback для moved не вызывается:
            # сохраняем прежний контракт.
            return

        # Для остальных событий временные и служебные файлы игнорируем.
        if self._is_ignored(src_path):
            return

        self._publish(
            f"file.{event.event_type}",
            path=src_path,
        )

        # Обратная совместимость:
        # callback вызывается только для created и modified.
        if event.event_type in ("created", "modified"):
            self._invoke_callbacks(event.src_path, src_path)


class FileTransport(Transport):
    """Транспорт на основе локальной/SMB файловой системы."""

    def __init__(
        self,
        root_dir: str | Path,
        event_engine: EventEngine | None = None,
    ):
        self.root = Path(root_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

        self.event_engine = event_engine

        self._observer: Observer | None = None
        self._handler: _Handler | None = None

        self._watched_dirs: set[Path] = set()
        self._observer_started = False

    def _abs(self, rel_path: str) -> Path:
        """Преобразует относительный путь в абсолютный с защитой."""

        return safe_join(self.root, rel_path)

    def put(self, path: str, data: bytes) -> None:
        target = self._abs(path)
        write_bytes_atomic(target, data)

    def get(self, path: str) -> bytes:
        return self._abs(path).read_bytes()

    def list(self, path: str) -> list[str]:
        directory = self._abs(path)

        if not directory.is_dir():
            return []

        return [
            item.name
            for item in directory.iterdir()
            if item.is_file()
        ]

    def delete(self, path: str) -> None:
        self._abs(path).unlink()

    def exists(self, path: str) -> bool:
        return self._abs(path).is_file()

    def watch(
        self,
        path: str,
        callback: Callable[[str], None] | None = None,
    ) -> None:
        """Добавляет директорию к наблюдению одного Observer."""

        watch_dir = self._abs(path)
        watch_dir.mkdir(parents=True, exist_ok=True)

        watch_dir = watch_dir.resolve()

        # Повторное добавление той же директории не требуется.
        if watch_dir in self._watched_dirs:
            if callback is not None and self._handler is not None:
                self._handler.add_callback(watch_dir, callback)

            logger.debug(
                f"Директория уже отслеживается: {watch_dir}"
            )
            return

        # Создаём Observer и обработчик только один раз.
        if self._observer is None:
            self._handler = _Handler(
                self.root,
                event_engine=self.event_engine,
            )

            self._observer = Observer()

        try:
            self._observer.schedule(
                self._handler,
                str(watch_dir),
                recursive=True,
            )

            self._watched_dirs.add(watch_dir)

            if callback is not None:
                self._handler.add_callback(watch_dir, callback)

            # Observer запускается только один раз,
            # последующие watch() добавляют новые директории.
            if not self._observer_started:
                self._observer.start()
                self._observer_started = True

            logger.info(
                f"Watchdog отслеживает директорию: {watch_dir}"
            )

        except Exception:
            logger.exception(
                f"Не удалось запустить наблюдение за {watch_dir}"
            )

            self._watched_dirs.discard(watch_dir)

            if not self._watched_dirs:
                self._observer = None
                self._handler = None
                self._observer_started = False

    def stop_watch(self) -> None:
        """Останавливает Observer и очищает наблюдаемые директории."""

        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join()
            except Exception:
                logger.exception("Ошибка остановки watchdog")
            finally:
                self._observer = None
                self._handler = None
                self._watched_dirs.clear()
                self._observer_started = False

            logger.info("Watchdog остановлен.")
