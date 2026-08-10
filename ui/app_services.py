"""
ui/app_services.py — Wire mock or real core services for the UI.

UI code imports only this module + viewmodels. Real core wiring follows
DEVELOPMENT.md and never pulls Drive/session/minecraft internals into screens.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from network.manager import NetworkManager
from network.radmin import RadminNetworkManager, StaticNetworkManager
from ui.mocks import build_default_mocks
from ui.viewmodels.session_vm import DEFAULT_SERVER_PORT, SessionViewModel

logger = logging.getLogger(__name__)


@dataclass
class AppServices:
    session: Any
    world: Any
    minecraft: Any
    network: NetworkManager
    view_model: SessionViewModel
    mode: str  # "mock" | "real"
    host_id: str
    server_port: int


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load_server_port() -> int:
    raw = os.environ.get("BLOCKSYNC_SERVER_PORT", "").strip()
    if raw.isdigit():
        return int(raw)
    return DEFAULT_SERVER_PORT


def try_build_real_services(
    network: NetworkManager,
    server_port: int,
) -> Optional[AppServices]:
    """Attempt to construct Dev1 core services. Returns None on failure."""
    try:
        from config.settings import BlockSyncConfig
        from core.minecraft_service import MinecraftService
        from core.session_service import SessionService
        from core.world_service import WorldService
        from minecraft.manager import MinecraftManager
        from session.lock import LockManager
        from session.session import Session
        from storage.gdrive import GoogleDriveStorageProvider
        from world.manager import WorldManager
        from world.snapshot import SnapshotBuilder
    except Exception as exc:
        logger.warning("Real core imports unavailable: %s", exc)
        return None

    world_id = os.environ.get("BLOCKSYNC_WORLD_ID", "survival")
    world_dir = os.environ.get("BLOCKSYNC_WORLD_DIR")
    server_dir = os.environ.get("BLOCKSYNC_SERVER_DIR")
    folder_id = os.environ.get("BLOCKSYNC_GDRIVE_FOLDER_ID")
    creds = os.environ.get("BLOCKSYNC_CREDENTIALS_FILE")

    if not all([world_dir, server_dir, folder_id, creds]):
        logger.info(
            "Real mode requested but BLOCKSYNC_* path env vars incomplete; "
            "falling back to mocks."
        )
        return None

    try:
        cfg = BlockSyncConfig(
            world_id=world_id,
            world_dir=Path(world_dir),
            server_dir=Path(server_dir),
            gdrive_folder_id=folder_id,
            credentials_file=Path(creds),
            minecraft_version=os.environ.get("BLOCKSYNC_MC_VERSION", "1.21.4"),
        )
        cfg.validate()
        cfg.ensure_work_dirs()

        provider = GoogleDriveStorageProvider(
            folder_id=cfg.gdrive_folder_id,
            credentials_file=cfg.credentials_file,
        )
        snapshot_builder = SnapshotBuilder()
        world_mgr = WorldManager(
            world_dir=cfg.world_dir,
            work_dir=cfg.work_dir,
            snapshots_dir=cfg.snapshots_dir,
            snapshot_builder=snapshot_builder,
        )
        mc_mgr = MinecraftManager(
            server_dir=cfg.server_dir,
            server_jar=cfg.server_jar,
            java_path=cfg.java_path,
            jvm_args=cfg.jvm_args,
            ready_timeout=cfg.ready_timeout,
            stop_timeout=cfg.stop_timeout,
            save_timeout=cfg.save_timeout,
        )
        lock_mgr = LockManager(provider=provider, config=cfg)
        session = Session(
            config=cfg,
            provider=provider,
            world_manager=world_mgr,
            minecraft_manager=mc_mgr,
            lock_manager=lock_mgr,
        )
        session_svc = SessionService(session)
        world_svc = WorldService(world_mgr, provider)
        mc_svc = MinecraftService(mc_mgr)
        vm = SessionViewModel(
            session_svc,
            world_svc,
            mc_svc,
            network,
            local_host_id=cfg.host_id,
            server_port=server_port,
        )
        return AppServices(
            session=session_svc,
            world=world_svc,
            minecraft=mc_svc,
            network=network,
            view_model=vm,
            mode="real",
            host_id=cfg.host_id,
            server_port=server_port,
        )
    except Exception as exc:
        logger.warning("Failed to wire real services: %s", exc, exc_info=True)
        return None


def build_app_services() -> AppServices:
    """Build services for the UI. Defaults to mocks for safe local UX."""
    use_mocks = _env_flag("BLOCKSYNC_USE_MOCKS", default=True)
    use_static_net = _env_flag("BLOCKSYNC_STATIC_NETWORK", default=False)
    server_port = _load_server_port()

    if use_static_net:
        network: NetworkManager = StaticNetworkManager(
            connected=True,
            ip=os.environ.get("BLOCKSYNC_STATIC_IP", "10.0.0.2"),
        )
    else:
        network = RadminNetworkManager()

    if not use_mocks:
        real = try_build_real_services(network, server_port)
        if real is not None:
            logger.info("BlockSync UI running against real core services.")
            return real
        logger.warning("Falling back to mock services.")

    foreign = os.environ.get("BLOCKSYNC_MOCK_FOREIGN_HOST") or None
    sync_result = os.environ.get("BLOCKSYNC_MOCK_SYNC", "UP_TO_DATE")
    local_v = int(os.environ.get("BLOCKSYNC_MOCK_LOCAL_VERSION", "184"))
    remote_v = int(os.environ.get("BLOCKSYNC_MOCK_REMOTE_VERSION", "184"))

    session, world, mc = build_default_mocks(
        foreign_host=foreign,
        sync_result=sync_result,
        local_version=local_v,
        remote_version=remote_v,
    )
    host_id = "you-local-mock"
    vm = SessionViewModel(
        session,
        world,
        mc,
        network,
        local_host_id=host_id,
        server_port=server_port,
    )
    logger.info("BlockSync UI running with mock services (mode=mock).")
    return AppServices(
        session=session,
        world=world,
        minecraft=mc,
        network=network,
        view_model=vm,
        mode="mock",
        host_id=host_id,
        server_port=server_port,
    )
