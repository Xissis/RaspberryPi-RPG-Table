# server/app.py
import os
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Optional

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
SCENES_FILE = os.path.join(BASE_DIR, "scenes.json")

os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(os.path.join(ASSETS_DIR, "tokens"), exist_ok=True)
os.makedirs(os.path.join(ASSETS_DIR, "maps"), exist_ok=True)

app = FastAPI(title="RPG Table Server - Scenes & MG")

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
        if not websockets:
            return
        coros = [ws.send_text(text) for ws in websockets]
        await asyncio.gather(*coros, return_exceptions=True)


manager = ConnectionManager()


class SceneManager:
    def __init__(self):
        self.scenes = {}  # id -> { map_file, tokens: {id:...}, revealed: [] }
        self.active_scene: Optional[str] = None
        self._load()

    def _load(self):
        if os.path.exists(SCENES_FILE):
            try:
                with open(SCENES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.scenes = data.get("scenes", {})
                self.active_scene = data.get("active")
            except Exception as e:
                print("Failed to load scenes file:", e)
                self.scenes = {}
                self.active_scene = None

    def _save(self):
        try:
            with open(SCENES_FILE, "w", encoding="utf-8") as f:
                json.dump({"scenes": self.scenes, "active": self.active_scene}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("Failed to save scenes file:", e)

    def create_scene(self, scene_id, map_file=None):
        if scene_id in self.scenes:
            raise ValueError("Scene already exists")
        self.scenes[scene_id] = {
            "map_file": map_file,
            "tokens": {},        # id -> token dict
            "revealed": []      # optional list of {x,y,r}
        }
        # if first scene, make active
        if not self.active_scene:
            self.active_scene = scene_id
        self._save()

    def delete_scene(self, scene_id):
        if scene_id in self.scenes:
            del self.scenes[scene_id]
            if self.active_scene == scene_id:
                self.active_scene = next(iter(self.scenes), None)
            self._save()

    def set_active(self, scene_id):
        if scene_id not in self.scenes:
            raise ValueError("Scene not found")
        self.active_scene = scene_id
        self._save()

    def get_active(self):
        if not self.active_scene:
            return None
        return self.scenes[self.active_scene]

    def list_scenes_meta(self):
        return {sid: {"map_file": s["map_file"]} for sid, s in self.scenes.items()}

    # token operations operate within a scene
    def add_token(self, scene_id, token_id, x=100, y=100, owner=None, image=None, vision: Optional[int]=None, light_radius: Optional[int]=None):
        sc = self.scenes.get(scene_id)
        if sc is None:
            raise ValueError("Scene not found")
        sc["tokens"][token_id] = {
            "id": token_id,
            "x": int(x),
            "y": int(y),
            **({"owner": owner} if owner else {}),
            **({"image": image} if image else {}),
            **({"vision": int(vision)} if vision not in (None, "",) else {}),
            **({"light_radius": int(light_radius)} if light_radius not in (None, "",) else {}),
        }
        self._save()

    def move_token(self, scene_id, token_id, x, y):
        sc = self.scenes.get(scene_id)
        if sc and token_id in sc["tokens"]:
            sc["tokens"][token_id]["x"] = int(x)
            sc["tokens"][token_id]["y"] = int(y)
            self._save()

    def set_map(self, scene_id, filename):
        sc = self.scenes.get(scene_id)
        if sc is None:
            raise ValueError("Scene not found")
        sc["map_file"] = filename
        self._save()

    def reveal_area(self, scene_id, x, y, r):
        sc = self.scenes.get(scene_id)
        if sc is None:
            raise ValueError("Scene not found")
        sc["revealed"].append({"x": int(x), "y": int(y), "r": int(r)})
        self._save()

    def to_active_dict(self):
        """Return the active scene data in serializable form."""
        if not self.active_scene:
            return {"active": None, "scene": None, "scenes": self.list_scenes_meta()}
        sc = self.get_active()
        return {
            "active": self.active_scene,
            "scene": {
                "id": self.active_scene,
                "map_file": sc.get("map_file"),
                "tokens": list(sc.get("tokens", {}).values()),
                "revealed": sc.get("revealed", []),
            },
            "scenes": self.list_scenes_meta()
        }


scenes = SceneManager()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    # send full server scene state on connect
    await ws.send_text(json.dumps({"action": "server_state", "data": scenes.to_active_dict()}))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            action = msg.get("action")
            data = msg.get("data", {})
            # move_token (expects id,x,y; optionally scene)
            if action == "move_token":
                scene_id = data.get("scene") or scenes.active_scene
                tid = data.get("id")
                x = data.get("x")
                y = data.get("y")
                if scene_id and tid is not None and x is not None and y is not None:
                    scenes.move_token(scene_id, tid, x, y)
                    await manager.broadcast_json({"action": "server_state", "data": scenes.to_active_dict()})
            # reveal area (optionally used by MG to persist fog reveals)
            if action == "reveal":
                scene_id = data.get("scene") or scenes.active_scene
                x = data.get("x"); y = data.get("y"); r = data.get("r")
                if scene_id and x is not None and y is not None and r is not None:
                    scenes.reveal_area(scene_id, x, y, r)
                    await manager.broadcast_json({"action": "server_state", "data": scenes.to_active_dict()})
            # add other ws actions as needed
    except WebSocketDisconnect:
        await manager.disconnect(ws)


@app.get("/state")
async def get_state():
    return JSONResponse(content=scenes.to_active_dict())


@app.post("/create_scene")
async def create_scene(name: str = Form(...), file: UploadFile = File(None)):
    # create scene and optionally save map file
    if name in scenes.scenes:
        return JSONResponse({"status": "error", "msg": "scene exists"}, status_code=400)
    map_filename = None
    if file:
        maps_dir = os.path.join(ASSETS_DIR, "maps")
        os.makedirs(maps_dir, exist_ok=True)
        map_filename = os.path.join("maps", file.filename)
        save_path = os.path.join(ASSETS_DIR, map_filename)
        with open(save_path, "wb") as f:
            content = await file.read()
            f.write(content)
    scenes.create_scene(name, map_file=map_filename)
    await manager.broadcast_json({"action": "server_state", "data": scenes.to_active_dict()})
    return {"status": "ok", "scene": name}


@app.post("/switch_scene")
async def switch_scene(scene: str = Form(...)):
    try:
        scenes.set_active(scene)
    except Exception as e:
        return JSONResponse({"status": "error", "msg": str(e)}, status_code=400)
    await manager.broadcast_json({"action": "server_state", "data": scenes.to_active_dict()})
    return {"status": "ok", "active": scene}


@app.get("/scenes")
async def list_scenes():
    return JSONResponse(content=scenes.list_scenes_meta())


@app.post("/upload_map")
async def upload_map(file: UploadFile = File(...), scene: str = Form(None)):
    # target scene is specified or active
    scene_id = scene or scenes.active_scene
    if not scene_id:
        return JSONResponse({"status": "error", "msg": "no active scene"}, status_code=400)
    maps_dir = os.path.join(ASSETS_DIR, "maps")
    os.makedirs(maps_dir, exist_ok=True)
    map_filename = os.path.join("maps", file.filename)
    save_path = os.path.join(ASSETS_DIR, map_filename)
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)
    scenes.set_map(scene_id, map_filename)
    await manager.broadcast_json({"action": "server_state", "data": scenes.to_active_dict()})
    return {"status": "ok", "filename": map_filename, "scene": scene_id}


@app.post("/upload_token")
async def upload_token(
    file: UploadFile = File(...),
    id: str = Form(...),
    x: int = Form(100),
    y: int = Form(100),
    owner: str = Form(None),
    vision: int = Form(None),
    light_radius: int = Form(None),
    scene: str = Form(None),
):
    scene_id = scene or scenes.active_scene
    if not scene_id:
        return JSONResponse({"status": "error", "msg": "no active scene"}, status_code=400)
    token_dir = os.path.join(ASSETS_DIR, "tokens")
    os.makedirs(token_dir, exist_ok=True)
    save_rel = os.path.join("tokens", file.filename)
    save_path = os.path.join(ASSETS_DIR, save_rel)
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)
    scenes.add_token(scene_id, id, x, y, owner=owner, image=save_rel, vision=vision, light_radius=light_radius)
    await manager.broadcast_json({"action": "server_state", "data": scenes.to_active_dict()})
    return {"status": "ok", "filename": save_rel, "scene": scene_id}


@app.post("/add_token")
async def add_token(
    id: str = Form(...),
    x: int = Form(100),
    y: int = Form(100),
    owner: str = Form(None),
    image: str = Form(None),
    vision: int = Form(None),
    light_radius: int = Form(None),
    scene: str = Form(None),
):
    scene_id = scene or scenes.active_scene
    if not scene_id:
        return JSONResponse({"status": "error", "msg": "no active scene"}, status_code=400)
    scenes.add_token(scene_id, id, x, y, owner=owner, image=image, vision=vision, light_radius=light_radius)
    await manager.broadcast_json({"action": "server_state", "data": scenes.to_active_dict()})
    return {"status": "ok", "scene": scene_id}


# UI MG
@app.get("/mg")
async def mg_ui():
    return FileResponse(os.path.join(BASE_DIR, "static", "mg", "index.html"))
