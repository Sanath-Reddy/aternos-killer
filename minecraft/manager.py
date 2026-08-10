"""
minecraft/manager.py — Minecraft Java server process management.

Responsibilities:
- Launch the Java process (``server.jar``) with configurable JVM args.
- Read stdout/stderr on a daemon thread and push lines into a queue.
- Detect server readiness by watching for the "Done (...)" log line.
- Send console commands via stdin.
- Perform graceful shutdown: ``stop`` command → wait → kill if necessary.
- Detect crashes (unexpected process exit while state ≠ STOPPING).
- Surface structured status via ``ProcessStatus``.

Never assumes ``java process started == Minecraft is ready``.
If the server JAR is missing, ``MissingServerJarError`` is raised before
the subprocess is even created.
"""

from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time
from enum import Enum
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Status enum
# ──────────────────────────────────────────────────────────────────────────────

class ProcessStatus(Enum):
    NOT_RUNNING  = "not_running"
    STARTING     = "starting"
    READY        = "ready"
    STOPPING     = "stopping"
    CRASHED      = "crashed"


# ──────────────────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────────────────

class MissingServerJarError(FileNotFoundError):
    """Raised when ``server.jar`` does not exist at the configured path."""


class ServerNotRunningError(RuntimeError):
    """Raised when an operation requires a running server but none is active."""


class ServerAlreadyRunningError(RuntimeError):
    """Raised when ``start()`` is called while the server is already running."""


class ServerReadyTimeoutError(TimeoutError):
    """Raised when the server does not emit the ready signal in time."""


class SaveTimeoutError(TimeoutError):
    """Raised when ``save-all flush`` is not confirmed within the timeout."""


class StopTimeoutError(TimeoutError):
    """Raised when the server process does not exit within the stop timeout."""


# ──────────────────────────────────────────────────────────────────────────────
# Ready / save signal patterns
# ──────────────────────────────────────────────────────────────────────────────

# Minecraft 1.7+ prints this when the server has finished loading.
_READY_SIGNAL = "Done ("          # e.g. "Done (3.456s)! For help, type "help""
_SAVE_SIGNAL  = "Saved the game"  # emitted after save-all flush
_STOP_SIGNAL  = "Stopping server" # emitted early in shutdown (belt-and-suspenders)


# ──────────────────────────────────────────────────────────────────────────────
# MinecraftManager
# ──────────────────────────────────────────────────────────────────────────────

