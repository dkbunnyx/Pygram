"""Безопасный мост событий EventEngine в GUI-поток Qt."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal, Slot

from src.core.event_engine import EventEngine, PygramEvent


class QtSignalBridge(QObject):
    """Перенаправляет события в поток, которому принадлежит bridge.

    EventEngine может публиковать события из watchdog/QThread. Подключение
    QueuedConnection гарантирует, что обработчик bridge будет вызван через
    очередь событий Qt, а UI-подписчики получат сигнал из GUI-потока.
    """

    event_received = Signal(object)

    def __init__(self, event_engine: EventEngine, parent: QObject | None = None):
        super().__init__(parent)
        self._event_engine = event_engine
        self._connected = True
        self._event_engine.event_published.connect(
            self._forward_event,
            Qt.ConnectionType.QueuedConnection,
        )

    @Slot(object)
    def _forward_event(self, event: PygramEvent) -> None:
        if self._connected:
            self.event_received.emit(event)

    def shutdown(self) -> None:
        """Отключает мост; повторный вызов безопасен."""
        if not self._connected:
            return
        self._connected = False
        try:
            self._event_engine.event_published.disconnect(self._forward_event)
        except (RuntimeError, TypeError):
            pass
