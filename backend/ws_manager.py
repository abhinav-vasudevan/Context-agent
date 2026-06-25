"""
WebSocket Manager — handles real-time communication with the React frontend.

Broadcasts:
  - LLM token stream (live AI output)
  - Process stdout/stderr (live terminal output)
  - Status updates (step progress, errors)
  - Input requests (when a process needs user input)
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional, Dict, Set
from fastapi import WebSocket

log = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections and broadcasts messages to all connected clients.
    Since this is localhost-only, single-user, we keep it simple.
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        log.info("WebSocket client connected. Total: %d", len(self.active_connections))

    async def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket."""
        async with self._lock:
            self.active_connections.discard(websocket)
        log.info("WebSocket client disconnected. Total: %d", len(self.active_connections))

    async def broadcast(self, message: dict):
        """Broadcast a JSON message to all connected clients."""
        if not self.active_connections:
            return
        text = json.dumps(message)
        dead = set()
        async with self._lock:
            for ws in self.active_connections:
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.add(ws)
            self.active_connections -= dead

    async def send_to(self, websocket: WebSocket, message: dict):
        """Send a message to a specific client."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception:
            pass

    # ── Convenience broadcast methods ─────────────────────────────────

    async def send_llm_token(self, token: str):
        """Broadcast a single LLM content token to all clients."""
        await self.broadcast({
            "type": "llm_token",
            "data": {"token": token},
        })

    async def send_llm_thinking(self, token: str):
        """Broadcast a single LLM thinking/reasoning token to all clients."""
        await self.broadcast({
            "type": "llm_thinking",
            "data": {"token": token},
        })

    async def send_llm_done(self, full_text: str):
        """Signal that LLM generation is complete."""
        await self.broadcast({
            "type": "llm_done",
            "data": {"full_text": full_text},
        })

    async def send_process_stdout(self, text: str):
        """Broadcast process stdout output."""
        await self.broadcast({
            "type": "process_stdout",
            "data": {"text": text},
        })

    async def send_process_stderr(self, text: str):
        """Broadcast process stderr output."""
        await self.broadcast({
            "type": "process_stderr",
            "data": {"text": text},
        })

    async def send_process_done(self, success: bool, exit_code: int, error: Optional[str] = None):
        """Signal that a process has finished running."""
        await self.broadcast({
            "type": "process_done",
            "data": {
                "success": success,
                "exit_code": exit_code,
                "error": error,
            },
        })

    async def send_input_request(self, prompt_text: str = ""):
        """Signal that the running process is waiting for user input."""
        await self.broadcast({
            "type": "input_request",
            "data": {"prompt": prompt_text},
        })

    async def send_status(self, status: str, detail: str = "", data: Optional[dict] = None):
        """Broadcast a status update."""
        await self.broadcast({
            "type": "status",
            "data": {
                "status": status,
                "detail": detail,
                **(data or {}),
            },
        })

    async def send_step_update(self, step_number: int, status: str, detail: str = ""):
        """Broadcast a step status update."""
        await self.broadcast({
            "type": "step_update",
            "data": {
                "step_number": step_number,
                "status": status,
                "detail": detail,
            },
        })

    async def send_error(self, error: str, file_path: str = ""):
        """Broadcast an error message."""
        await self.broadcast({
            "type": "error",
            "data": {
                "error": error,
                "file_path": file_path,
            },
        })

    async def send_permission_request(self, request_id: str, question: str, default: bool = False):
        """Ask the frontend for permission (e.g., before executing code)."""
        await self.broadcast({
            "type": "permission_request",
            "data": {
                "request_id": request_id,
                "question": question,
                "default": default,
            },
        })

    async def send_file_update(self, file_path: str, content: str = ""):
        """Notify that a file has been created or updated."""
        await self.broadcast({
            "type": "file_update",
            "data": {
                "file_path": file_path,
                "content": content,
            },
        })

    async def send_plan_update(self, plan_steps: list):
        """Broadcast the full plan state."""
        await self.broadcast({
            "type": "plan_update",
            "data": {"steps": plan_steps},
        })
