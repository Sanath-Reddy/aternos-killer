"""Copy-to-clipboard address control."""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from ui.theme import COLORS, FONTS


class CopyAddress(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        on_copied: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(master, fg_color=COLORS["panel_alt"], corner_radius=8, **kwargs)
        self._address: Optional[str] = None
        self._on_copied = on_copied

        self._addr_label = ctk.CTkLabel(
            self,
            text="—",
            font=FONTS["mono"],
            text_color=COLORS["text"],
            anchor="w",
        )
        self._addr_label.pack(fill="x", padx=14, pady=(12, 6))

        self._btn = ctk.CTkButton(
            self,
            text="COPY ADDRESS",
            font=FONTS["heading"],
            fg_color=COLORS["accent_dim"],
            hover_color=COLORS["accent"],
            text_color=COLORS["text"],
            command=self._copy,
            height=36,
        )
        self._btn.pack(fill="x", padx=14, pady=(0, 12))

    def set_address(self, address: Optional[str]) -> None:
        self._address = address
        self._addr_label.configure(text=address or "No address available")
        self._btn.configure(state="normal" if address else "disabled")

    def _copy(self) -> None:
        if not self._address:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._address)
            self.update()
        except Exception:
            pass
        self._btn.configure(text="COPIED")
        self.after(1600, lambda: self._btn.configure(text="COPY ADDRESS"))
        if self._on_copied:
            self._on_copied()
