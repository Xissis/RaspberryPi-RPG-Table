# server/app.py
import os
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import List

ASSETS_DIR = "server/assets"
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(os.path.join(ASSETS_DIR, "tokens"), exist_ok=True)

app = FastAPI(title="RPG Table Server")

# Serving assets
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
        self.map_file = None   # map file in /assets
        self.tokens = {}       # id -> dict

    def to_dict(self):
        return {
            "map": self.map_file,
            "tokens": list(self.tokens.values())
        }

    def add_token(self, token_id, x=100, y=100, owner=None, image=None):
        self.tokens[token_id] = {
            "id": token_id,
            "x": x,
            "y": y,
            **({"owner": owner} if owner else {}),
            **({"image": image} if image else {}),
        }

    def move_token(self, token_id, x, y):
        if token_id in self.tokens:
            self.tokens[token_id]["x"] = x
            self.tokens[token_id]["y"] = y

    def set_map(self, filename):
        self.map_file = filename


state = GameState()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    await ws.send_text(json.dumps({"action": "update_state", "data": state.to_dict()}))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            action = msg.get("action")
            data = msg.get("data", {})
            if action == "move_token":
                tid = data.get("id")
                x = data.get("x")
                y = data.get("y")
                if tid is not None and x is not None and y is not None:
                    state.move_token(tid, int(x), int(y))
                    await manager.broadcast_json({"action": "update_state", "data": state.to_dict()})
    except WebSocketDisconnect:
        await manager.disconnect(ws)


@app.get("/state")
async def get_state():
    return JSONResponse(content=state.to_dict())


@app.post("/add_token")
async def add_token(id: str = Form(...), x: int = Form(100), y: int = Form(100), owner: str = Form(None)):
    state.add_token(id, x, y, owner=owner)
    await manager.broadcast_json({"action": "update_state", "data": state.to_dict()})
    return {"status": "ok", "state": state.to_dict()}


@app.post("/upload_map")
async def upload_map(file: UploadFile = File(...)):
    save_path = os.path.join(ASSETS_DIR, file.filename)
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)
    state.set_map(file.filename)
    await manager.broadcast_json({"action": "update_state", "data": state.to_dict()})
    return {"status": "ok", "filename": file.filename}


@app.post("/upload_token")
async def upload_token(file: UploadFile = File(...), id: str = Form(...), x: int = Form(100), y: int = Form(100)):
    token_dir = os.path.join(ASSETS_DIR, "tokens")
    os.makedirs(token_dir, exist_ok=True)
    save_path = os.path.join(token_dir, file.filename)
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    state.add_token(id, x, y, image=f"tokens/{file.filename}")
    await manager.broadcast_json({"action": "update_state", "data": state.to_dict()})
    return {"status": "ok", "filename": file.filename}


# UI MG
@app.get("/mg")
async def mg_ui():
    return FileResponse("server/static/mg/index.html")
