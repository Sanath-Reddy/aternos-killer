"""Hosting screen — startup progress and active host controls."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from ui.theme import COLORS, FONTS
from ui.viewmodels.session_vm import SessionSnapshot
from ui.widgets.copy_address import CopyAddress
from ui.widgets.progress_steps import ProgressSteps
from ui.widgets.status_badge import StatusBadge


class HostingScreen(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        on_stop: Callable[[], None],
        on_back: Callable[[], None],
        on_view_log: Callable[[], None],
        on_retry: Callable[[], None],
        on_details: Callable[[], None],
        **kwargs,
    ):
        super().__init__(master, fg_color=COLORS["bg"], **kwargs)
        self._on_stop = on_stop
        self._on_back = on_back
        self._on_view_log = on_view_log
        self._on_retry = on_retry
        self._on_details = on_details

        self._title = ctk.CTkLabel(
            self,
            text="Starting…",
            font=FONTS["title"],
            text_color=COLORS["text"],
        )
        self._title.pack(pady=(28, 8))

        self._subtitle = ctk.CTkLabel(
            self,
            text="",
            font=FONTS["body"],
            text_color=COLORS["muted"],
            justify="center",
        )
        self._subtitle.pack(pady=(0, 16))

        self._steps = ProgressSteps(self)
        self._steps.pack(fill="x", padx=48, pady=(0, 16))

        self._server_badge = StatusBadge(self)
        self._server_badge.pack(pady=(4, 4))

        self._radmin_badge = StatusBadge(self)
        self._radmin_badge.pack(pady=(4, 8))

        meta = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=10)
        meta.pack(fill="x", padx=36, pady=(4, 12))
        self._meta = ctk.CTkLabel(
            meta,
            text="",
            font=FONTS["body"],
            text_color=COLORS["muted"],
            justify="left",
            anchor="w",
        )
        self._meta.pack(fill="x", padx=14, pady=12)

        self._copy = CopyAddress(self)
        self._copy.pack(fill="x", padx=36, pady=(0, 12))

        self._stop_btn = ctk.CTkButton(
            self,
            text="STOP & SAVE",
            font=FONTS["heading"],
            fg_color=COLORS["danger"],
            hover_color=COLORS["danger_hover"],
            text_color=COLORS["text"],
            height=46,
            command=self._on_stop,
        )
        self._stop_btn.pack(fill="x", padx=48, pady=(8, 8))

        self._error_frame = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=10)
        self._error_title = ctk.CTkLabel(
            self._error_frame,
            text="",
            font=FONTS["heading"],
            text_color=COLORS["danger"],
            anchor="w",
        )
        self._error_title.pack(fill="x", padx=14, pady=(12, 4))
        self._error_body = ctk.CTkLabel(
            self._error_frame,
            text="",
            font=FONTS["small"],
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
        )
        self._error_body.pack(fill="x", padx=14, pady=(0, 8))
        err_actions = ctk.CTkFrame(self._error_frame, fg_color="transparent")
        err_actions.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkButton(
            err_actions,
            text="RETRY",
            width=100,
            command=self._on_retry,
            fg_color=COLORS["accent_dim"],
            hover_color=COLORS["accent"],
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            err_actions,
            text="VIEW DETAILS",
            width=120,
            command=self._on_details,
            fg_color=COLORS["panel_alt"],
            hover_color=COLORS["border"],
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            err_actions,
            text="VIEW LOG",
            width=100,
            command=self._on_view_log,
            fg_color=COLORS["panel_alt"],
            hover_color=COLORS["border"],
        ).pack(side="left")

        self._back_btn = ctk.CTkButton(
            self,
            text="BACK",
            font=FONTS["small"],
            fg_color="transparent",
            hover_color=COLORS["panel_alt"],
            text_color=COLORS["muted"],
            command=self._on_back,
        )
        self._back_btn.pack(pady=(4, 12))

    def apply(self, snap: SessionSnapshot) -> None:
        if snap.status == "active":
            self._title.configure(text="YOU ARE HOSTING")
            self._subtitle.configure(
                text=f"{snap.world_name}    Version {snap.world_version or '—'}"
            )
        elif snap.status in ("saving", "snapshotting", "uploading"):
            self._title.configure(text="Stopping session")
            self._subtitle.configure(text=snap.status_message)
        elif snap.status == "error":
            self._title.configure(text="Hosting failed")
            self._subtitle.configure(text="")
        else:
            self._title.configure(text=f"Starting {snap.world_name}")
            self._subtitle.configure(text=snap.status_message or "Starting server…")

        self._steps.set_steps(snap.progress_steps)

        online = snap.server_status == "online" or snap.status == "active"
        self._server_badge.set_status(
            f"Server: {snap.server_status.upper()}",
            ok=True if online else (False if snap.server_status == "crashed" else None),
        )
        self._radmin_badge.set_status(
            "Radmin VPN  Connected" if snap.radmin_connected else "Radmin VPN  Not detected",
            ok=snap.radmin_connected,
        )

        lines = [
            f"Radmin VPN: {snap.radmin_ip or '—'}",
            f"Minecraft: {snap.server_port}",
        ]
        if snap.connection_address:
            lines.append(f"Connection: {snap.connection_address}")
        self._meta.configure(text="\n".join(lines))
        self._copy.set_address(snap.connection_address)

        stopping = snap.status in ("saving", "snapshotting", "uploading") or snap.busy
        can_stop = snap.status == "active" and not snap.busy
        self._stop_btn.configure(state="normal" if can_stop else "disabled")
        if stopping:
            self._stop_btn.configure(text="SAVING…")
        else:
            self._stop_btn.configure(text="STOP & SAVE")

        if snap.status == "error" or (snap.error and snap.error_type == "RadminUnavailable"):
            self._error_frame.pack(fill="x", padx=36, pady=(4, 8))
            self._error_title.configure(text=snap.error or "Error")
            # Show friendly body without forcing raw stack by default
            detail = (snap.error_detail or "").split("\n\n")[0]
            self._error_body.configure(text=detail)
        else:
            self._error_frame.pack_forget()

        self._back_btn.configure(
            state="normal" if snap.status in ("closed", "error") and not snap.busy else "disabled"
        )
