"""
ui/viewmodels/session_vm.py — Aggregates core + network state for screens.

UI widgets bind to SessionViewModel only — never to Drive, filesystem, or
Minecraft process internals.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from network.manager import NetworkManager

logger = logging.getLogger(__name__)

DEFAULT_SERVER_PORT = 25565

FRIENDLY_ERRORS = {
    "lock_conflict": (
        "Someone is already hosting.",
        "Join their session instead of starting a second host.",
    ),
    "StorageUnavailableError": (
        "Cannot reach shared world storage.",
        "Your local world has not been deleted.",
    ),
    "WorldConflictError": (
        "World conflict",
        "Your local world and the shared world have diverged. "
        "Do not overwrite either copy.",
    ),
    "LocalWorldAheadError": (
        "World conflict",
        "Your local world is newer than the shared world. "
        "Do not overwrite either copy.",
    ),
    "SessionError": (
        "Minecraft could not be started.",
        "Check the server log, then retry.",
    ),
}


@dataclass
class SessionSnapshot:
    status: str = "closed"
    world_name: str = "World"
    world_version: Optional[int] = None
    local_version: Optional[int] = None
    remote_version: Optional[int] = None
    sync_result: str = "UNKNOWN"
    host_name: Optional[str] = None
    host_is_self: bool = False
    server_status: str = "offline"
    server_port: int = DEFAULT_SERVER_PORT
    radmin_connected: bool = False
    radmin_ip: Optional[str] = None
    radmin_message: str = ""
    connection_address: Optional[str] = None
    error: Optional[str] = None
    error_detail: Optional[str] = None
    error_type: Optional[str] = None
    progress_steps: List[Dict[str, str]] = field(default_factory=list)
    busy: bool = False
    status_message: str = ""
    download_pct: Optional[int] = None
    toast: Optional[str] = None


Listener = Callable[[SessionSnapshot], None]


class SessionViewModel:
    """Presentation model consumed by Home / Hosting / Join screens."""

    def __init__(
        self,
        session_svc: Any,
        world_svc: Any,
        mc_svc: Any,
        network: NetworkManager,
        *,
        local_host_id: str = "",
        server_port: int = DEFAULT_SERVER_PORT,
    ) -> None:
        self._session = session_svc
        self._world = world_svc
        self._mc = mc_svc
        self._network = network
        self._local_host_id = local_host_id
        self._server_port = server_port

        self._listeners: List[Listener] = []
        self._lock = threading.RLock()
        self._snap = SessionSnapshot(server_port=server_port)
        self._last_error_type: Optional[str] = None
        self._last_error_raw: Optional[str] = None

        if hasattr(self._session, "add_state_observer"):
            self._session.add_state_observer(self._on_state_change)

        self.refresh()

    # ── Subscriptions ─────────────────────────────────────────────────────────

    def add_listener(self, callback: Listener) -> None:
        self._listeners.append(callback)
        callback(self.snapshot)

    @property
    def snapshot(self) -> SessionSnapshot:
        with self._lock:
            return SessionSnapshot(**self._snap.__dict__)

    def _emit(self) -> None:
        snap = self.snapshot
        for cb in list(self._listeners):
            try:
                cb(snap)
            except Exception as exc:
                logger.debug("UI listener error: %s", exc)

    def _update(self, **kwargs: Any) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self._snap, key, value)
        self._emit()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        try:
            status = self._session.get_state()
            lock = self._session.get_lock_info()
            compare = self._world.compare_versions()
            local_m = self._world.get_local_manifest()
            remote_m = self._world.get_remote_manifest()
            server_status = self._mc.get_status()
            net = self._network.get_network_status()
        except Exception as exc:
            logger.error("refresh failed: %s", exc, exc_info=True)
            self._update(
                error="Something went wrong.",
                error_detail=str(exc),
                error_type=type(exc).__name__,
                status_message="Unable to refresh status.",
            )
            return

        world_name = (
            (local_m or remote_m or {}).get("world_id")
            or "World"
        )
        if isinstance(world_name, str):
            world_name = world_name.replace("-", " ").replace("_", " ").title()

        local_v = compare.get("local_version")
        remote_v = compare.get("remote_version")
        display_v = remote_v if remote_v is not None else local_v

        host_name = None
        host_is_self = False
        if lock:
            host_name = lock.get("host_id")
            if self._local_host_id and host_name == self._local_host_id:
                host_is_self = True
            # Mock self host id
            if host_name and str(host_name).endswith("-mock") and "you" in str(host_name):
                host_is_self = True

        radmin_ip = net.ip
        address = None
        if radmin_ip:
            address = f"{radmin_ip}:{self._server_port}"
        elif lock and not host_is_self and status == "closed":
            # Joiner may not have local Radmin IP for the host; still show port hint.
            address = None

        # For join screen: if foreign host, connection uses host's Radmin IP —
        # V1 only knows local Radmin IP. Show local detection + port; host shares address.
        if status == "active" and radmin_ip:
            address = f"{radmin_ip}:{self._server_port}"

        steps = self._steps_for(status)
        status_message = self._message_for(status, compare.get("result", ""))

        download_pct = None
        if hasattr(self._world, "get_download_progress") and getattr(
            self._world, "_downloading", False
        ):
            download_pct = self._world.get_download_progress()

        # Preserve UI-level errors (e.g. Radmin) until retry/clear; session ERROR always wins.
        keep_error = status == "error" or bool(self._snap.error_type)
        self._update(
            status=status,
            world_name=world_name,
            world_version=display_v,
            local_version=local_v,
            remote_version=remote_v,
            sync_result=compare.get("result", "UNKNOWN"),
            host_name=host_name,
            host_is_self=host_is_self,
            server_status=server_status,
            server_port=self._server_port,
            radmin_connected=net.connected,
            radmin_ip=radmin_ip,
            radmin_message=net.message,
            connection_address=address,
            progress_steps=steps,
            status_message=status_message,
            download_pct=download_pct,
            error=self._snap.error if keep_error else None,
            error_detail=self._snap.error_detail if keep_error else None,
            error_type=self._snap.error_type if keep_error else None,
        )

    def _on_state_change(self, old: str, new: str) -> None:
        logger.debug("Session state %s → %s", old, new)
        self.refresh()

    # ── Actions ───────────────────────────────────────────────────────────────

    def host_world(self) -> None:
        if self._snap.busy:
            return
        if not self._network.is_available():
            self._update(
                error="Radmin VPN is not connected.",
                error_detail=self._network.get_network_status().message,
                error_type="RadminUnavailable",
                status_message=(
                    "Other players will not be able to connect until "
                    "Radmin VPN is available."
                ),
            )
            self.refresh()
            return

        self._update(busy=True, error=None, error_detail=None, error_type=None)
        threading.Thread(target=self._run_begin_host, daemon=True).start()

    def _run_begin_host(self) -> None:
        try:
            result = self._session.begin_host()
            if not result.get("ok"):
                self._apply_error_result(result)
            else:
                self._update(
                    busy=False,
                    error=None,
                    error_detail=None,
                    error_type=None,
                    toast="Server is online.",
                )
        except Exception as exc:
            self._apply_error_result(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "state": "error",
                }
            )
        finally:
            self._update(busy=False)
            self.refresh()

    def stop_and_save(self) -> None:
        if self._snap.busy:
            return
        self._update(busy=True, error=None, error_detail=None, error_type=None)
        threading.Thread(target=self._run_end_host, daemon=True).start()

    def _run_end_host(self) -> None:
        try:
            result = self._session.end_host()
            if not result.get("ok"):
                self._apply_error_result(result)
            else:
                version = result.get("version")
                self._update(
                    busy=False,
                    toast=f"World saved (v{version})." if version else "World saved.",
                    error=None,
                    error_detail=None,
                    error_type=None,
                )
        except Exception as exc:
            self._apply_error_result(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "state": "error",
                }
            )
        finally:
            self._update(busy=False)
            self.refresh()

    def update_world(self) -> None:
        """Download shared world without hosting (mock or future WorldService API)."""
        if self._snap.busy:
            return
        if not hasattr(self._world, "sync_world"):
            self._update(
                toast="World updates apply automatically when you host.",
            )
            return
        self._update(busy=True, download_pct=0)
        threading.Thread(target=self._run_sync_world, daemon=True).start()

    def _run_sync_world(self) -> None:
        try:
            result = self._world.sync_world()
            if result.get("ok"):
                self._update(
                    toast=f"World updated to v{result.get('version')}.",
                    busy=False,
                )
            else:
                self._apply_error_result(
                    {
                        "ok": False,
                        "error": result.get("error", "Update failed"),
                        "error_type": result.get("error_type", "SyncError"),
                    }
                )
        except Exception as exc:
            self._apply_error_result(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
            )
        finally:
            self._update(busy=False)
            self.refresh()

    def retry(self) -> None:
        if hasattr(self._session, "reset_error"):
            try:
                self._session.reset_error()
            except Exception as exc:
                logger.debug("reset_error: %s", exc)
        self._update(error=None, error_detail=None, error_type=None)
        self.refresh()

    def clear_toast(self) -> None:
        self._update(toast=None)

    def get_log_tail(self, n: int = 80) -> List[str]:
        try:
            return list(self._mc.get_log_tail(n=n))
        except Exception as exc:
            return [f"(unable to read log: {exc})"]

    def copy_address_text(self) -> Optional[str]:
        return self.snapshot.connection_address

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _apply_error_result(self, result: Dict[str, Any]) -> None:
        err_type = result.get("error_type") or "Error"
        raw = result.get("error") or "Unknown error"
        title, detail = FRIENDLY_ERRORS.get(
            err_type,
            (
                "Something went wrong.",
                "Your last known-good world is safe.",
            ),
        )
        self._last_error_type = err_type
        self._last_error_raw = raw
        self._update(
            error=title,
            error_detail=f"{detail}\n\n{raw}",
            error_type=err_type,
            busy=False,
            status_message=title,
        )

    def _steps_for(self, status: str) -> List[Dict[str, str]]:
        order = [
            ("sync", "World synchronized"),
            ("lock", "Host acquired"),
            ("mc", "Minecraft started"),
            ("ready", "Server ready"),
        ]
        if status == "closed":
            return [{"id": i, "label": l, "state": "pending"} for i, l in order]
        if status == "starting":
            return [
                {"id": "sync", "label": "World synchronized", "state": "done"},
                {"id": "lock", "label": "Host acquired", "state": "done"},
                {"id": "mc", "label": "Minecraft started", "state": "active"},
                {"id": "ready", "label": "Server ready", "state": "pending"},
            ]
        if status in ("active", "saving", "snapshotting", "uploading"):
            return [{"id": i, "label": l, "state": "done"} for i, l in order]
        if status == "error":
            return [
                {"id": "sync", "label": "World synchronized", "state": "done"},
                {"id": "lock", "label": "Host acquired", "state": "pending"},
                {"id": "mc", "label": "Minecraft started", "state": "pending"},
                {"id": "ready", "label": "Server ready", "state": "error"},
            ]
        return [{"id": i, "label": l, "state": "pending"} for i, l in order]

    def _message_for(self, status: str, sync_result: str) -> str:
        if status == "starting":
            return "Starting server..."
        if status == "active":
            return "Server Online"
        if status == "saving":
            return "Saving world...\nDo not close BlockSync."
        if status in ("snapshotting", "uploading"):
            return "Saving world to shared storage..."
        if status == "error":
            return self._snap.error or "Something went wrong."
        if sync_result == "NEEDS_UPDATE":
            return "New world version available."
        if sync_result in ("CONFLICT", "LOCAL_AHEAD"):
            return "World conflict — do not overwrite either copy."
        return "Ready to host"
