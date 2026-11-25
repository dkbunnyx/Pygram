"""Централизованная, дедуплицированная синхронизация сообщений."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from loguru import logger
from PySide6.QtCore import QObject, QThread, Signal, Qt

from src.core.message import sync_messages_to_db
from src.core.event_engine import EventEngine


class _SyncWorker(QThread):
    completed = Signal(object, bool)

    def __init__(
        self,
        shared_folder,
        chat_id: str,
        user_fp16: str,
        user_priv_pem: str,
        sync_callable: Callable = sync_messages_to_db,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.shared_folder = shared_folder
        self.chat_id = chat_id
        self.user_fp16 = user_fp16
        self.user_priv_pem = user_priv_pem
        self.sync_callable = sync_callable

    def run(self) -> None:
        success = False
        try:
            self.sync_callable(
                self.shared_folder,
                self.chat_id,
                self.user_fp16,
                self.user_priv_pem,
                prune_missing=False,
            )
            success = True
        except Exception:
            logger.exception(f"Ошибка синхронизации чата {self.chat_id}")
        self.completed.emit(self, success)


@dataclass(frozen=True)
class _SyncRequest:
    shared_folder: object
    chat_id: str
    user_fp16: str
    user_priv_pem: str


class SyncEngine(QObject):
    """Не допускает параллельную синхронизацию одного чата.

    Повторные запросы во время активной синхронизации объединяются в один
    дополнительный проход. Разные чаты могут синхронизироваться независимо.
    """

    sync_finished = Signal(str, bool)

    def __init__(
        self,
        parent: QObject | None = None,
        sync_callable: Callable = sync_messages_to_db,
        event_engine: EventEngine | None = None,
        max_concurrent: int = 3,
    ):
        super().__init__(parent)
        if max_concurrent < 1:
            raise ValueError("max_concurrent должен быть не меньше 1")
        self._sync_callable = sync_callable
        self._event_engine = event_engine
        self._max_concurrent = int(max_concurrent)
        self._workers: dict[str, _SyncWorker] = {}
        self._pending: dict[str, _SyncRequest] = {}
        self._queued: dict[str, _SyncRequest] = {}
        self._closing = False

    def request_sync(
        self,
        shared_folder,
        chat_id: str,
        user_fp16: str,
        user_priv_pem: str,
        *,
        coalesce: bool = True,
    ) -> bool:
        if self._closing or not chat_id:
            return False

        request = _SyncRequest(
            shared_folder, chat_id, user_fp16, user_priv_pem
        )

        if chat_id in self._workers:
            # Событийные запросы требуют дополнительного прохода после текущей
            # синхронизации. Периодический fallback может быть проигнорирован.
            if coalesce:
                self._pending[chat_id] = request
            return False

        if chat_id in self._queued:
            if coalesce:
                self._queued[chat_id] = request
            return False

        if len(self._workers) >= self._max_concurrent:
            # Очередь нужна, чтобы пакетный запрос ChatList не терял чаты
            # при достижении лимита потоков. Повторные fallback-запросы
            # не перезаписывают уже поставленную в очередь задачу.
            self._queued[chat_id] = request
            return False

        self._start_request(request)
        return True

    def _start_request(self, request: _SyncRequest) -> None:
        worker = _SyncWorker(
            request.shared_folder,
            request.chat_id,
            request.user_fp16,
            request.user_priv_pem,
            sync_callable=self._sync_callable,
            parent=self,
        )
        self._workers[request.chat_id] = worker
        worker.completed.connect(
            self._on_worker_completed, Qt.ConnectionType.QueuedConnection
        )
        if self._event_engine is not None:
            self._event_engine.publish("sync.started", chat_id=request.chat_id)
        worker.start()

    def _on_worker_completed(self, worker: _SyncWorker, success: bool) -> None:
        # Сигнал может прийти до окончательного выхода из run(); wait() здесь
        # короткий и гарантирует, что старый поток завершён до следующего запуска.
        worker.wait()
        chat_id = worker.chat_id
        if self._workers.get(chat_id) is worker:
            self._workers.pop(chat_id, None)
        worker.deleteLater()

        self.sync_finished.emit(chat_id, success)
        if self._event_engine is not None:
            self._event_engine.publish(
                "sync.completed", chat_id=chat_id, success=bool(success)
            )

        pending = self._pending.pop(chat_id, None)
        if pending is not None and not self._closing:
            self._start_request(pending)
        self._start_queued_requests()

    def _start_queued_requests(self) -> None:
        while not self._closing and len(self._workers) < self._max_concurrent and self._queued:
            first_chat_id = next(iter(self._queued))
            request = self._queued.pop(first_chat_id)
            self._start_request(request)

    def is_syncing(self, chat_id: str) -> bool:
        return chat_id in self._workers or chat_id in self._queued

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Запрещает новые задачи и ожидает завершения активных потоков."""
        self._closing = True
        all_stopped = True
        for worker in tuple(self._workers.values()):
            if worker.isRunning() and not worker.wait(timeout_ms):
                all_stopped = False

        if not all_stopped:
            # Закрытие окна было отменено: возвращаем движок в рабочее состояние.
            self._closing = False
            return False

        self._pending.clear()
        self._queued.clear()
        return True

    def resume(self) -> None:
        """Возобновляет приём задач, если закрытие окна было отменено."""
        self._closing = False
