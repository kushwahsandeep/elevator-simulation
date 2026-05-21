from __future__ import annotations



from collections import defaultdict, deque

from typing import Dict, List, Set



from .models import Elevator, Passenger





def _eligible_pickup_indices(elevators: List[Elevator], max_passengers: int) -> List[int]:

    return [i for i, e in enumerate(elevators) if len(e.onboard) < max_passengers]





def _normalize_assignment_strategy(name: str) -> str:

    key = (name or "nearest").strip().lower().replace("-", "_")

    if key == "score":

        key = "score_based"

    return key





def _pick_elevator_for_landing(

    elevators: List[Elevator],

    pickup_floor: int,

    eligible: List[int],

    strategy: str,

    rr_counter: List[int],

) -> int:

    """Choose one dispatcher for a hall queue (eligible = cars with pickup capacity)."""

    sk = _normalize_assignment_strategy(strategy)

    if sk == "nearest":

        return min(eligible, key=lambda i: (abs(elevators[i].floor - pickup_floor), i))

    if sk == "round_robin":

        elist = sorted(eligible)

        chosen = elist[rr_counter[0] % len(elist)]

        rr_counter[0] += 1

        return chosen

    # score_based: distance, onboard load, small bonus toward source (same weights as scheduler.ScoreBased)

    if sk == "score_based":

        best_i = eligible[0]

        best_score = 10**18

        for i in eligible:

            el = elevators[i]

            dist = abs(el.floor - pickup_floor)

            load = len(el.onboard)

            bonus = 0

            if el.direction != 0:

                delta = pickup_floor - el.floor

                toward = (delta > 0 and el.direction > 0) or (delta < 0 and el.direction < 0)

                if toward:

                    bonus = -3

            score = dist * 10 + load * 4 + bonus

            if score < best_score or (score == best_score and i < best_i):

                best_score = score

                best_i = i

        return best_i

    return min(eligible, key=lambda i: (abs(elevators[i].floor - pickup_floor), i))





def elevator_pickup_floor_sets(

    elevators: List[Elevator],

    max_passengers: int,

    landing_queues: Dict[int, deque[Passenger]],

    assignment_strategy: str,

    rr_counter: List[int],

) -> Dict[int, Set[int]]:

    """Give each nonempty landing hall exactly one dispatched car's navigation targets for this movement phase.



    ``rr_counter`` is a single-element list holding the mutable round-robin cursor.

    """

    nonempty = [(floor, queue) for floor, queue in landing_queues.items() if queue]

    nonempty.sort(key=lambda fq: (fq[1][0].request.time, fq[0]))

    pickup_by_elev_idx: Dict[int, Set[int]] = defaultdict(set)

    for floor, _queue in nonempty:

        eligible = _eligible_pickup_indices(elevators, max_passengers)

        if not eligible:

            continue

        pick_i = _pick_elevator_for_landing(

            elevators, floor, eligible, assignment_strategy, rr_counter

        )

        pickup_by_elev_idx[pick_i].add(floor)

    return pickup_by_elev_idx





def stop_floors_for_elevator(

    el: Elevator,

    max_passengers: int,

    landing_queues: Dict[int, deque[Passenger]],

    dispatched_pickups: Set[int],

) -> List[int]:

    """Drop targets; hall stops for dispatched pickups; include queued travelers' dest for routing."""

    floors: set[int] = {p.request.dest for p in el.onboard.values()}

    active = {f for f in dispatched_pickups if landing_queues.get(f)}

    if active and len(el.onboard) < max_passengers:

        floors |= active

        for floor_no in active:

            queue = landing_queues.get(floor_no)

            if queue:

                floors |= {p.request.dest for p in queue}

    return sorted(floors)





def scan_next_target(current: int, stop_floors: List[int], direction: int) -> int | None:

    """Next SCAN waypoint; never returns ``current`` — hop is always to another floor."""

    if not stop_floors:

        return None

    s = sorted(set(stop_floors))

    d = 1 if direction >= 0 else -1

    if d > 0:

        above = [f for f in s if f > current]

        if above:

            return min(above)

        below = [f for f in s if f < current]

        if below:

            return max(below)

        return None

    below_first = [f for f in s if f < current]

    if below_first:

        return max(below_first)

    above_wrap = [f for f in s if f > current]

    if above_wrap:

        return min(above_wrap)

    return None





def move_one_floor(current: int, target: int | None) -> tuple[int, int]:

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





def move_elevators(

    elevators: List[Elevator],

    max_passengers: int,

    landing_queues: Dict[int, deque[Passenger]],

    assignment_strategy: str,

    rr_counter: List[int],

) -> None:

    pickup_by_idx = elevator_pickup_floor_sets(

        elevators, max_passengers, landing_queues, assignment_strategy, rr_counter

    )

    for el in elevators:

        dispatched_pickups = pickup_by_idx.get(el.idx, set())

        active_pickups = {f for f in dispatched_pickups if landing_queues.get(f)}

        stops = stop_floors_for_elevator(el, max_passengers, landing_queues, active_pickups)

        if not stops:

            el.direction = 0

            continue

        if el.direction == 0:

            t_up = scan_next_target(el.floor, stops, 1)

            t_dn = scan_next_target(el.floor, stops, -1)

            if t_up is None and t_dn is None:

                el.direction = 0

                continue


            if t_up is None:

                assert t_dn is not None

                el.direction = -1 if t_dn < el.floor else 1


            elif t_dn is None:

                assert t_up is not None

                el.direction = 1 if t_up > el.floor else -1


            else:

                du = abs(t_up - el.floor)

                dd = abs(t_dn - el.floor)

                if du < dd or (du == dd and t_up >= el.floor):

                    el.direction = 1 if t_up >= el.floor else -1

                else:

                    el.direction = -1 if t_dn <= el.floor else 1



        target = scan_next_target(el.floor, stops, el.direction)

        if target is None:

            el.direction = 0

            continue

        new_floor, _ = move_one_floor(el.floor, target)

        el.floor = new_floor



        dispatched_pickups2 = pickup_by_idx.get(el.idx, set())

        active_pickups2 = {f for f in dispatched_pickups2 if landing_queues.get(f)}

        stops_after = stop_floors_for_elevator(

            el, max_passengers, landing_queues, active_pickups2

        )

        if stops_after:

            el.direction = update_direction_after_move(new_floor, stops_after, el.direction)

        else:

            el.direction = 0

