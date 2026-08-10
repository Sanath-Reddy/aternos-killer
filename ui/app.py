"""
ui/app.py — BlockSync CustomTkinter application shell and screen router.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Optional

import customtkinter as ctk

from ui.app_services import AppServices, build_app_services
from ui.screens.error_dialog import show_details, show_log
from ui.screens.home import HomeScreen
from ui.screens.hosting import HostingScreen
from ui.screens.join import JoinScreen
from ui.theme import COLORS, WINDOW
from ui.viewmodels.session_vm import SessionSnapshot, SessionViewModel

logger = logging.getLogger(__name__)


class BlockSyncApp(ctk.CTk):
    def __init__(self, services: AppServices):
        super().__init__()
        self.services = services
        self.vm: SessionViewModel = services.view_model

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")

        self.title(WINDOW["title"])
        self.geometry(WINDOW["geometry"])
        self.minsize(*WINDOW["min_size"])
        self.configure(fg_color=COLORS["bg"])

        self._container = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        self._container.pack(fill="both", expand=True)

        self.home = HomeScreen(
            self._container,
            on_host=self._on_host,
            on_join=self._show_join,
            on_update=self.vm.update_world,
            on_details=self._on_conflict_details,
        )
        self.hosting = HostingScreen(
            self._container,
            on_stop=self.vm.stop_and_save,
            on_back=self._show_home,
            on_view_log=self._on_view_log,
            on_retry=self._on_retry,
            on_details=self._on_error_details,
        )
        self.join = JoinScreen(
            self._container,
            on_back=self._show_home,
            on_join=self._on_join_copy,
        )

        self._current: Optional[ctk.CTkFrame] = None
        self._show_home()

        self.vm.add_listener(self._on_snapshot)
        self.after(2000, self._poll_refresh)

        mode = services.mode
        self.title(f"{WINDOW['title']} ({mode})")

    # ── Navigation ────────────────────────────────────────────────────────────

    def _show(self, screen: ctk.CTkFrame) -> None:
        if self._current is not None:
            self._current.pack_forget()
        self._current = screen
        screen.pack(fill="both", expand=True)

    def _show_home(self) -> None:
        self._show(self.home)

    def _show_hosting(self) -> None:
        self._show(self.hosting)

    def _show_join(self) -> None:
        self._show(self.join)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_host(self) -> None:
        snap = self.vm.snapshot
        if snap.host_name and not snap.host_is_self:
            self._show_join()
            return
        self._show_hosting()
        self.vm.host_world()

    def _on_join_copy(self) -> None:
        address = self.vm.copy_address_text()
        if not address:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(address)
            self.update()
        except tk.TclError:
            pass
        self.vm._update(toast="Address copied — paste in Minecraft Multiplayer.")

    def _on_retry(self) -> None:
        self.vm.retry()
        snap = self.vm.snapshot
        if snap.status == "closed":
            self._show_home()

    def _on_view_log(self) -> None:
        show_log(self, self.vm.get_log_tail())

    def _on_error_details(self) -> None:
        snap = self.vm.snapshot
        show_details(
            self,
            title="Error details",
            body=snap.error_detail or snap.error or "(no details)",
        )

    def _on_conflict_details(self) -> None:
        snap = self.vm.snapshot
        body = (
            f"Sync result: {snap.sync_result}\n"
            f"Local version: {snap.local_version}\n"
            f"Shared version: {snap.remote_version}\n\n"
            "BlockSync will not overwrite either copy.\n"
            "Resolve manually with your group, then retry."
        )
        show_details(self, title="World conflict", body=body)

    # ── State binding ─────────────────────────────────────────────────────────

    def _on_snapshot(self, snap: SessionSnapshot) -> None:
        # Marshal onto UI thread.
        self.after(0, lambda s=snap: self._apply_snapshot(s))

    def _apply_snapshot(self, snap: SessionSnapshot) -> None:
        self.home.apply(snap)
        self.hosting.apply(snap)
        self.join.apply(snap)

        # Auto-route based on session lifecycle.
        if snap.error_type == "lock_conflict":
            self._show_join()
            return

        if snap.status in ("starting", "active", "saving", "snapshotting", "uploading"):
            if self._current is not self.hosting:
                self._show_hosting()
        elif snap.status == "error":
            if self._current is self.home:
                self._show_hosting()
        elif snap.status == "closed" and not snap.busy:
            if self._current is self.hosting and not snap.error:
                # After successful STOP & SAVE, return home.
                self._show_home()

        if snap.toast:
            self.after(3500, self.vm.clear_toast)

    def _poll_refresh(self) -> None:
        try:
            self.vm.refresh()
        except Exception as exc:
            logger.debug("poll refresh: %s", exc)
        self.after(2000, self._poll_refresh)


def run_app(services: Optional[AppServices] = None) -> None:
    services = services or build_app_services()
    app = BlockSyncApp(services)
    app.mainloop()