class MinecraftManager:
    """Manages a single Minecraft Java Edition server process.

    Parameters
    ----------
    server_dir:
        Working directory for the server (contains ``server.jar``,
        ``server.properties``, ``world/``, etc.).
    server_jar:
        Absolute path to ``server.jar``.  Must exist before ``start()`` is
        called.
    java_path:
        Path to the Java executable (``"java"`` resolves via PATH).
    jvm_args:
        Extra flags passed before ``-jar``.  E.g. ``["-Xmx4G", "-Xms1G"]``.
    ready_timeout:
        Seconds to wait for the ``Done (...)`` ready signal.
    stop_timeout:
        Seconds to wait for the process to exit after sending ``stop``.
    save_timeout:
        Seconds to wait for ``Saved the game`` confirmation.
    max_log_lines:
        Maximum number of log lines kept in the in-memory ring buffer.
    """

    def __init__(
        self,
        server_dir: Path,
        server_jar: Path,
        java_path: str = "java",
        jvm_args: Optional[List[str]] = None,
        ready_timeout: float = 180.0,
        stop_timeout: float = 60.0,
        save_timeout: float = 30.0,
        max_log_lines: int = 2000,
    ) -> None:
        self._server_dir   = server_dir
        self._server_jar   = server_jar
        self._java_path    = java_path
        self._jvm_args     = jvm_args or ["-Xmx4G", "-Xms1G"]
        self._ready_timeout = ready_timeout
        self._stop_timeout  = stop_timeout
        self._save_timeout  = save_timeout
        self._max_log_lines = max_log_lines

        self._process: Optional[subprocess.Popen] = None
        self._status  = ProcessStatus.NOT_RUNNING
        self._status_lock = threading.Lock()

        # Stdout/stderr is merged and read on a daemon thread.
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._log_lines: List[str] = []
        self._log_lock  = threading.Lock()

        self._reader_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the Minecraft server process.

        Does NOT wait for readiness — call ``wait_until_ready()`` afterwards.

        Raises:
            ServerAlreadyRunningError: If a process is already running.
            MissingServerJarError: If ``server.jar`` does not exist.
        """
        with self._status_lock:
            if self._status not in (ProcessStatus.NOT_RUNNING, ProcessStatus.CRASHED):
                raise ServerAlreadyRunningError(
                    f"Server is already in state: {self._status.value}"
                )

        if not self._server_jar.exists():
            raise MissingServerJarError(
                f"server.jar not found: {self._server_jar}\n"
                "Run the jar downloader first."
            )

        cmd = [
            self._java_path,
            *self._jvm_args,
            "-jar", str(self._server_jar),
            "nogui",
        ]
        logger.info("Launching Minecraft: %s", " ".join(cmd))

        self._process = subprocess.Popen(
            cmd,
            cwd=str(self._server_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # merge so we see everything
            bufsize=1,                  # line-buffered
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        self._set_status(ProcessStatus.STARTING)

        # Clear stale log buffer from previous run.
        with self._log_lock:
            self._log_lines.clear()
        while not self._log_queue.empty():
            try:
                self._log_queue.get_nowait()
            except queue.Empty:
                break

        # Start background reader + watchdog.
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            daemon=True,
            name="mc-stdout-reader",
        )
        self._reader_thread.start()

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="mc-watchdog",
        )
        self._watchdog_thread.start()

        logger.debug("Process started (PID=%s)", self._process.pid)

    def wait_until_ready(self, timeout: Optional[float] = None) -> bool:
        """Block until the server emits the ``Done (...)`` ready signal.

        Parameters
        ----------
        timeout:
            Override the default ready timeout (seconds).  Pass ``None`` to
            use the value configured at construction time.

        Returns:
            ``True`` if the server became ready, ``False`` if it exited before
            the ready signal was seen.

        Raises:
            ServerNotRunningError: If ``start()`` has not been called.
            ServerReadyTimeoutError: If the timeout elapses without the signal.
        """
        if self._process is None:
            raise ServerNotRunningError("start() has not been called")

        deadline = time.monotonic() + (timeout or self._ready_timeout)

        while time.monotonic() < deadline:
            # Check if process died unexpectedly.
            if self._process.poll() is not None:
                logger.warning(
                    "Server process exited (rc=%s) before ready signal",
                    self._process.returncode,
                )
                return False

            # Check if we already transitioned to READY via the reader thread.
            if self.status == ProcessStatus.READY:
                return True

            time.sleep(0.25)

        raise ServerReadyTimeoutError(
            f"Server did not become ready within {timeout or self._ready_timeout}s"
        )

    def save(self, timeout: Optional[float] = None) -> bool:
        """Send ``save-all flush`` and wait for ``Saved the game`` confirmation.

        Returns:
            ``True`` if save was confirmed, ``False`` on timeout.

        Raises:
            ServerNotRunningError: If the server is not in READY state.
            SaveTimeoutError: If the save is not confirmed within *timeout*.
        """
        self._require_status(ProcessStatus.READY, "save")

        deadline = time.monotonic() + (timeout or self._save_timeout)

        logger.info("Sending save-all flush …")
        self.send_command("save-all flush")

        while time.monotonic() < deadline:
            if self._process and self._process.poll() is not None:
                raise ServerNotRunningError("Server exited during save")
            # Scan recent log lines for the save confirmation.
            with self._log_lock:
                for line in reversed(self._log_lines[-50:]):
                    if _SAVE_SIGNAL in line:
                        logger.info("Save confirmed.")
                        return True
            time.sleep(0.2)

        raise SaveTimeoutError(
            f"Save not confirmed within {timeout or self._save_timeout}s"
        )

    def stop(self, timeout: Optional[float] = None) -> bool:
        """Gracefully stop the Minecraft server.

        Sends the ``stop`` command, waits for the process to exit, and kills
        it if the timeout elapses.

        Returns:
            ``True`` if the process exited cleanly, ``False`` if it was killed.

        Raises:
            ServerNotRunningError: If the server is not running.
        """
        with self._status_lock:
            if self._status not in (ProcessStatus.READY, ProcessStatus.STARTING):
                raise ServerNotRunningError(
                    f"Cannot stop: server is in state {self._status.value}"
                )
            self._status = ProcessStatus.STOPPING

        logger.info("Stopping Minecraft server …")
        self.send_command("stop")

        deadline = time.monotonic() + (timeout or self._stop_timeout)
        while time.monotonic() < deadline:
            if self._process and self._process.poll() is not None:
                rc = self._process.returncode
                logger.info("Server process exited cleanly (rc=%s)", rc)
                self._set_status(ProcessStatus.NOT_RUNNING)
                self._process = None
                return True
            time.sleep(0.5)

        # Graceful stop timed out — kill.
        logger.warning(
            "Server did not exit within %ss; sending SIGKILL",
            timeout or self._stop_timeout,
        )
        if self._process:
            self._process.kill()
            self._process.wait()
            self._process = None
        self._set_status(ProcessStatus.NOT_RUNNING)
        return False

    def send_command(self, cmd: str) -> None:
        """Write a console command to the server's stdin.

        Raises:
            ServerNotRunningError: If no process is running.
        """
        if self._process is None or self._process.stdin is None:
            raise ServerNotRunningError("No running server process to send command to")
        try:
            self._process.stdin.write(cmd + "\n")
            self._process.stdin.flush()
            logger.debug("→ MC command: %r", cmd)
        except (BrokenPipeError, OSError) as exc:
            logger.error("Failed to send command %r: %s", cmd, exc)
            raise ServerNotRunningError(f"stdin write failed: {exc}") from exc

    @property
    def status(self) -> ProcessStatus:
        """Current process status (thread-safe)."""
        with self._status_lock:
            return self._status

    def get_log_lines(self, n: int = 100) -> List[str]:
        """Return the last *n* lines from the server log buffer."""
        with self._log_lock:
            return list(self._log_lines[-n:])

    def is_running(self) -> bool:
        """Return True if the server process is alive."""
        return self._process is not None and self._process.poll() is None

    # ── Private helpers ───────────────────────────────────────────────────────

    def _set_status(self, new_status: ProcessStatus) -> None:
        with self._status_lock:
            old = self._status
            self._status = new_status
        if old != new_status:
            logger.debug("ProcessStatus: %s → %s", old.value, new_status.value)

    def _require_status(self, required: ProcessStatus, op: str) -> None:
        current = self.status
        if current != required:
            raise ServerNotRunningError(
                f"Cannot perform '{op}': server status is {current.value!r} "
                f"(expected {required.value!r})"
            )

    def _reader_loop(self) -> None:
        """Daemon thread: read stdout/stderr line by line and buffer them."""
        assert self._process is not None
        assert self._process.stdout is not None

        for raw_line in self._process.stdout:
            line = raw_line.rstrip("\n")
            self._log_queue.put(line)

            with self._log_lock:
                self._log_lines.append(line)
                # Trim buffer to avoid unbounded growth.
                if len(self._log_lines) > self._max_log_lines:
                    del self._log_lines[: self._max_log_lines // 2]

            logger.debug("[MC] %s", line)

            # Detect readiness.
            if _READY_SIGNAL in line and self.status == ProcessStatus.STARTING:
                logger.info("Server ready signal received.")
                self._set_status(ProcessStatus.READY)

        # EOF — process has exited.
        logger.debug("MC stdout reader: EOF reached")

    def _watchdog_loop(self) -> None:
        """Daemon thread: detect unexpected process exit (crash)."""
        assert self._process is not None
        self._process.wait()   # blocks until the process exits

        with self._status_lock:
            current = self._status

        if current not in (ProcessStatus.NOT_RUNNING, ProcessStatus.STOPPING):
            logger.error(
                "Minecraft process exited unexpectedly (rc=%s) — CRASH detected!",
                self._process.returncode if self._process else "?",
            )
            self._set_status(ProcessStatus.CRASHED)
        else:
            logger.debug("Watchdog: process exited normally")
