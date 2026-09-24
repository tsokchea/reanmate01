"""Which submission states may follow which (server/src/services/assignment-state-machine.js)."""

from ..middleware.errors import ApiError

ASSIGNMENT_TRANSITIONS = {
    "not_started": ("in_progress", "submitted", "late"),
    "in_progress": ("in_progress", "submitted", "late"),
    "submitted": ("graded",),
    "late": ("graded",),
    "graded": (),
}


def assert_assignment_transition(from_state, to_state):
    if to_state not in ASSIGNMENT_TRANSITIONS.get(from_state, ()):
        raise ApiError.conflict(f"A submission cannot move from {from_state} to {to_state}")
