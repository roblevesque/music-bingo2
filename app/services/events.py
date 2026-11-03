"""In-memory publish/subscribe for live updates over Server-Sent Events.

Single-process by design (see README). `publish` is safe to call from any thread.
Events are state snapshots, so a slow client can safely miss the older ones.
"""

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass

PLAYERS = "players"
HOST = "host"


@dataclass(frozen=True)
class Event:
    name: str
    data: dict


def format_sse(event: Event) -> str:
    # json.dumps never emits a raw newline, so one `data:` line is always enough.
    return f"event: {event.name}\ndata: {json.dumps(event.data, separators=(',', ':'))}\n\n"


class Subscription:
    def __init__(self, game_id: int, audience: str, loop: asyncio.AbstractEventLoop, maxsize: int = 20):
        self.game_id = game_id
        self.audience = audience
        self.loop = loop
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)

    def _put(self, event: Event) -> None:
        if self.queue.full():
            self.queue.get_nowait()  # drop the oldest; the newest snapshot supersedes it
        self.queue.put_nowait(event)

    def deliver(self, event: Event) -> None:
        try:
            self.loop.call_soon_threadsafe(self._put, event)
        except RuntimeError:  # the event loop has shut down
            pass


class Hub:
    def __init__(self) -> None:
        self._subscriptions: dict[int, set[Subscription]] = {}
        self._lock = threading.Lock()

    def subscribe(self, game_id: int, audience: str) -> Subscription:
        """Call from inside the event loop that will read the queue."""
        sub = Subscription(game_id, audience, asyncio.get_running_loop())
        with self._lock:
            self._subscriptions.setdefault(game_id, set()).add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            subs = self._subscriptions.get(sub.game_id)
            if subs:
                subs.discard(sub)
                if not subs:
                    del self._subscriptions[sub.game_id]

    def publish(self, game_id: int, audience: str, event: Event) -> None:
        with self._lock:
            targets = [s for s in self._subscriptions.get(game_id, ()) if s.audience == audience]
        for sub in targets:
            sub.deliver(event)

    def subscriber_count(self, game_id: int, audience: str | None = None) -> int:
        with self._lock:
            subs = self._subscriptions.get(game_id, set())
            return sum(1 for s in subs if audience is None or s.audience == audience)


async def stream(sub: Subscription, initial: Iterable[Event] = (), keepalive: float = 15.0) -> AsyncIterator[str]:
    """Yield SSE text: the initial snapshot(s), then live events, with periodic keep-alives."""
    for event in initial:
        yield format_sse(event)
    while True:
        try:
            event = await asyncio.wait_for(sub.queue.get(), timeout=keepalive)
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
            continue
        yield format_sse(event)
