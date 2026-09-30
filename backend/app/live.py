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


async def _send_loop(websocket: WebSocket, queue: asyncio.Queue) -> None:
    while True:
        await websocket.send_json(await queue.get())


async def _until_disconnect(websocket: WebSocket) -> None:
    """Lee solo para enterarse de que el cliente se fue; lo que mande se descarta (solo lectura).
    Sin esto, una sesion sin mensajes queda colgada en queue.get() para siempre y sigue contando
    como "mirada" aunque la pagina se haya cerrado (bug real en la e2e: el repo nunca se apagaba)."""
    while (await websocket.receive())["type"] != "websocket.disconnect":
        pass


@router.websocket("/ws/live/{session_id}")
async def ws_live(websocket: WebSocket, session_id: str) -> None:
    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
    _subscribers[session_id].add(queue)
    tasks: list[asyncio.Task] = []
    try:
        await websocket.accept()
        tasks = [asyncio.create_task(_send_loop(websocket, queue)), asyncio.create_task(_until_disconnect(websocket))]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except Exception:  # cliente se fue (WebSocketDisconnect, socket cerrado, etc)
        pass
    finally:
        for task in tasks:
            task.cancel()
        _last_seen[session_id] = time.monotonic()
        _subscribers[session_id].discard(queue)
        if not _subscribers[session_id]:
            _subscribers.pop(session_id, None)
