from __future__ import annotations

import base64
from typing import Any

from .core import FrameEmulator


class FrameLensOverlay:
    """Transparent always-on-top desktop lens for visual emulator inspection."""

    def __init__(self, emulator: FrameEmulator, scale: int = 1) -> None:
        try:
            import tkinter as tk
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The desktop lens requires Python Tk support. Headless emulator commands still work."
            ) from exc

        self.tk = tk
        self.emulator = emulator
        self.scale = max(1, scale)
        self.root = tk.Tk()
        self.root.title("Frame Emulator Lens")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.82)
        self.root.configure(bg="black")
        self.root.geometry(f"{emulator.display.width * self.scale}x{emulator.display.height * self.scale}+80+80")
        self.canvas = tk.Canvas(
            self.root,
            width=emulator.display.width * self.scale,
            height=emulator.display.height * self.scale,
            highlightthickness=0,
            bg="black",
        )
        self.canvas.pack(fill="both", expand=True)
        self.photo: Any | None = None
        self.root.bind("<Escape>", lambda _: self.root.destroy())
        self.root.bind("t", lambda _: self.emulator.inject_tap())

    def run(self) -> None:
        self._refresh()
        self.root.mainloop()

    def _refresh(self) -> None:
        ppm = self.emulator.display.snapshot_ppm()
        self.photo = self.tk.PhotoImage(data=base64.b64encode(ppm).decode("ascii"))
        if self.scale != 1:
            self.photo = self.photo.zoom(self.scale, self.scale)
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.root.after(100, self._refresh)
