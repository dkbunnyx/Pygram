"""Проверка маршрутизации файловых событий в ChatViewWidget."""

from types import SimpleNamespace

from src.core.event_engine import PygramEvent
from src.ui.chat_view import ChatViewWidget


class _MessagesModel:
    def __init__(self):
        self.removed = []

    def remove_message_by_id(self, msg_id):
        self.removed.append(msg_id)


class _DB:
    def __init__(self):
        self.deleted = []

    def delete_message(self, msg_id):
        self.deleted.append(msg_id)


def make_view():
    view = SimpleNamespace(
        current_chat_id="chat-1",
        current_other_fp="other-fp",
        user=SimpleNamespace(fp16="my-fp", priv_pem="private"),
        messages_model=_MessagesModel(),
        db=_DB(),
        _last_file_count=5,
        _reactions_cache={"msg-123": {"fp": "👍"}},
        selected_msg_ids={"msg-123"},
        calls=[],
    )
    view._trigger_sync = lambda: view.calls.append("sync")
    view._refresh_reactions_if_changed = lambda: view.calls.append("reactions")
    view._refresh_read_status_if_changed = lambda: view.calls.append("read")
    view._sync_and_render = lambda: view.calls.append("render")
    view._update_status = lambda: view.calls.append("presence")
    view._refresh_group_metadata = lambda: view.calls.append("group")
    return view


def event(event_type, path):
    return PygramEvent(event_type, {"path": path})


def test_new_message_file_requests_sync():
    view = make_view()
    ChatViewWidget._on_event_published(view, event("file.moved", "message/chat-1/123.bin"))
    assert view.calls == ["sync"]


def test_physical_message_deletion_removes_local_copy():
    view = make_view()
    ChatViewWidget._on_event_published(view, event("file.deleted", "message/chat-1/msg-123.bin"))
    assert view.messages_model.removed == ["msg-123"]
    assert view.db.deleted == ["msg-123"]
    assert view._last_file_count == -1
    assert "msg-123" not in view._reactions_cache
    assert "msg-123" not in view.selected_msg_ids


def test_reaction_event_refreshes_reactions():
    view = make_view()
    ChatViewWidget._on_event_published(view, event("file.moved", ".status/reactions/chat-1_msg.json"))
    assert view.calls == ["reactions"]


def test_read_event_refreshes_read_receipts():
    view = make_view()
    ChatViewWidget._on_event_published(view, event("file.moved", ".status/read/chat-1_other.json"))
    assert view.calls == ["read"]


def test_deleted_marker_refreshes_chat():
    view = make_view()
    ChatViewWidget._on_event_published(view, event("file.moved", ".status/deleted/chat-1.json"))
    assert view.calls == ["render"]


def test_presence_event_updates_status():
    view = make_view()
    ChatViewWidget._on_event_published(view, event("file.moved", ".status/other-fp.json"))
    assert view.calls == ["presence"]


def test_group_metadata_event_refreshes_group():
    view = make_view()
    view.current_chat_id = "grp_123"
    ChatViewWidget._on_event_published(view, event("file.moved", ".meta/grp_123.enc"))
    assert view.calls == ["group"]


def test_unrelated_file_event_is_ignored():
    view = make_view()
    ChatViewWidget._on_event_published(view, event("file.moved", ".profiles/other.png"))
    assert view.calls == []
