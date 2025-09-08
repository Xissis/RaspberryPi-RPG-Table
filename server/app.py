# server/app.py
import os
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from typing import List

ASSETS_DIR = "server/assets"
os.makedirs(ASSETS_DIR, exist_ok=True)

app = FastAPI(title="RPG Table Server (MVP)")

# Serve uploaded maps/tokens as static files at /assets
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.active.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self.lock:
            if websocket in self.active:
                self.active.remove(websocket)

    async def broadcast_json(self, payload):
        text = json.dumps(payload)
        async with self.lock:
            websockets = list(self.active)
        coros = [ws.send_text(text) for ws in websockets]
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)


manager = ConnectionManager()


class GameState:
    def __init__(self):
        self.map_file = None   # filename in server/assets or None
        self.tokens = {}       # id -> {id, x, y, light_radius(optional), owner(optional)}

    def to_dict(self):
        return {
            "map": self.map_file,
            "tokens": list(self.tokens.values())
        }

    def add_token(self, token_id, x=100, y=100, owner=None, light_radius=None, vision=None):
        self.tokens[token_id] = {
            "id": token_id,
            "x": x,
            "y": y,
            **({"owner": owner} if owner is not None else {}),
            **({"light_radius": light_radius} if light_radius is not None else {}),
            **({"vision": vision} if vision is not None else {}),
        }

    def move_token(self, token_id, x, y):
        if token_id in self.tokens:
            self.tokens[token_id]["x"] = x
            self.tokens[token_id]["y"] = y

    def set_map(self, filename):
        self.map_file = filename


state = GameState()


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    # On connect, send full state
    await ws.send_text(json.dumps({"action": "update_state", "data": state.to_dict()}))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            # handle incoming messages (e.g., move_token)
            action = msg.get("action")
            data = msg.get("data", {})
            if action == "move_token":
                tid = data.get("id")
                x = data.get("x")
                y = data.get("y")
                if tid is not None and x is not None and y is not None:
                    state.move_token(tid, int(x), int(y))
                    # broadcast updated state to everyone
                    await manager.broadcast_json({"action": "update_state", "data": state.to_dict()})
            # extendable for more actions
    except WebSocketDisconnect:
        await manager.disconnect(ws)


# Simple GET state for debugging / frontend to poll if needed
@app.get("/state")
async def get_state():
    return JSONResponse(content=state.to_dict())


# Add token via HTTP POST (for MG or scripts)
@app.post("/add_token")
async def add_token(id: str = Form(...), x: int = Form(100), y: int = Form(100), owner: str = Form(None)):
    state.add_token(id, x, y, owner=owner)
    # broadcast new state
    await manager.broadcast_json({"action": "update_state", "data": state.to_dict()})
    return {"status": "ok", "state": state.to_dict()}


# Upload map file (multipart/form-data)
@app.post("/upload_map")
async def upload_map(file: UploadFile = File(...)):
    # save file to assets dir
    save_path = os.path.join(ASSETS_DIR, file.filename)
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)
    # set as current map
    state.set_map(file.filename)
    await manager.broadcast_json({"action": "update_state", "data": state.to_dict()})
    return {"status": "ok", "filename": file.filename}
