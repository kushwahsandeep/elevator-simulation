from __future__ import annotations

from typing import List, Protocol

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
