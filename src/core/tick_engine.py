"""Централизованный периодический механизм резервной сверки."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from loguru import logger
from PySide6.QtCore import QObject, QTimer


@dataclass
class _TickJob:
    callback: Callable[[], None]
    interval_ms: int
    next_run: float


class TickEngine(QObject):
    """Запускает зарегистрированные fallback-задачи в GUI-потоке Qt.

    События остаются основным способом обновления. TickEngine нужен для
    восстановления после пропущенных файловых событий и периодической сверки.
    """

    def __init__(
        self,
        parent: QObject | None = None,
        tick_interval_ms: int = 250,
    ):
        super().__init__(parent)
        if tick_interval_ms < 10:
            raise ValueError("tick_interval_ms должен быть не меньше 10 мс")

        self._jobs: dict[str, _TickJob] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(tick_interval_ms)
        self._timer.timeout.connect(self._run_due_jobs)
        self._timer.start()

    def register(
        self,
        name: str,
        callback: Callable[[], None],
        interval_ms: int,
        *,
        immediate: bool = False,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Имя tick-задачи не может быть пустым")
        if interval_ms < 1:
            raise ValueError("Интервал tick-задачи должен быть положительным")
        if not callable(callback):
            raise TypeError("callback должен быть вызываемым объектом")

        now = time.monotonic()
        self._jobs[name] = _TickJob(
            callback=callback,
            interval_ms=int(interval_ms),
            next_run=now if immediate else now + interval_ms / 1000,
        )

    def unregister(self, name: str) -> bool:
        return self._jobs.pop(name, None) is not None

    def has_job(self, name: str) -> bool:
        return name in self._jobs

    def stop(self) -> None:
        self._timer.stop()
        self._jobs.clear()

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def _run_due_jobs(self) -> None:
        now = time.monotonic()
        for name, job in tuple(self._jobs.items()):
            if now < job.next_run:
                continue

            # Не пытаемся проигрывать пропущенные тики пачкой: один запуск
            # актуализирует состояние, следующий назначается от текущего времени.
            job.next_run = now + job.interval_ms / 1000
            try:
                job.callback()
            except RuntimeError:
                # Виджет мог быть уничтожен между регистрацией и тиком.
                self._jobs.pop(name, None)
            except Exception:
                logger.exception(f"Ошибка резервной tick-задачи: {name}")
