"""Home screen — world / session overview and primary actions."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from ui.theme import COLORS, FONTS
from ui.viewmodels.session_vm import SessionSnapshot
from ui.widgets.status_badge import StatusBadge


class HomeScreen(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        on_host: Callable[[], None],
        on_join: Callable[[], None],
        on_update: Callable[[], None],
        on_details: Callable[[], None],
        **kwargs,
    ):
        super().__init__(master, fg_color=COLORS["bg"], **kwargs)
        self._on_host = on_host
        self._on_join = on_join
        self._on_update = on_update
        self._on_details = on_details

        brand = ctk.CTkLabel(
            self,
            text="BlockSync",
            font=FONTS["brand"],
            text_color=COLORS["accent"],
        )
        brand.pack(pady=(28, 4))

        self._world = ctk.CTkLabel(
            self,
            text="World",
            font=FONTS["title"],
            text_color=COLORS["text"],
        )
        self._world.pack(pady=(12, 0))

        self._version = ctk.CTkLabel(
            self,
            text="World —",
            font=FONTS["body"],
            text_color=COLORS["muted"],
        )
        self._version.pack(pady=(4, 16))

        self._session_badge = StatusBadge(self)
        self._session_badge.pack(pady=(0, 8))

        self._host_label = ctk.CTkLabel(
            self,
            text="",
            font=FONTS["small"],
            text_color=COLORS["muted"],
        )
        self._host_label.pack(pady=(0, 8))

        self._banner = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=10)
        self._banner_title = ctk.CTkLabel(
            self._banner,
            text="",
            font=FONTS["heading"],
            text_color=COLORS["warn"],
            anchor="w",
        )
        self._banner_title.pack(fill="x", padx=14, pady=(12, 4))
        self._banner_body = ctk.CTkLabel(
            self._banner,
            text="",
            font=FONTS["small"],
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
        )
        self._banner_body.pack(fill="x", padx=14, pady=(0, 8))
        self._banner_actions = ctk.CTkFrame(self._banner, fg_color="transparent")
        self._banner_actions.pack(fill="x", padx=14, pady=(0, 12))
        self._update_btn = ctk.CTkButton(
            self._banner_actions,
            text="UPDATE WORLD",
            font=FONTS["small"],
            fg_color=COLORS["accent_dim"],
            hover_color=COLORS["accent"],
            command=self._on_update,
            height=32,
            width=140,
        )
        self._details_btn = ctk.CTkButton(
            self._banner_actions,
            text="VIEW DETAILS",
            font=FONTS["small"],
            fg_color=COLORS["panel_alt"],
            hover_color=COLORS["border"],
            command=self._on_details,
            height=32,
            width=140,
        )

        self._progress = ctk.CTkProgressBar(
            self,
            progress_color=COLORS["accent"],
            fg_color=COLORS["panel_alt"],
        )
        self._progress_label = ctk.CTkLabel(
            self,
            text="",
            font=FONTS["small"],
            text_color=COLORS["muted"],
        )

        self._radmin_badge = StatusBadge(self)
        self._radmin_badge.pack(pady=(8, 4))
        self._radmin_ip = ctk.CTkLabel(
            self,
            text="",
            font=FONTS["mono"],
            text_color=COLORS["muted"],
        )
        self._radmin_ip.pack(pady=(0, 20))

        self._host_btn = ctk.CTkButton(
            self,
            text="HOST WORLD",
            font=FONTS["heading"],
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#102010",
            height=48,
            command=self._on_host,
        )
        self._host_btn.pack(fill="x", padx=48, pady=(8, 10))

        self._join_btn = ctk.CTkButton(
            self,
            text="JOIN SESSION",
            font=FONTS["heading"],
            fg_color=COLORS["panel_alt"],
            hover_color=COLORS["border"],
            text_color=COLORS["text"],
            height=44,
            command=self._on_join,
        )
        self._join_btn.pack(fill="x", padx=48, pady=(0, 16))

        self._toast = ctk.CTkLabel(
            self,
            text="",
            font=FONTS["small"],
            text_color=COLORS["accent"],
        )
        self._toast.pack(pady=(0, 12))

    def apply(self, snap: SessionSnapshot) -> None:
        self._world.configure(text=snap.world_name)
        ver = snap.world_version if snap.world_version is not None else "—"
        self._version.configure(text=f"World v{ver}")

        if snap.status == "active" and snap.host_is_self:
            self._session_badge.set_status("You are hosting", ok=True)
        elif snap.host_name and not snap.host_is_self:
            self._session_badge.set_status("Session active", ok=True)
            self._host_label.configure(text=f"Host: {snap.host_name}")
        elif snap.status == "error":
            self._session_badge.set_status(snap.error or "Error", ok=False)
            self._host_label.configure(text="")
        else:
            self._session_badge.set_status(snap.status_message or "Ready to host", ok=True)
            self._host_label.configure(text="")

        if snap.host_name and not snap.host_is_self and snap.status == "closed":
            self._host_label.configure(text=f"Host: {snap.host_name}")

        # Sync / conflict banners
        self._banner.pack_forget()
        self._update_btn.pack_forget()
        self._details_btn.pack_forget()
        self._progress.pack_forget()
        self._progress_label.pack_forget()

        if snap.busy and snap.download_pct is not None:
            self._progress.set(max(0.0, min(1.0, snap.download_pct / 100.0)))
            self._progress_label.configure(
                text=f"Downloading world… {snap.download_pct}%   World v{snap.remote_version}"
            )
            self._progress.pack(fill="x", padx=48, pady=(0, 4))
            self._progress_label.pack(pady=(0, 8))
        elif snap.sync_result == "NEEDS_UPDATE":
            self._banner_title.configure(text="New world version available.")
            self._banner_body.configure(
                text=f"Local: {snap.local_version}    Shared: {snap.remote_version}"
            )
            self._banner.pack(fill="x", padx=36, pady=(0, 12))
            self._update_btn.pack(side="left", padx=(0, 8))
        elif snap.sync_result in ("CONFLICT", "LOCAL_AHEAD"):
            self._banner_title.configure(text="⚠ World conflict")
            self._banner_body.configure(
                text=(
                    f"Your local world is newer than\nthe shared world.\n\n"
                    f"Local: {snap.local_version}    Shared: {snap.remote_version}\n\n"
                    "Do not overwrite either copy."
                    if snap.sync_result == "LOCAL_AHEAD"
                    else (
                        f"Local and shared worlds have diverged.\n\n"
                        f"Local: {snap.local_version}    Shared: {snap.remote_version}\n\n"
                        "Do not overwrite either copy."
                    )
                )
            )
            self._banner.pack(fill="x", padx=36, pady=(0, 12))
            self._details_btn.pack(side="left")

        if snap.radmin_connected:
            self._radmin_badge.set_status("Radmin VPN  Connected", ok=True)
            self._radmin_ip.configure(text=f"IP: {snap.radmin_ip}" if snap.radmin_ip else "")
        else:
            self._radmin_badge.set_status("Radmin VPN  Not detected", ok=False)
            self._radmin_ip.configure(text=snap.radmin_message or "Install/connect Radmin VPN")

        hosting_busy = snap.busy or snap.status in (
            "starting",
            "saving",
            "snapshotting",
            "uploading",
        )
        conflict = snap.sync_result in ("CONFLICT", "LOCAL_AHEAD")
        foreign = bool(snap.host_name and not snap.host_is_self and snap.status == "closed")

        self._host_btn.configure(
            state="disabled" if hosting_busy or conflict or foreign else "normal"
        )
        self._join_btn.configure(state="normal" if foreign or snap.connection_address else "normal")
        self._update_btn.configure(state="disabled" if hosting_busy else "normal")

        self._toast.configure(text=snap.toast or "")
