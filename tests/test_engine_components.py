"""Тесты Qt Signal Bridge, Tick Engine и Sync Engine."""

import time

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from src.core.event_engine import EventEngine
from src.core.qt_signal_bridge import QtSignalBridge
from src.core.sync_engine import SyncEngine
from src.core.tick_engine import TickEngine


@pytest.fixture(scope="module")
def qt_app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def run_event_loop(milliseconds: int, qt_app):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def test_qt_signal_bridge_delivers_events_through_qt_queue(qt_app):
    engine = EventEngine()
    bridge = QtSignalBridge(engine)
    received = []
    bridge.event_received.connect(received.append)

    event = engine.publish("message.created", chat_id="chat-1")

    # QueuedConnection: обработчик не должен вызываться синхронно в publish().
    assert received == []
    run_event_loop(30, qt_app)

    assert received == [event]
    bridge.shutdown()


def test_tick_engine_runs_registered_fallback_job(qt_app):
    engine = TickEngine(tick_interval_ms=10)
    calls = []
    engine.register("fallback", lambda: calls.append(time.monotonic()), 20)

    run_event_loop(90, qt_app)
    engine.stop()

    assert len(calls) >= 2


def test_tick_engine_unregister_stops_job(qt_app):
    engine = TickEngine(tick_interval_ms=10)
    calls = []
    engine.register("fallback", lambda: calls.append(1), 10)
    assert engine.unregister("fallback") is True

    run_event_loop(50, qt_app)
    engine.stop()

    assert calls == []


def test_sync_engine_coalesces_multiple_requests_for_same_chat(qt_app):
    calls = []

    def fake_sync(shared_folder, chat_id, user_fp16, user_priv_pem, prune_missing):
        calls.append(chat_id)
        time.sleep(0.03)

    engine = SyncEngine(sync_callable=fake_sync)
    completed = []
    loop = QEventLoop()

    def on_finished(chat_id, success):
        completed.append((chat_id, success))
        if len(completed) == 2:
            loop.quit()

    engine.sync_finished.connect(on_finished)

    assert engine.request_sync("share", "chat-1", "fp", "private") is True
    assert engine.request_sync("share", "chat-1", "fp", "private") is False
    assert engine.request_sync("share", "chat-1", "fp", "private") is False

    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    engine.shutdown()

    assert completed == [("chat-1", True), ("chat-1", True)]
    assert calls == ["chat-1", "chat-1"]


def test_sync_engine_allows_different_chats_in_parallel(qt_app):
    calls = []

    def fake_sync(shared_folder, chat_id, user_fp16, user_priv_pem, prune_missing):
        calls.append(chat_id)
        time.sleep(0.02)

    engine = SyncEngine(sync_callable=fake_sync)
    completed = []
    loop = QEventLoop()

    def on_finished(chat_id, success):
        completed.append(chat_id)
        if len(completed) == 2:
            loop.quit()

    engine.sync_finished.connect(on_finished)
    engine.request_sync("share", "chat-1", "fp", "private")
    engine.request_sync("share", "chat-2", "fp", "private")

    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    engine.shutdown()

    assert set(completed) == {"chat-1", "chat-2"}
    assert set(calls) == {"chat-1", "chat-2"}


def test_sync_engine_limits_parallel_workers(qt_app):
    from threading import Lock

    lock = Lock()
    active = 0
    maximum_seen = 0
    completed = []

    def fake_sync(shared_folder, chat_id, user_fp16, user_priv_pem, prune_missing):
        nonlocal active, maximum_seen
        with lock:
            active += 1
            maximum_seen = max(maximum_seen, active)
        time.sleep(0.03)
        with lock:
            active -= 1

    engine = SyncEngine(sync_callable=fake_sync, max_concurrent=1)
    loop = QEventLoop()

    def on_finished(chat_id, success):
        completed.append(chat_id)
        if len(completed) == 3:
            loop.quit()

    engine.sync_finished.connect(on_finished)
    engine.request_sync("share", "chat-1", "fp", "private")
    engine.request_sync("share", "chat-2", "fp", "private")
    engine.request_sync("share", "chat-3", "fp", "private")

    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    engine.shutdown()

    assert set(completed) == {"chat-1", "chat-2", "chat-3"}
    assert maximum_seen == 1
