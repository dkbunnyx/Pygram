
"""Тесты для Pygram Event Engine."""

import pytest

from src.core.event_engine import EventEngine, PygramEvent


class TestEventEngine:
    def test_publish_creates_event(self):
        engine = EventEngine()

        event = engine.publish(
            "message.created",
            chat_id="chat_123",
            message_id="msg_456",
        )

        assert isinstance(event, PygramEvent)
        assert event.event_type == "message.created"
        assert event.payload == {
            "chat_id": "chat_123",
            "message_id": "msg_456",
        }

    def test_publish_emits_signal(self):
        engine = EventEngine()
        received = []

        engine.event_published.connect(received.append)

        event = engine.publish("message.created", chat_id="123")

        assert len(received) == 1
        assert received[0] is event

    def test_multiple_subscribers_receive_event(self):
        engine = EventEngine()
        first = []
        second = []

        engine.event_published.connect(first.append)
        engine.event_published.connect(second.append)

        event = engine.publish("reaction.changed")

        assert first == [event]
        assert second == [event]

    def test_empty_event_type_is_rejected(self):
        engine = EventEngine()

        with pytest.raises(ValueError):
            engine.publish("")

        with pytest.raises(ValueError):
            engine.publish("   ")

    def test_non_string_event_type_is_rejected(self):
        engine = EventEngine()

        with pytest.raises(ValueError):
            engine.publish(123)

    def test_event_type_is_stripped(self):
        engine = EventEngine()

        event = engine.publish("  message.created  ")

        assert event.event_type == "message.created"
