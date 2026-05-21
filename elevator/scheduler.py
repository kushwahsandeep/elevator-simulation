from __future__ import annotations

from typing import Callable, List, Protocol, Type

from .models import Elevator, RequestInput


class AssignmentStrategy(Protocol):
    def assign(self, req: RequestInput, elevators: List[Elevator]) -> int:
        """Return elevator index (0-based) for this request."""


class NearestCar:
    """Pick the elevator whose current floor is closest to request.source (tie: lower index)."""

    def assign(self, req: RequestInput, elevators: List[Elevator]) -> int:
        best_idx = 0
        best_dist = abs(elevators[0].floor - req.source)
        for i in range(1, len(elevators)):
            d = abs(elevators[i].floor - req.source)
            if d < best_dist or (d == best_dist and i < best_idx):
                best_dist = d
                best_idx = i
        return best_idx


class RoundRobin:
    """Assign incoming requests to elevators in cyclic order (0 → 1 → … → repeat)."""

    __slots__ = ("_next",)

    def __init__(self) -> None:
        self._next = 0

    def assign(self, req: RequestInput, elevators: List[Elevator]) -> int:
        if not elevators:
            raise ValueError("assign: no elevators")
        i = self._next % len(elevators)
        self._next += 1
        return i


class ScoreBased:
    """Lower score wins: distance to pickup, load, small bonus if car is moving toward the source."""

    def assign(self, req: RequestInput, elevators: List[Elevator]) -> int:
        best_idx = 0
        best_score = 1e18
        for i, el in enumerate(elevators):
            dist = abs(el.floor - req.source)
            load = len(el.onboard)
            for q in el.waiting.values():
                load += len(q)
            bonus = 0
            if el.direction != 0:
                delta = req.source - el.floor
                toward = (delta > 0 and el.direction > 0) or (delta < 0 and el.direction < 0)
                if toward:
                    bonus = -3
            score = dist * 10 + load * 4 + bonus
            if score < best_score or (score == best_score and i < best_idx):
                best_score = score
                best_idx = i
        return best_idx


_STRATEGIES: dict[str, Type[NearestCar | RoundRobin | ScoreBased]] = {
    "nearest": NearestCar,
    "round_robin": RoundRobin,
    "score_based": ScoreBased,
}


def strategy_names() -> List[str]:
    return sorted(_STRATEGIES.keys())


def assignment_strategy_for(name: str) -> NearestCar | RoundRobin | ScoreBased:
    """Instantiate a strategy (fresh state per simulation / live session)."""
    key = (name or "nearest").strip().lower().replace("-", "_")
    if key == "score":
        key = "score_based"
    cls = _STRATEGIES.get(key)
    if cls is None:
        allowed = ", ".join(strategy_names())
        raise ValueError(f"unknown assignment_strategy {name!r}; use one of: {allowed}")
    inst: NearestCar | RoundRobin | ScoreBased = cls()
    return inst


def get_assign_fn(name: str) -> Callable[[RequestInput, List[Elevator]], int]:
    """Return a strategy's ``assign(req, elevators)`` for tests and tools.

    Hall→car pickup dispatch in ``elevator.movement`` uses ``SimulationConfig.assignment_strategy`` each tick.
    """
    return assignment_strategy_for(name).assign
