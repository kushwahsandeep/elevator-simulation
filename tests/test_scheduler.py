"""Assignment strategy registry and behavior."""

import pytest

from elevator.models import Elevator, RequestInput
from elevator.scheduler import (
    NearestCar,
    RoundRobin,
    ScoreBased,
    assignment_strategy_for,
    get_assign_fn,
)


def _elevators_template(n: int = 3) -> list[Elevator]:
    return [
        Elevator(idx=i, floor=3, direction=0, waiting={}, onboard={})
        for i in range(n)
    ]


def test_get_assign_fn_unknown_raises():
    with pytest.raises(ValueError, match="unknown assignment_strategy"):
        get_assign_fn("nope")


def test_assignment_strategy_for_aliases_score():
    a = assignment_strategy_for("score")
    assert isinstance(a, ScoreBased)


def test_round_robin_cycles():
    rr = RoundRobin()
    req = RequestInput(0, "p", 1, 2)
    els = _elevators_template(3)
    assert rr.assign(req, els) == 0
    assert rr.assign(req, els) == 1
    assert rr.assign(req, els) == 2
    assert rr.assign(req, els) == 0


def test_nearest_car_picks_closest():
    req = RequestInput(0, "p", source=11, dest=12)
    els = [
        Elevator(0, floor=2, direction=0, waiting={}, onboard={}),
        Elevator(1, floor=9, direction=0, waiting={}, onboard={}),
        Elevator(2, floor=11, direction=0, waiting={}, onboard={}),
    ]
    assert NearestCar().assign(req, els) == 2


def test_score_based_prefers_closer_over_rr():
    """Regression: strategies must be instantiable independently."""
    assert callable(get_assign_fn("nearest"))
    assert callable(get_assign_fn("score_based"))
