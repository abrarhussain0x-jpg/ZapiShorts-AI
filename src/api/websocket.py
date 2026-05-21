"""WebSocket connection manager and progress streaming endpoint."""

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


class WebSocketManager:
    """Manages active WebSocket connections keyed by job_id."""

    def __init__(self):
        self._connections: Dict[str, List[WebSocket]] = defaultdict(list)

    async def connect(self, job_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[job_id].append(ws)
        logger.debug(
            "WS connected: job=%s total=%d", job_id, len(self._connections[job_id])
        )

    def disconnect(self, job_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(job_id, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self._connections.pop(job_id, None)
        logger.debug("WS disconnected: job=%s", job_id)

    async def broadcast(self, job_id: str, data: Any) -> None:
        """Send a JSON message to all connections subscribed to job_id."""
        dead = []
        for ws in list(self._connections.get(job_id, [])):
            try:
                await ws.send_text(json.dumps(data, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(job_id, ws)

    def get_broadcast_fn(self, job_id: str):
        """Return a sync-safe broadcast callable for use in background threads."""
        manager = self

        def _sync_broadcast(data: Any) -> None:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(manager.broadcast(job_id, data))
            except Exception:
                pass
            finally:
                loop.close()

        return _sync_broadcast

    @property
    def active_jobs(self) -> List[str]:
        return list(self._connections.keys())

    @property
    def total_connections(self) -> int:
        return sum(len(v) for v in self._connections.values())


# Global singleton
ws_manager = WebSocketManager()


@router.websocket("/jobs/{job_id}")
async def websocket_job_progress(job_id: str, websocket: WebSocket):
    """Stream real-time progress events for a processing job.

    Event format:
        {"progress": 0-100, "stage": "download|encode|upload|done", "message": "..."}
    """
    await ws_manager.connect(job_id, websocket)
    try:
        # Send initial ack
        await websocket.send_text(
            json.dumps(
                {
                    "progress": 0,
                    "stage": "connected",
                    "message": f"Connected to job {job_id}",
                    "job_id": job_id,
                }
            )
        )
        # Keep connection alive until client disconnects
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(job_id, websocket)


@router.websocket("/system")
async def websocket_system_metrics(websocket: WebSocket):
    """Stream system metrics every 5 seconds."""
    import psutil

    await websocket.accept()
    try:
        while True:
            payload = {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory_percent": psutil.virtual_memory().percent,
                "active_ws_jobs": ws_manager.active_jobs,
                "total_ws_connections": ws_manager.total_connections,
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
    except ImportError:
        await websocket.send_text(json.dumps({"error": "psutil not installed"}))
        await websocket.close()
