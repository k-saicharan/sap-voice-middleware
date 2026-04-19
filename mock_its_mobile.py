import asyncio
import logging
import random
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mock_its_mobile")

app = FastAPI(title="Mock ITS Mobile Server", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared Tasks
TASKS = [
    {"task_id": "TSK-0001", "location": "A-12", "material": "Diet Coke 12-pack"},
    {"task_id": "TSK-0002", "location": "B-04", "material": "Sprite Zero 6-pack"},
    {"task_id": "TSK-0003", "location": "C-09", "material": "Dasani Water 24-can"},
    {"task_id": "TSK-0004", "location": "D-01", "material": "Fanta Orange 2L"},
    {"task_id": "TSK-0005", "location": "E-22", "material": "Dr. Pepper 12-pack"},
]

# State Variables
app.state.current = "DISPLAY"
app.state.task_index = 0
app.state.current_quantity = random.randint(1, 25)

class State(BaseModel):
    current_state: str
    task_id: str
    location: str
    quantity: int
    material: str
    commands_expected: list[str]

class PickConfirmation(BaseModel):
    command: str

def get_current_task():
    task = TASKS[app.state.task_index % len(TASKS)].copy()
    task["quantity"] = app.state.current_quantity
    return task

def get_expected_commands(state: str) -> list[str]:
    if state in ["DISPLAY", "SCAN"]:
        return ["CAMERA", "TASK OVERVIEW", "SKIP", "CANCEL"]
    elif state == "VOICE":
        # Allow a wide range of numeric picks to be recognized grammars
        return [f"PICK {i}" for i in range(1, 41)] + ["REPEAT", "CANCEL", "CAMERA"]
    return []

@app.get("/api/state", response_model=State)
async def get_state():
    task = get_current_task()
    return State(
        current_state=app.state.current,
        task_id=task["task_id"],
        location=task["location"],
        quantity=task["quantity"],
        material=task["material"],
        commands_expected=get_expected_commands(app.state.current),
    )

@app.post("/api/scan")
async def trigger_scan(success: bool = True):
    """ Simulate the camera scanning the barcode. """
    if app.state.current not in ["DISPLAY", "SCAN"]:
        raise HTTPException(status_code=400, detail="Not in a state to scan.")
    
    if success:
        app.state.current = "VOICE"
        logger.info(f"Scan successful -> Transition to VOICE. Target QTY: {app.state.current_quantity}")
        return {"status": "success", "message": "Barcode scanned successfully. Ready for voice confirmation."}
    else:
        app.state.current = "SCAN" # Failed loop
        return {"status": "error", "message": "Scan failed. Please align barcode and try again."}

@app.post("/api/voice")
async def handle_voice_command(body: PickConfirmation):
    """ Receive the normalized command from the middleware flow. """
    expected_commands = get_expected_commands(app.state.current)
    cmd = body.command.upper()
    task = get_current_task()
    
    logger.info(f"Received Voice Command: {cmd} (State: {app.state.current}, Target: PICK {app.state.current_quantity})")

    # Check if the command is even valid for the current state
    if cmd not in expected_commands:
        logger.warning(f"Invalid command {cmd} for state {app.state.current}")
        raise HTTPException(status_code=400, detail=f"Command '{cmd}' not allowed in state {app.state.current}")
    
    if cmd == "CAMERA":
        # UX FIX: Map 'CAMERA' as universal trigger to start the simulation (move to VOICE)
        app.state.current = "VOICE"
        logger.info(f"CAMERA command universally triggered -> Transition to VOICE simulation (QTY: {app.state.current_quantity})")
        return {"status": "success", "action": "enter_simulation", "message": "Simulation started via voice."}
    
    if app.state.current == "VOICE":
        if cmd == f"PICK {app.state.current_quantity}":
            app.state.current = "ADVANCE"
            logger.info(f"Quantity confirmed for {task['material']}. Advancing.")
            asyncio.create_task(advance_task_after_delay(2.0))
            return {"status": "success", "message": "Quantity confirmed.", "advanced": True}
        else:
            logger.warning(f"Incorrect quantity. Expected {app.state.current_quantity}, got {cmd}")
            raise HTTPException(status_code=400, detail=f"Incorrect quantity. Expected {app.state.current_quantity}.")
    
    raise HTTPException(status_code=400, detail="Invalid state transition")

@app.get("/api/reset")
async def reset_state():
    app.state.current = "DISPLAY"
    app.state.task_index = 0
    app.state.current_quantity = random.randint(1, 25)
    logger.info(f"Demo reset. New quantity: {app.state.current_quantity}")
    return {"status": "success", "message": "Demo reset to initial state."}

async def advance_task_after_delay(delay: float):
    await asyncio.sleep(delay)
    app.state.task_index += 1
    app.state.current_quantity = random.randint(1, 25)
    app.state.current = "DISPLAY"
    task = get_current_task()
    logger.info(f"Advanced to next task: {task['material']} with Quantity: {app.state.current_quantity}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("mock_its_mobile:app", host="0.0.0.0", port=8002, reload=True)


