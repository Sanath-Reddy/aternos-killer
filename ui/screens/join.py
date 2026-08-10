"""Join screen — active session connection info for non-hosts."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from ui.theme import COLORS, FONTS
from ui.viewmodels.session_vm import SessionSnapshot
from ui.widgets.copy_address import CopyAddress
from ui.widgets.status_badge import StatusBadge


class JoinScreen(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        on_back: Callable[[], None],
        on_join: Callable[[], None],
        **kwargs,
    ):
        super().__init__(master, fg_color=COLORS["bg"], **kwargs)
        self._on_back = on_back
        self._on_join = on_join

        ctk.CTkLabel(
            self,
            text="Active Session",
            font=FONTS["title"],
            text_color=COLORS["text"],
        ).pack(pady=(28, 16))

        card = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=10)
        card.pack(fill="x", padx=36, pady=(0, 12))

        self._info = ctk.CTkLabel(
            card,
            text="",
            font=FONTS["body"],
            text_color=COLORS["muted"],
            justify="left",
            anchor="w",
        )
        self._info.pack(fill="x", padx=16, pady=16)

        self._radmin_badge = StatusBadge(self)
        self._radmin_badge.pack(pady=(4, 4))
        self._server_badge = StatusBadge(self)
        self._server_badge.pack(pady=(0, 12))

        self._copy = CopyAddress(self)
        self._copy.pack(fill="x", padx=36, pady=(0, 12))

        self._hint = ctk.CTkLabel(
            self,
            text=(
                "Open Minecraft → Multiplayer → Direct Connection\n"
                "and paste the address above."
            ),
            font=FONTS["small"],
            text_color=COLORS["muted"],
            justify="center",
        )
        self._hint.pack(pady=(4, 12))

        self._join_btn = ctk.CTkButton(
            self,
            text="JOIN",
            font=FONTS["heading"],
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#102010",
            height=46,
            command=self._on_join,
        )
        self._join_btn.pack(fill="x", padx=48, pady=(4, 8))

        ctk.CTkButton(
            self,
            text="BACK",
            font=FONTS["small"],
            fg_color="transparent",
            hover_color=COLORS["panel_alt"],
            text_color=COLORS["muted"],
            command=self._on_back,
        ).pack(pady=(4, 12))

        self._toast = ctk.CTkLabel(
            self,
            text="",
            font=FONTS["small"],
            text_color=COLORS["accent"],
        )
        self._toast.pack()

    def apply(self, snap: SessionSnapshot) -> None:
        host = snap.host_name or "Unknown"
        lines = [
            f"Host: {host}",
            f"World: {snap.world_name}",
            f"Version: {snap.world_version if snap.world_version is not None else '—'}",
        ]
        if snap.connection_address:
            lines.append(f"\nAddress: {snap.connection_address}")
        else:
            lines.append(
                "\nAsk the host to share their BlockSync address "
                "(Radmin IP + port)."
            )
        self._info.configure(text="\n".join(lines))

        self._radmin_badge.set_status(
            "Radmin: Connected" if snap.radmin_connected else "Radmin: Not detected",
            ok=snap.radmin_connected,
        )
        # Joiner doesn't run the server locally; treat foreign lock as online session.
        foreign_active = bool(snap.host_name and not snap.host_is_self)
        self._server_badge.set_status(
            "Server: Online" if foreign_active else f"Server: {snap.server_status}",
            ok=True if foreign_active else None,
        )
        self._copy.set_address(snap.connection_address)
        self._join_btn.configure(
            state="normal" if snap.connection_address else "disabled"
        )
        self._toast.configure(text=snap.toast or "")
