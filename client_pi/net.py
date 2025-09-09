# client_pi/net.py
import asyncio
import json
import threading
import websockets
import os
import requests

shared_state = {
    "map": None,
    "tokens": [],
    "scene_id": None,
    "revealed": []
}

_lock = threading.Lock()

def _safe_download(url, local_path, timeout=6):
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    if not os.path.exists(local_path):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(resp.content)
        except Exception as e:
            print("Download error:", e)

def _set_state_from_server(data, server_base_url=None, cache_dir="client_pi/cache"):
    os.makedirs(cache_dir, exist_ok=True)
    active = data.get("active")
    scene = data.get("scene") or {}
    map_file = scene.get("map_file")
    tokens = scene.get("tokens", [])
    revealed = scene.get("revealed", [])

    with _lock:
        shared_state["scene_id"] = active
        shared_state["tokens"] = tokens
        shared_state["revealed"] = revealed

    # download map if present
    if map_file and server_base_url:
        url = f"{server_base_url}/assets/{map_file}"
        local_path = os.path.join(cache_dir, map_file)
        _safe_download(url, local_path)
        if os.path.exists(local_path):
            with _lock:
                shared_state["map"] = local_path
        else:
            with _lock:
                shared_state["map"] = None
    else:
        with _lock:
            shared_state["map"] = None

    # download token images
    if server_base_url:
        for t in tokens:
            img_rel = t.get("image")
            if img_rel:
                url = f"{server_base_url}/assets/{img_rel}"
                local_path = os.path.join(cache_dir, img_rel)
                _safe_download(url, local_path)

    with _lock:
        shared_state["tokens"] = tokens

async def _ws_loop(uri, server_http_base=None):
    while True:
        try:
            async with websockets.connect(uri) as ws:
                print("Connected to server websocket:", uri)
                async for message in ws:
                    try:
                        msg = json.loads(message)
                    except Exception:
                        continue
                    action = msg.get("action")
                    data = msg.get("data", {})
                    if action == "server_state":
                        _set_state_from_server(data, server_base_url=server_http_base)
        except Exception as e:
            print("WS/connect error:", e)
            await asyncio.sleep(2)

def start_ws_in_thread(ws_uri: str, server_http_base: str = None):
    def runner():
        asyncio.run(_ws_loop(ws_uri, server_http_base))
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t

def get_state_snapshot():
    with _lock:
        return {
            "map": shared_state["map"],
            "tokens": list(shared_state["tokens"]),
            "scene_id": shared_state["scene_id"],
            "revealed": list(shared_state["revealed"])
        }
