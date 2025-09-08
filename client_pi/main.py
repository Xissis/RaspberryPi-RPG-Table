# client_pi/main.py
import pygame
import sys
import time
from net import start_ws_in_thread, get_state_snapshot

# KONFIG:
SERVER_WS = "ws://<SERVER_IP>:8000/ws"   # <-- zmień <SERVER_IP> na IP serwera z PC
SERVER_HTTP = "http://<SERVER_IP>:8000" # służy do pobierania plików w /assets
SCREEN_W, SCREEN_H = 1280, 720

def draw_token(surface, token):
    x = int(token.get("x", 100))
    y = int(token.get("y", 100))
    pygame.draw.circle(surface, (200, 60, 60), (x, y), 16)
    # id label
    font = pygame.font.get_default_font()
    f = pygame.font.Font(font, 14)
    txt = f.render(str(token.get("id", "")), True, (255,255,255))
    surface.blit(txt, (x+18, y-8))

def main():
    # start websocket background thread
    print("Starting WS client...")
    start_ws_in_thread(SERVER_WS, server_http_base=SERVER_HTTP)

    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("RPG Table - Pi Client (MVP)")
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
                    # scale to screen if needed
                    map_surface = pygame.transform.scale(map_surface, (SCREEN_W, SCREEN_H))
                    print("Loaded map:", map_path)
                except Exception as e:
                    print("Failed to load map:", e)
                    map_surface = None

        # draw
        if map_surface:
            screen.blit(map_surface, (0,0))
        else:
            screen.fill((20, 30, 20))

        # draw tokens
        tokens = snapshot.get("tokens", [])
        for t in tokens:
            draw_token(screen, t)

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
