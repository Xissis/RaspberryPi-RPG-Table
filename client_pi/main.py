# client_pi/main.py
import pygame
import sys
import time
import os
from net import start_ws_in_thread, get_state_snapshot

SERVER_WS = "ws://<SERVER_IP>:8080/ws"
SERVER_HTTP = "http://<SERVER_IP>:8080"
SCREEN_W, SCREEN_H = 1280, 720

# cache tokens images
token_images = {}

def draw_token(surface, token):
    x = int(token.get("x", 100))
    y = int(token.get("y", 100))
    image = token.get("image")

    if image:
        if image not in token_images:
            try:
                path = os.path.join("client_pi/cache", image)
                if os.path.exists(path):
                    token_images[image] = pygame.image.load(path).convert_alpha()
            except Exception as e:
                print("Token load error:", e)
                token_images[image] = None
        img = token_images.get(image)
        if img:
            img = pygame.transform.scale(img, (32, 32))
            surface.blit(img, (x-16, y-16))
            return

    # fallback: circle
    pygame.draw.circle(surface, (200, 60, 60), (x, y), 16)
    font = pygame.font.get_default_font()
    f = pygame.font.Font(font, 14)
    txt = f.render(str(token.get("id", "")), True, (255,255,255))
    surface.blit(txt, (x+18, y-8))

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
        if map_path != last_map_path:
            last_map_path = map_path
            if map_path:
                try:
                    map_surface = pygame.image.load(map_path).convert()
                    map_surface = pygame.transform.scale(map_surface, (SCREEN_W, SCREEN_H))
                    print("Loaded map:", map_path)
                except Exception as e:
                    print("Failed to load map:", e)
                    map_surface = None

        if map_surface:
            screen.blit(map_surface, (0,0))
        else:
            screen.fill((20, 30, 20))

        tokens = snapshot.get("tokens", [])
        for t in tokens:
            draw_token(screen, t)

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
