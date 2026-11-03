import asyncio
import threading

from app.services.events import Event, Hub, format_sse, stream


def run(coro):
    return asyncio.run(coro)


def test_format_sse():
    assert format_sse(Event("state", {"a": 1, "b": "x\ny"})) == 'event: state\ndata: {"a":1,"b":"x\\ny"}\n\n'


def test_publish_reaches_only_the_matching_game_and_audience():
    async def scenario():
        hub = Hub()
        players = hub.subscribe(1, "players")
        host = hub.subscribe(1, "host")
        other_game = hub.subscribe(2, "players")
        hub.publish(1, "players", Event("state", {"n": 1}))
        await asyncio.sleep(0.01)
        assert (players.queue.qsize(), host.queue.qsize(), other_game.queue.qsize()) == (1, 0, 0)
    run(scenario())


def test_publish_is_safe_from_another_thread():
    async def scenario():
        hub = Hub()
        sub = hub.subscribe(1, "host")
        thread = threading.Thread(target=hub.publish, args=(1, "host", Event("state", {"n": 7})))
        thread.start()
        thread.join()
        event = await asyncio.wait_for(sub.queue.get(), timeout=1)
        assert event.data == {"n": 7}
    run(scenario())


def test_full_queue_drops_the_oldest_event():
    async def scenario():
        hub = Hub()
        sub = hub.subscribe(1, "players")
        for n in range(sub.queue.maxsize + 3):
            hub.publish(1, "players", Event("state", {"n": n}))
        await asyncio.sleep(0.05)
        items = [sub.queue.get_nowait().data["n"] for _ in range(sub.queue.qsize())]
        assert items[-1] == sub.queue.maxsize + 2  # newest kept
        assert items == sorted(items) and len(items) == sub.queue.maxsize
    run(scenario())


def test_unsubscribe_stops_delivery_and_cleans_up():
    async def scenario():
        hub = Hub()
        sub = hub.subscribe(1, "players")
        assert hub.subscriber_count(1) == 1
        hub.unsubscribe(sub)
        hub.publish(1, "players", Event("state", {}))
        await asyncio.sleep(0.01)
        assert sub.queue.empty() and hub.subscriber_count(1) == 0
    run(scenario())


def test_stream_sends_initial_then_live_events_then_keepalives():
    async def scenario():
        hub = Hub()
        sub = hub.subscribe(1, "players")
        chunks = stream(sub, initial=[Event("state", {"n": 0})], keepalive=0.05)
        assert (await anext(chunks)).startswith("event: state")
        hub.publish(1, "players", Event("state", {"n": 1}))
        assert '"n":1' in await anext(chunks)
        assert await anext(chunks) == ": keepalive\n\n"
        await chunks.aclose()
    run(scenario())
