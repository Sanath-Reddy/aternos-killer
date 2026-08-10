"""
tests/test_minecraft_manager.py — Unit tests for MinecraftManager.

Uses subprocess mocking to avoid requiring a real Java installation.
"""

import subprocess
import time
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from minecraft.manager import (
    MinecraftManager,
    MissingServerJarError,
    ProcessStatus,
    SaveTimeoutError,
    ServerAlreadyRunningError,
    ServerNotRunningError,
    ServerReadyTimeoutError,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def make_manager(tmp_path: Path, **kwargs) -> MinecraftManager:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    server_jar = server_dir / "server.jar"
    server_jar.write_bytes(b"fake jar")
    return MinecraftManager(
        server_dir=server_dir,
        server_jar=server_jar,
        java_path="java",
        jvm_args=["-Xmx1G"],
        ready_timeout=kwargs.get("ready_timeout", 5.0),
        stop_timeout=kwargs.get("stop_timeout", 5.0),
        save_timeout=kwargs.get("save_timeout", 5.0),
    )


def fake_process(stdout_lines: list, returncode: int = 0) -> MagicMock:
    """Create a mock Popen that emits *stdout_lines* then exits."""
    output = "\n".join(stdout_lines) + "\n"
    proc = MagicMock(spec=subprocess.Popen)
    proc.stdout = StringIO(output)
    proc.stdin = MagicMock()
    proc.returncode = returncode
    proc.pid = 12345
    proc.poll.return_value = None
    proc.wait.return_value = returncode
    return proc


# ──────────────────────────────────────────────────────────────────────────────
# start()
# ──────────────────────────────────────────────────────────────────────────────

class TestStart:
    def test_missing_jar_raises(self, tmp_path):
        server_dir = tmp_path / "server"
        server_dir.mkdir()
        mgr = MinecraftManager(
            server_dir=server_dir,
            server_jar=server_dir / "server.jar",
        )
        with pytest.raises(MissingServerJarError):
            mgr.start()

    def test_already_running_raises(self, tmp_path):
        mgr = make_manager(tmp_path)
        proc = fake_process(["[Server thread/INFO]: Done (1.0s)! For help"])
        with patch("subprocess.Popen", return_value=proc):
            mgr.start()
        with pytest.raises(ServerAlreadyRunningError):
            with patch("subprocess.Popen", return_value=proc):
                mgr.start()

    def test_status_changes_to_starting(self, tmp_path):
        mgr = make_manager(tmp_path)
        proc = fake_process([])
        with patch("subprocess.Popen", return_value=proc):
            mgr.start()
        # Status should be STARTING (process running, no ready signal yet).
        assert mgr.status in (ProcessStatus.STARTING, ProcessStatus.READY)


# ──────────────────────────────────────────────────────────────────────────────
# wait_until_ready()
# ──────────────────────────────────────────────────────────────────────────────

class TestWaitUntilReady:
    def test_ready_on_done_signal(self, tmp_path):
        mgr = make_manager(tmp_path, ready_timeout=5.0)
        proc = fake_process([
            "[Server thread/INFO]: Starting Minecraft server",
            "[Server thread/INFO]: Done (1.234s)! For help, type \"help\"",
        ])
        with patch("subprocess.Popen", return_value=proc):
            mgr.start()
        time.sleep(0.2)  # let reader thread process the line
        assert mgr.status == ProcessStatus.READY

    def test_timeout_raises(self, tmp_path):
        mgr = make_manager(tmp_path, ready_timeout=0.3)
        proc = fake_process([
            "[Server thread/INFO]: Loading…",
            # No "Done" line
        ])
        proc.poll.return_value = None  # keep "running"
        with patch("subprocess.Popen", return_value=proc):
            mgr.start()
        with pytest.raises(ServerReadyTimeoutError):
            mgr.wait_until_ready(timeout=0.3)

    def test_process_exits_before_ready(self, tmp_path):
        mgr = make_manager(tmp_path, ready_timeout=2.0)
        proc = fake_process([], returncode=1)
        proc.poll.return_value = 1   # process already exited
        with patch("subprocess.Popen", return_value=proc):
            mgr.start()
        result = mgr.wait_until_ready(timeout=0.5)
        assert result is False


# ──────────────────────────────────────────────────────────────────────────────
# send_command()
# ──────────────────────────────────────────────────────────────────────────────

class TestSendCommand:
    def test_send_command_writes_to_stdin(self, tmp_path):
        mgr = make_manager(tmp_path)
        proc = fake_process(["[INFO]: Done (1.0s)!"])
        with patch("subprocess.Popen", return_value=proc):
            mgr.start()
        time.sleep(0.2)

        mgr.send_command("say hello")
        proc.stdin.write.assert_called()
        args = proc.stdin.write.call_args[0][0]
        assert "say hello" in args

    def test_send_command_raises_when_not_running(self, tmp_path):
        mgr = make_manager(tmp_path)
        with pytest.raises(ServerNotRunningError):
            mgr.send_command("stop")


# ──────────────────────────────────────────────────────────────────────────────
# get_log_lines()
# ──────────────────────────────────────────────────────────────────────────────

class TestGetLogLines:
    def test_log_lines_captured(self, tmp_path):
        mgr = make_manager(tmp_path)
        proc = fake_process([
            "Line one",
            "Line two",
            "[Server thread/INFO]: Done (1.0s)!",
        ])
        with patch("subprocess.Popen", return_value=proc):
            mgr.start()
        time.sleep(0.3)  # allow reader thread

        lines = mgr.get_log_lines(n=10)
        assert any("Line one" in l for l in lines)
        assert any("Line two" in l for l in lines)


# ──────────────────────────────────────────────────────────────────────────────
# Crash detection
# ──────────────────────────────────────────────────────────────────────────────

class TestCrashDetection:
    def test_crash_sets_crashed_status(self, tmp_path):
        mgr = make_manager(tmp_path)
        proc = fake_process(
            ["[INFO]: Done (1.0s)!", "[INFO]: Something went wrong"],
            returncode=1,
        )
        # process.poll returns None at first (running), then 1 (exited).
        proc.poll.side_effect = [None, None, 1]
        with patch("subprocess.Popen", return_value=proc):
            mgr.start()
        time.sleep(0.4)  # let watchdog + reader threads run

        # After process exits unexpectedly, status should be CRASHED.
        # (May take a moment for watchdog thread to notice.)
        for _ in range(10):
            if mgr.status == ProcessStatus.CRASHED:
                break
            time.sleep(0.1)
        assert mgr.status == ProcessStatus.CRASHED
