# client_pi/net.py
import asyncio
import json
import threading
import websockets
import os
import requests

# shared mutable state updated by net thread, consumed by main thread
shared_state = {
    "map": None,    # local filename or None
    "tokens": [],   # list of tokens
    "map_url": None # remote URL for map (optional)
}
_lock = threading.Lock()

def _set_state_from_server(data, server_base_url=None, cache_dir="client_pi/cache"):
    os.makedirs(cache_dir, exist_ok=True)
    # map: server sends filename in /assets
    map_file = data.get("map")
    with _lock:
        if map_file:
            # if server base url provided, try to download
            if server_base_url:
                url = f"{server_base_url}/assets/{map_file}"
                local_path = os.path.join(cache_dir, map_file)
                if not os.path.exists(local_path):
                    try:
                        resp = requests.get(url, timeout=5)
                        if resp.status_code == 200:
                            with open(local_path, "wb") as f:
                                f.write(resp.content)
                    except Exception as e:
                        print("Failed download map:", e)
                # if downloaded or already existed, set
                if os.path.exists(local_path):
                    shared_state["map"] = local_path
                else:
                    shared_state["map"] = None
            else:
                shared_state["map"] = None
        else:
            shared_state["map"] = None
        shared_state["tokens"] = data.get("tokens", [])

async def _ws_loop(uri, server_http_base=None):
    async with websockets.connect(uri) as ws:
        print("Connected to server websocket:", uri)
        async for message in ws:
            try:
                msg = json.loads(message)
            except Exception:
                continue
            action = msg.get("action")
            data = msg.get("data", {})
            if action == "update_state":
                _set_state_from_server(data, server_base_url=server_http_base)
            # handle other incoming messages here

def start_ws_in_thread(ws_uri: str, server_http_base: str = None):
    # run asyncio websocket loop in background thread
    def runner():
        asyncio.run(_ws_loop(ws_uri, server_http_base))
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t

def get_state_snapshot():
    with _lock:
        return {"map": shared_state["map"], "tokens": list(shared_state["tokens"])}
