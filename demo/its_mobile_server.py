"""
Mock ITS Mobile Server + WebSocket Telemetry Server.

Single FastAPI process on port 8001 that combines:
  - Mock ITS Mobile endpoints:
      GET  /instruction   -> current picking task prompt
      POST /command       -> validates corrected command against expected_grammar,
                             advances queue
  - Telemetry WebSocket:
      WS   /telemetry     -> broadcasts {stage: raw_intent|corrected_command, text}

State machine: waiting_for_instruction -> waiting_for_command -> validating
               -> next_instruction -> waiting_for_instruction (cycle).
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import List, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


# --- Task queue ---------------------------------------------------------------

@dataclass
class PickingTask:
    prompt: str
    expected_grammar: List[str]


TASKS: List[PickingTask] = [
    PickingTask(
        prompt="Pick 5 units from bin A-12",
        expected_grammar=["PICK", "5", "A-12", "CONFIRM"],
    ),
    PickingTask(
        prompt="Pick 10 units from bin B-03",
        expected_grammar=["PICK", "10", "B-03", "CONFIRM"],
    ),
    PickingTask(
        prompt="Pick 2 units from bin C-07",
        expected_grammar=["PICK", "2", "C-07", "CONFIRM"],
    ),
    PickingTask(
        prompt="Skip damaged item and continue",
        expected_grammar=["SKIP"],
    ),
    PickingTask(
        prompt="Confirm completion of current order",
        expected_grammar=["CONFIRM"],
    ),
]


# --- Server state -------------------------------------------------------------

@dataclass
class ServerState:
    index: int = 0
    state: str = "waiting_for_instruction"
    history: List[dict] = field(default_factory=list)

    def current(self) -> PickingTask:
        return TASKS[self.index % len(TASKS)]

    def advance(self) -> None:
        self.index = (self.index + 1) % len(TASKS)
        self.state = "waiting_for_instruction"


STATE = ServerState()


# --- WebSocket hub ------------------------------------------------------------

class TelemetryHub:
    def __init__(self) -> None:
        self.clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.clients.discard(ws)

    async def broadcast(self, payload: dict) -> None:
        data = json.dumps(payload)
        dead: List[WebSocket] = []
        # Snapshot under lock, send outside lock.
        async with self._lock:
            clients = list(self.clients)
        for ws in clients:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self.clients.discard(ws)


HUB = TelemetryHub()


# --- FastAPI app --------------------------------------------------------------

app = FastAPI(title="Mock ITS Mobile + Telemetry", version="0.1.0")


class CommandPayload(BaseModel):
    # Accept a flexible payload — orchestrator may send the normalized command
    # string, or the full RecognitionResult from the middleware.
    matched_command: str | None = None
    mapped_value: str | None = None
    transcribed_text: str | None = None
    command: str | None = None  # convenience alias


@app.get("/instruction")
async def get_instruction():
    if STATE.state == "waiting_for_command":
        # Already handed out — return same task until command arrives.
        pass
    else:
        STATE.state = "waiting_for_command"
    task = STATE.current()
    return {
        "index": STATE.index,
        "prompt": task.prompt,
        "expected_grammar": task.expected_grammar,
        "state": STATE.state,
    }


@app.post("/command")
async def post_command(payload: CommandPayload):
    STATE.state = "validating"
    task = STATE.current()

    candidates = [
        payload.matched_command,
        payload.mapped_value,
        payload.command,
        payload.transcribed_text,
    ]
    token = next((c for c in candidates if c), "") or ""
    token_upper = token.strip().upper()

    success = any(token_upper == g.upper() for g in task.expected_grammar)

    entry = {
        "index": STATE.index,
        "prompt": task.prompt,
        "expected_grammar": task.expected_grammar,
        "received": token_upper,
        "success": success,
    }
    STATE.history.append(entry)

    if success:
        STATE.advance()
        next_task = STATE.current()
        return {
            "success": True,
            "validated": token_upper,
            "next_prompt": next_task.prompt,
            "state": STATE.state,
        }

    STATE.state = "waiting_for_command"
    return {
        "success": False,
        "validated": token_upper,
        "expected_grammar": task.expected_grammar,
        "state": STATE.state,
    }


@app.get("/state")
async def get_state():
    task = STATE.current()
    return {
        "index": STATE.index,
        "state": STATE.state,
        "current_prompt": task.prompt,
        "expected_grammar": task.expected_grammar,
        "history": STATE.history[-10:],
    }


@app.post("/telemetry/publish")
async def publish_telemetry(payload: dict):
    """Internal endpoint used by the orchestrator to push telemetry events
    without holding a WebSocket connection itself."""
    asyncio.create_task(HUB.broadcast(payload))
    return {"queued": True}


@app.websocket("/telemetry")
async def telemetry_ws(ws: WebSocket):
    await HUB.connect(ws)
    try:
        while True:
            # Keep connection alive; ignore any client messages.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await HUB.disconnect(ws)


# --- Static demo screen -------------------------------------------------------

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
async def index():
    path = os.path.join(_STATIC_DIR, "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="index.html not found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
