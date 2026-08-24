"""Bounded, isolated conversation memory."""

from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    role: str
    content: str


class SessionMemory:
    def __init__(self, max_messages: int = 12) -> None:
        self._sessions: dict[str, deque[Message]] = defaultdict(
            lambda: deque(maxlen=max_messages)
        )

    def add(self, session_id: str, role: str, content: str) -> None:
        self._sessions[session_id].append(Message(role, content))

    def recent(self, session_id: str) -> list[Message]:
        return list(self._sessions.get(session_id, ()))

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)