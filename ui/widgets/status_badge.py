"""Status badge widget — connected / offline / hosting indicators."""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import COLORS, FONTS


class StatusBadge(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._dot = ctk.CTkLabel(
            self,
            text="●",
            font=FONTS["body"],
            text_color=COLORS["offline"],
            width=18,
        )
        self._dot.pack(side="left")
        self._label = ctk.CTkLabel(
            self,
            text="",
            font=FONTS["body"],
            text_color=COLORS["text"],
            anchor="w",
        )
        self._label.pack(side="left", padx=(4, 0))

    def set_status(self, text: str, *, ok: bool | None = None) -> None:
        if ok is True:
            color = COLORS["ok"]
        elif ok is False:
            color = COLORS["danger"]
        else:
            color = COLORS["warn"]
        self._dot.configure(text_color=color)
        self._label.configure(text=text)
