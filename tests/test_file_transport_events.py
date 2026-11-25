"""Тесты событийного обработчика FileTransport."""

import pytest
from pathlib import Path

from watchdog.events import (
    FileCreatedEvent,
    FileModifiedEvent,
    FileDeletedEvent,
    FileMovedEvent,
)

from src.core.event_engine import EventEngine
from src.transport.file_transport import FileTransport, _Handler
import src.transport.file_transport as file_transport_module

def create_handler(tmp_path):
    root = tmp_path / "share"
    root.mkdir()

    engine = EventEngine()
    published = []
    callbacks = []

    engine.event_published.connect(published.append)

    handler = _Handler(root, callbacks.append, engine)

    return handler, root, published, callbacks


def test_created_event(create_handler_fixture):
    handler, root, published, callbacks = create_handler_fixture
    path = root / "message" / "chat1.json"

    handler.on_any_event(FileCreatedEvent(str(path)))

    assert len(published) == 1
    assert published[0].event_type == "file.created"
    assert published[0].payload["path"] == "message/chat1.json"
    assert callbacks == ["message/chat1.json"]


def test_modified_event(create_handler_fixture):
    handler, root, published, callbacks = create_handler_fixture
    path = root / "message" / "chat1.json"

    handler.on_any_event(FileModifiedEvent(str(path)))

    assert len(published) == 1
    assert published[0].event_type == "file.modified"
    assert callbacks == ["message/chat1.json"]


def test_deleted_event(create_handler_fixture):
    handler, root, published, callbacks = create_handler_fixture
    path = root / "message" / "chat1.json"

    handler.on_any_event(FileDeletedEvent(str(path)))

    assert len(published) == 1
    assert published[0].event_type == "file.deleted"
    assert published[0].payload["path"] == "message/chat1.json"
    assert callbacks == []


def test_moved_event(create_handler_fixture):
    handler, root, published, callbacks = create_handler_fixture
    source = root / "message" / "old.json"
    destination = root / "message" / "new.json"

    handler.on_any_event(
        FileMovedEvent(str(source), str(destination))
    )

    assert len(published) == 1
    assert published[0].event_type == "file.moved"
    assert published[0].payload["src_path"] == "message/old.json"
    assert published[0].payload["dest_path"] == "message/new.json"
    assert published[0].payload["path"] == "message/new.json"
    assert callbacks == []


def test_temporary_file_is_ignored(create_handler_fixture):
    handler, root, published, callbacks = create_handler_fixture
    path = root / "message" / "chat1.json.tmp"

    handler.on_any_event(FileCreatedEvent(str(path)))

    assert published == []
    assert callbacks == []


def test_moving_temp_file_to_final_name_is_detected(create_handler_fixture):
    handler, root, published, callbacks = create_handler_fixture
    source = root / "message" / "chat1.json.tmp"
    destination = root / "message" / "chat1.json"

    handler.on_any_event(
        FileMovedEvent(str(source), str(destination))
    )

    assert len(published) == 1
    assert published[0].event_type == "file.moved"
    assert published[0].payload["dest_path"] == "message/chat1.json"


def test_directory_event_is_ignored(create_handler_fixture):
    handler, root, published, callbacks = create_handler_fixture
    path = root / "message"

    event = FileCreatedEvent(str(path))
    event.is_directory = True

    handler.on_any_event(event)

    assert published == []
    assert callbacks == []


def test_path_outside_root_is_ignored(create_handler_fixture, tmp_path):
    handler, root, published, callbacks = create_handler_fixture
    outside = tmp_path / "outside.json"

    handler.on_any_event(FileCreatedEvent(str(outside)))

    assert published == []
    assert callbacks == []




@pytest.fixture
def create_handler_fixture(tmp_path):
    return create_handler(tmp_path)




def test_watchdog_publishes_event_and_calls_callback(
    tmp_path, monkeypatch
):
    root = tmp_path / "share"
    root.mkdir()

    engine = EventEngine()
    transport = FileTransport(root, event_engine=engine)

    published = []
    callbacks = []

    engine.event_published.connect(published.append)

    class FakeObserver:
        def __init__(self):
            self.handler = None
            self.path = None
            self.recursive = None
            self.started = False
            self.stopped = False
            self.joined = False

        def schedule(self, handler, path, recursive):
            self.handler = handler
            self.path = path
            self.recursive = recursive

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def join(self):
            self.joined = True

    monkeypatch.setattr(
        file_transport_module,
        "Observer",
        FakeObserver,
    )

    transport.watch(".", callbacks.append)

    observer = transport._observer

    assert observer is not None
    assert observer.started is True
    assert observer.handler is not None
    assert observer.recursive is True

    event = FileCreatedEvent(
        str(root / "integration_test.txt")
    )
    observer.handler.on_any_event(event)

    assert len(published) == 1
    assert published[0].event_type == "file.created"
    assert published[0].payload["path"] == "integration_test.txt"

    assert callbacks == ["integration_test.txt"]

    transport.stop_watch()

    assert observer.stopped is True
    assert observer.joined is True
    assert transport._observer is None


def test_watchdog_can_watch_multiple_directories_with_one_observer(
    tmp_path, monkeypatch
):
    root = tmp_path / "share"
    root.mkdir()
    engine = EventEngine()
    transport = FileTransport(root, event_engine=engine)

    class FakeObserver:
        def __init__(self):
            self.schedules = []
            self.started = False

        def schedule(self, handler, path, recursive):
            self.schedules.append((handler, path, recursive))

        def start(self):
            self.started = True

        def stop(self):
            pass

        def join(self):
            pass

    monkeypatch.setattr(file_transport_module, "Observer", FakeObserver)

    transport.watch("message/chat-1")
    first_observer = transport._observer
    transport.watch(".status")
    transport.watch(".meta")

    assert transport._observer is first_observer
    assert first_observer.started is True
    assert len(first_observer.schedules) == 3
    assert {Path(item[1]).name for item in first_observer.schedules} == {
        "chat-1", ".status", ".meta"
    }
    assert all(item[2] is True for item in first_observer.schedules)

    transport.stop_watch()
