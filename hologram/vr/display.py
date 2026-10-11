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

    Frames arrive at the render resolution as RGBX and are shown without a
    copy; SDL's GPU renderer scales them up to the panels (pygame.SCALED).
    In a window, keys stand in for the helmet's buttons: M = mode,
    SPACE = action, - and = (or keypad - and +) = volume, ESC = quit.
    """

    KEYS = {"m": "mode", "space": "action", "-": "volume_down", "=": "volume_up",
            "[-]": "volume_down", "[+]": "volume_up", "escape": "quit"}

    def __init__(self, render_size: tuple[int, int], windowed: bool = False) -> None:
        if not windowed and "DISPLAY" not in os.environ and "WAYLAND_DISPLAY" not in os.environ:
            os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
        import pygame

        self.pg = pygame
        pygame.display.init()
        flags = pygame.SCALED if windowed else pygame.FULLSCREEN | pygame.SCALED
        try:
            self.screen = pygame.display.set_mode(render_size, flags)
        except pygame.error:                   # no GPU scaling: scale in software instead
            self.screen = pygame.display.set_mode((0, 0) if not windowed else render_size,
                                                  0 if windowed else pygame.FULLSCREEN)
        pygame.display.set_caption("Hologram VR")
        pygame.mouse.set_visible(False)

    def show(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        if frame.shape[2] == 4 and frame.flags["C_CONTIGUOUS"]:
            surf = self.pg.image.frombuffer(frame, (w, h), "RGBX")
        else:
            surf = self.pg.surfarray.make_surface(np.swapaxes(frame[..., :3], 0, 1))
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
