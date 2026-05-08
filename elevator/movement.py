from __future__ import annotations

from typing import List, Optional

from .models import Elevator


def stop_floors_for_elevator(el: Elevator, max_passengers: int) -> List[int]:
    """Pickup floors only if below capacity; always include onboard destinations (SCAN targets)."""
    floors: set[int] = set()
    if len(el.onboard) < max_passengers:
        for floor_no, queue in el.waiting.items():
            if queue:
                floors.add(floor_no)
    for p in el.onboard.values():
        floors.add(p.request.dest)
    return sorted(floors)


def scan_next_target(current: int, stop_floors: List[int], direction: int) -> Optional[int]:
    """Next SCAN waypoint; ``direction`` +1 hunts up then wraps, -1 hunts down."""
    if not stop_floors:
        return None
    s = sorted(set(stop_floors))
    d = 1 if direction >= 0 else -1
    if d > 0:
        right = [f for f in s if f >= current]
        if right:
            return min(right)
        return max(s)
    left = [f for f in s if f <= current]
    if left:
        return max(left)
    return min(s)


def move_one_floor(current: int, target: Optional[int]) -> tuple[int, int]:
    """Move one floor toward ``target``; idle if ``None`` or already there."""
    if target is None or current == target:
        return current, 0
    if current < target:
        return current + 1, 1
    return current - 1, -1


def update_direction_after_move(
    new_floor: int,
    stops: List[int],
    prev_direction: int,
) -> int:
    """Momentum: pick scan direction toward the next remaining stop."""
    if not stops:
        return 0
    t = scan_next_target(new_floor, stops, prev_direction if prev_direction != 0 else 1)
    if t is None:
        return 0
    if t > new_floor:
        return 1
    if t < new_floor:
        return -1
    return prev_direction if prev_direction != 0 else 1
