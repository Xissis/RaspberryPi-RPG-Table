# shared/protocol.py
# Proste helpery do budowania JSON-ów. Użyteczne w kliencie i serwerze.

def make_update_state(data):
    return {"action": "update_state", "data": data}

def make_move_token(token_id, x, y):
    return {"action": "move_token", "data": {"id": token_id, "x": x, "y": y}}
