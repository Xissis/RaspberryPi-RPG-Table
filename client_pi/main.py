# client_pi/main.py
import pygame
import sys
import os
from net import start_ws_in_thread, get_state_snapshot

# KONFIG:
SERVER_WS = "ws://<SERVER_IP>:8000/ws"   # <-- zmień na IP serwera
SERVER_HTTP = "http://<SERVER_IP>:8000"  # <-- zmień na IP serwera
SCREEN_W, SCREEN_H = 1280, 720
FOG_ALPHA = 220  # 0-255 - gęstość mgły (większe = ciemniej)

token_images = {}

def load_token_image_if_any(token):
    image_rel = token.get("image")
    if not image_rel:
        return None
    path = os.path.join("client_pi/cache", image_rel)
    if image_rel not in token_images:
        if os.path.exists(path):
            try:
                token_images[image_rel] = pygame.image.load(path).convert_alpha()
            except Exception as e:
                print("Token load error:", e)
                token_images[image_rel] = None
        else:
            token_images[image_rel] = None
    return token_images.get(image_rel)

def draw_token(surface, token):
    x = int(token.get("x", 100))
    y = int(token.get("y", 100))
    img = load_token_image_if_any(token)
    if img:
        img_scaled = pygame.transform.smoothscale(img, (32, 32))
        surface.blit(img_scaled, (x-16, y-16))
    else:
        pygame.draw.circle(surface, (200, 60, 60), (x, y), 16)
        font = pygame.font.Font(pygame.font.get_default_font(), 14)
        txt = font.render(str(token.get("id", "")), True, (255,255,255))
        surface.blit(txt, (x+18, y-8))

def make_radial_gradient(radius, alpha=FOG_ALPHA):
    """Tworzy Surface z radialnym gradientem (przezroczysty w centrum, ciemny na krawędzi)."""
    surf = pygame.Surface((radius*2, radius*2), pygame.SRCALPHA)
    for r in range(radius, 0, -1):
        a = int(alpha * (r / radius))  # od 0 w centrum do alpha na krawędzi
        pygame.draw.circle(surf, (0, 0, 0, a), (radius, radius), r)
    return surf

def apply_fog_of_war(surface, tokens, revealed):
    fog = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    fog.fill((0,0,0,FOG_ALPHA))

    # stałe odsłonięte obszary (jeśli w przyszłości net.py będzie zwracał "revealed")
    for rv in revealed or []:
        r = rv.get("r", 0)
        if r > 0:
            grad = make_radial_gradient(r)
            fog.blit(grad, (rv["x"]-r, rv["y"]-r), special_flags=pygame.BLEND_RGBA_MIN)

    # dynamiczne światło i wizja graczy
    for t in tokens:
        if t.get("owner") != "player":
            continue
        for key in ["vision", "light_radius"]:
            r = t.get(key)
            if r and r > 0:
                grad = make_radial_gradient(r)
                fog.blit(grad, (t["x"]-r, t["y"]-r), special_flags=pygame.BLEND_RGBA_MIN)

    surface.blit(fog, (0,0))

def main():
    print("Starting WS client...")
    start_ws_in_thread(SERVER_WS, server_http_base=SERVER_HTTP)

    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("RPG Table - Pi Client")
    clock = pygame.time.Clock()

    map_surface = None
    last_map_path = None

    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False

        snapshot = get_state_snapshot()
        map_path = snapshot.get("map")
        tokens = snapshot.get("tokens", [])
        revealed = []  # (na przyszłość: można dodać do net.py)

        # reload map if changed
        if map_path != last_map_path:
            last_map_path = map_path
            if map_path:
                try:
                    map_surface = pygame.image.load(map_path).convert()
                    map_surface = pygame.transform.smoothscale(map_surface, (SCREEN_W, SCREEN_H))
                    print("Loaded map:", map_path)
                except Exception as e:
                    print("Failed to load map:", e)
                    map_surface = None

        if map_surface:
            screen.blit(map_surface, (0,0))
        else:
            screen.fill((20,30,20))

        # draw tokens
        for t in tokens:
            draw_token(screen, t)

        # apply fog & lighting
        revealed = snapshot.get("revealed", [])
        apply_fog_of_war(screen, tokens, revealed)


        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
