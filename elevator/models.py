from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional


_ASSIGNMENT_STRATEGIES = frozenset({"nearest", "round_robin", "score_based"})


@dataclass(frozen=True)
class SimulationConfig:
    """Discrete simulation parameters (``assignment_strategy`` selects hall→car dispatch each tick)."""

    num_floors: int
    num_elevators: int
    max_passengers: int
    initial_floor: int = 1
    assignment_strategy: str = "nearest"

    def __post_init__(self) -> None:
        if self.num_floors < 1:
            raise ValueError("num_floors must be >= 1")
        if self.num_elevators < 1:
            raise ValueError("num_elevators must be >= 1")
        if self.max_passengers < 1:
            raise ValueError("max_passengers must be >= 1")
        if not 1 <= self.initial_floor <= self.num_floors:
            raise ValueError("initial_floor must be in [1, num_floors]")
        ak = self.assignment_strategy.strip().lower().replace("-", "_")
        if ak == "score":
            ak = "score_based"
        if ak not in _ASSIGNMENT_STRATEGIES:
            allowed = ", ".join(sorted(_ASSIGNMENT_STRATEGIES))
            raise ValueError(f"assignment_strategy must be one of {allowed}")
        object.__setattr__(self, "assignment_strategy", ak)


@dataclass(frozen=True)
class RequestInput:
    """CSV row: time, id, source, destination."""

    time: int
    passenger_id: str
    source: int
    dest: int


@dataclass
class Passenger:
    request: RequestInput
    assigned_elevator: int
    picked_up_at: Optional[int] = None
    dropped_at: Optional[int] = None

    @property
    def wait_time(self) -> int:
        if self.picked_up_at is None:
            raise RuntimeError("passenger still waiting")
        return self.picked_up_at - self.request.time

    @property
    def travel_time(self) -> int:
        if self.picked_up_at is None or self.dropped_at is None:
            raise RuntimeError("passenger not delivered")
        return self.dropped_at - self.picked_up_at

    @property
    def total_time(self) -> int:
        if self.dropped_at is None:
            raise RuntimeError("passenger not delivered")
        return self.dropped_at - self.request.time


@dataclass
class Elevator:
    idx: int
    floor: int
    direction: int  # -1, 0 idle, +1
    waiting: Dict[int, Deque[Passenger]] = field(default_factory=dict)
    onboard: Dict[str, Passenger] = field(default_factory=dict)

    def stop_floors(self) -> List[int]:
        """Floors with a waiting queue or an onboard drop."""
        floors: set[int] = set()
        for floor_no, queue in self.waiting.items():
            if queue:
                floors.add(floor_no)
        for p in self.onboard.values():
            floors.add(p.request.dest)
        return sorted(floors)
