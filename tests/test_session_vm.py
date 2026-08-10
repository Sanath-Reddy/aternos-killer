"""SessionViewModel tests against mock services."""

from network.radmin import StaticNetworkManager
from ui.mocks import build_default_mocks
from ui.viewmodels.session_vm import SessionViewModel


def test_host_and_stop_flow():
    session, world, mc = build_default_mocks(sync_result="UP_TO_DATE")
    net = StaticNetworkManager(connected=True, ip="10.9.8.7")
    vm = SessionViewModel(session, world, mc, net, local_host_id="you-local-mock")

    assert vm.snapshot.status == "closed"
    assert vm.snapshot.connection_address == "10.9.8.7:25565"

    result = session.begin_host()
    assert result["ok"] is True
    vm.refresh()
    snap = vm.snapshot
    assert snap.status == "active"
    assert snap.host_is_self is True
    assert snap.server_status == "online"

    end = session.end_host()
    assert end["ok"] is True
    vm.refresh()
    assert vm.snapshot.status == "closed"


def test_lock_conflict_error_type():
    session, world, mc = build_default_mocks(foreign_host="alice-pc")
    net = StaticNetworkManager(connected=True, ip="10.9.8.7")
    vm = SessionViewModel(session, world, mc, net, local_host_id="you-local-mock")
    vm.refresh()
    assert vm.snapshot.host_name == "alice-pc"

    result = session.begin_host()
    assert result["ok"] is False
    assert result["error_type"] == "lock_conflict"


def test_radmin_blocks_host():
    session, world, mc = build_default_mocks()
    net = StaticNetworkManager(connected=False)
    vm = SessionViewModel(session, world, mc, net, local_host_id="you-local-mock")
    vm.host_world()
    # host_world is async; wait briefly via direct check of sync path
    # Call the internal guard path by inspecting snapshot after sync invoke:
    # host_world starts a thread — join by polling
    import time

    for _ in range(20):
        if vm.snapshot.error_type == "RadminUnavailable":
            break
        time.sleep(0.05)
    assert vm.snapshot.error_type == "RadminUnavailable"
    assert session.get_state() == "closed"
