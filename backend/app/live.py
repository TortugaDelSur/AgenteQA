"""Vista en vivo: bus en memoria por sesion + WebSocket de solo lectura (servidor -> cliente).

ponytail: bus de un solo proceso; con varios workers de uvicorn cada uno ve solo lo suyo.
Si se escala, pasar a Redis pub/sub.
"""
import asyncio
import time
from collections import defaultdict

from fastapi import APIRouter, WebSocket

router = APIRouter()

QUEUE_SIZE = 100
_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
# ultima vez que alguien miraba la sesion: sirve para apagar el repo levantado si la pagina se
# cerro o se corto internet (ver repo/launch.py::reap_idle).
_last_seen: dict[str, float] = {}


def is_watched(session_id: str) -> bool:
    return bool(_subscribers.get(session_id))


def last_seen(session_id: str) -> float | None:
    return _last_seen.get(session_id)


def publish(session_id: str, message: dict) -> None:
    for queue in list(_subscribers.get(session_id, ())):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            # cliente lento: se pierde el mensaje (en frames no importa, llega el siguiente).
            pass


@router.websocket("/ws/live/{session_id}")
async def ws_live(websocket: WebSocket, session_id: str) -> None:
    # solo lectura: nunca se hace receive(); lo que mande el cliente se ignora.
    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
    _subscribers[session_id].add(queue)
    try:
        await websocket.accept()
        while True:
            await websocket.send_json(await queue.get())
    except Exception:  # cliente se fue (WebSocketDisconnect, socket cerrado, etc)
        pass
    finally:
        _last_seen[session_id] = time.monotonic()
        _subscribers[session_id].discard(queue)
        if not _subscribers[session_id]:
            _subscribers.pop(session_id, None)
