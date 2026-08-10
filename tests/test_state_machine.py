"""
tests/test_state_machine.py — Unit tests for SessionFSM.
"""

import pytest
from session.state import (
    InvalidTransitionError,
    SessionFSM,
    SessionState,
)


class TestValidTransitions:
    def test_closed_to_starting(self):
        fsm = SessionFSM()
        fsm.transition(SessionState.STARTING)
        assert fsm.state == SessionState.STARTING

    def test_happy_path(self):
        fsm = SessionFSM()
        path = [
            SessionState.STARTING,
            SessionState.ACTIVE,
            SessionState.SAVING,
            SessionState.SNAPSHOTTING,
            SessionState.UPLOADING,
            SessionState.CLOSED,
        ]
        for state in path:
            fsm.transition(state)
        assert fsm.state == SessionState.CLOSED

    def test_any_state_can_go_to_error(self):
        states_before_error = [
            SessionState.STARTING,
            SessionState.ACTIVE,
            SessionState.SAVING,
            SessionState.SNAPSHOTTING,
            SessionState.UPLOADING,
        ]
        for start in states_before_error:
            fsm = SessionFSM(initial=start)
            fsm.transition(SessionState.ERROR)
            assert fsm.state == SessionState.ERROR

    def test_error_to_closed(self):
        fsm = SessionFSM(initial=SessionState.ERROR)
        fsm.transition(SessionState.CLOSED)
        assert fsm.state == SessionState.CLOSED


class TestInvalidTransitions:
    def test_closed_to_active_is_invalid(self):
        fsm = SessionFSM()
        with pytest.raises(InvalidTransitionError):
            fsm.transition(SessionState.ACTIVE)

    def test_active_to_closed_is_invalid(self):
        fsm = SessionFSM(initial=SessionState.ACTIVE)
        with pytest.raises(InvalidTransitionError):
            fsm.transition(SessionState.CLOSED)

    def test_active_to_starting_is_invalid(self):
        fsm = SessionFSM(initial=SessionState.ACTIVE)
        with pytest.raises(InvalidTransitionError):
            fsm.transition(SessionState.STARTING)

    def test_uploading_to_starting_is_invalid(self):
        fsm = SessionFSM(initial=SessionState.UPLOADING)
        with pytest.raises(InvalidTransitionError):
            fsm.transition(SessionState.STARTING)

    def test_error_cannot_go_to_starting_directly(self):
        fsm = SessionFSM(initial=SessionState.ERROR)
        with pytest.raises(InvalidTransitionError):
            fsm.transition(SessionState.STARTING)


class TestForceError:
    def test_force_error_from_active(self):
        fsm = SessionFSM(initial=SessionState.ACTIVE)
        fsm.force_error("test crash")
        assert fsm.state == SessionState.ERROR

    def test_force_error_from_closed_is_noop_idempotent(self):
        # CLOSED → force_error should work (bypass normal table)
        fsm = SessionFSM()
        fsm.force_error("startup failure")
        assert fsm.state == SessionState.ERROR

    def test_force_error_idempotent(self):
        fsm = SessionFSM(initial=SessionState.ERROR)
        fsm.force_error("double error")  # Should not raise
        assert fsm.state == SessionState.ERROR


class TestObservers:
    def test_observer_called_on_transition(self):
        calls = []
        fsm = SessionFSM()
        fsm.add_observer(lambda old, new: calls.append((old, new)))
        fsm.transition(SessionState.STARTING)
        assert len(calls) == 1
        old, new = calls[0]
        assert old == SessionState.CLOSED
        assert new == SessionState.STARTING

    def test_observer_removed(self):
        calls = []
        cb = lambda old, new: calls.append((old, new))
        fsm = SessionFSM()
        fsm.add_observer(cb)
        fsm.remove_observer(cb)
        fsm.transition(SessionState.STARTING)
        assert calls == []

    def test_bad_observer_does_not_crash_fsm(self):
        def bad_observer(old, new):
            raise RuntimeError("observer bug")

        fsm = SessionFSM()
        fsm.add_observer(bad_observer)
        # Should not propagate the observer exception.
        fsm.transition(SessionState.STARTING)
        assert fsm.state == SessionState.STARTING

    def test_can_transition_to(self):
        fsm = SessionFSM()
        assert fsm.can_transition_to(SessionState.STARTING) is True
        assert fsm.can_transition_to(SessionState.ACTIVE) is False
