"""PostgreSQL-backed SSE replay for investigation events."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from typing import Any

from .services import ConversationError, events_for_turn, serialize_event


_LAST_EVENT_ID = re.compile(r"(?:0|[1-9][0-9]*)\Z")
MAX_EVENT_ID = 2_147_483_647


def parse_last_event_id(value: Any) -> int:
    """Parse the canonical non-negative decimal form used by EventSource."""

    if value is None or value == "":
        return 0
    if not isinstance(value, str) or not _LAST_EVENT_ID.fullmatch(value):
        raise ConversationError("invalid_last_event_id", "Last-Event-ID must be a canonical non-negative integer")
    parsed = int(value)
    if parsed > MAX_EVENT_ID:
        raise ConversationError("invalid_last_event_id", "Last-Event-ID is out of range")
    return parsed


def replay_events(user: Any, conversation_id: Any, turn_id: Any, last_event_id: Any = None) -> Iterator[str]:
    last_sequence = parse_last_event_id(last_event_id)
    events = events_for_turn(user, conversation_id, turn_id)
    yield from replay_event_rows(events, last_sequence)


def replay_event_rows(events: Iterable[Any], last_event_id: Any = 0) -> Iterator[str]:
    last_sequence = parse_last_event_id(last_event_id) if not isinstance(last_event_id, int) else last_event_id
    for event in events:
        if event.sequence <= last_sequence:
            continue
        yield format_sse(serialize_event(event))


def format_sse(event: dict[str, Any]) -> str:
    data = event.get("data", {})
    return (
        f"id: {int(event['sequence'])}\n"
        f"event: {event['event_type']}\n"
        f"data: {json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}\n\n"
    )
