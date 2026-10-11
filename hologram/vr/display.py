"""Output to the headset's display (or a desktop window, or nowhere)."""
from __future__ import annotations

import os
from typing import Protocol

import numpy as np


class Display(Protocol):
    def show(self, frame: np.ndarray) -> None: ...
    def poll_keys(self) -> list[tuple[str, bool]]: ...
    def close(self) -> None: ...


class NullDisplay:
    """No output (headless tests and the demo)."""

    def __init__(self) -> None:
        self.last: np.ndarray | None = None
        self.frames = 0

    def show(self, frame: np.ndarray) -> None:
        self.last = frame
        self.frames += 1

    def poll_keys(self) -> list[tuple[str, bool]]:
        return []

    def close(self) -> None:
        pass


class PygameDisplay:
    """Fullscreen on the Pi (SDL KMS/DRM, no desktop needed) or a window.

    In a window, keys stand in for the helmet's buttons: M = mode,
    SPACE = action, - and = (or keypad - and +) = volume, ESC = quit.
    """

    KEYS = {"m": "mode", "space": "action", "-": "volume_down", "=": "volume_up",
            "[-]": "volume_down", "[+]": "volume_up", "escape": "quit"}

    def __init__(self, size: tuple[int, int], windowed: bool = False) -> None:
        if not windowed and "DISPLAY" not in os.environ and "WAYLAND_DISPLAY" not in os.environ:
            os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
        import pygame

        self.pg = pygame
        pygame.display.init()
        flags = 0 if windowed else pygame.FULLSCREEN
        self.screen = pygame.display.set_mode(size if not windowed else (size[0] // 2, size[1] // 2), flags)
        pygame.display.set_caption("Hologram VR")
        pygame.mouse.set_visible(False)

    def show(self, frame: np.ndarray) -> None:
        surf = self.pg.surfarray.make_surface(np.swapaxes(frame, 0, 1))
        if surf.get_size() != self.screen.get_size():
            surf = self.pg.transform.scale(surf, self.screen.get_size())
        self.screen.blit(surf, (0, 0))
        self.pg.display.flip()

    def poll_keys(self) -> list[tuple[str, bool]]:
        out = []
        for ev in self.pg.event.get():
            if ev.type == self.pg.QUIT:
                out.append(("quit", True))
            elif ev.type in (self.pg.KEYDOWN, self.pg.KEYUP):
                name = self.KEYS.get(self.pg.key.name(ev.key))
                if name:
                    out.append((name, ev.type == self.pg.KEYDOWN))
        return out

    def close(self) -> None:
        self.pg.display.quit()
