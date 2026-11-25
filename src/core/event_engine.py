"""Центральное ядро событий Pygram Event Engine."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class PygramEvent:
    """Событие, опубликованное внутри Pygram."""

    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)


class EventEngine(QObject):
    """Центральный канал публикации событий Pygram."""

    event_published = Signal(object)

    def publish(self, event_type: str, **payload: Any) -> PygramEvent:
        """Создаёт и публикует событие."""

        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("Тип события не может быть пустым")

        event = PygramEvent(
            event_type=event_type.strip(),
            payload=dict(payload),
        )

        self.event_published.emit(event)
        return event
