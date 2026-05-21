from __future__ import annotations

import csv
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from io import StringIO
from typing import Dict, List, Optional, Sequence, TextIO, Tuple

from .models import Elevator, Passenger, RequestInput, SimulationConfig
from .movement import move_elevators
logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    passengers: List[Passenger]
    position_log_lines: List[str]
    request_journal_lines: List[str] = field(default_factory=list)


def _validate_request(req: RequestInput, config: SimulationConfig) -> None:
    for label, floor in (("source", req.source), ("dest", req.dest)):
        if not 1 <= floor <= config.num_floors:
            raise ValueError(
                f"{req.passenger_id}: {label} floor {floor} out of range 1..{config.num_floors}"
            )
    if req.source == req.dest:
        raise ValueError(f"{req.passenger_id}: source and dest must differ")


def format_request_journal_header() -> str:
    return (
        "tick,event,passenger_id,request_time,source,dest,elevator,"
        "wait_time,travel_time,total_time,status"
    )


def _request_journal_row(
    tick: int,
    event: str,
    passenger_id: str,
    request_time: int,
    source: int,
    dest: int,
    elevator: int,
    wait_cell: str,
    travel_cell: str,
    total_cell: str,
    status: str,
) -> str:
    buf = StringIO()
    w = csv.writer(buf, lineterminator="")
    w.writerow(
        [
            tick,
            event,
            passenger_id,
            request_time,
            source,
            dest,
            elevator,
            wait_cell,
            travel_cell,
            total_cell,
            status,
        ]
    )
    return buf.getvalue()


def _passenger_requests_trip_up(p: Passenger) -> bool:
    """True when dest > source — \"up\" in the UI."""
    return p.request.dest > p.request.source


def _pickup_matches_lift_direction(p: Passenger, lift_direction: int) -> bool:
    """Idle accepts any passenger. Moving up blocks only down-bound trips."""
    if lift_direction == 0:
        return True
    # Up-bound shafts pass down-trip waiters until direction idles/reverses; do not strand
    # up-trips arriving on a descending car after it stops at their landing floor.
    if lift_direction > 0 and not _passenger_requests_trip_up(p):
        return False
    return True


def _pickup_matches_cabin_trip_mix(p: Passenger, onboard: Dict[str, Passenger]) -> bool:
    """Non-empty cabin only boards passengers whose declared trip matches existing occupants."""
    if not onboard:
        return True
    cabin_up = _passenger_requests_trip_up(next(iter(onboard.values())))
    return _passenger_requests_trip_up(p) == cabin_up


def _pickup_allowed_at_floor(p: Passenger, el: Elevator) -> bool:
    return _pickup_matches_lift_direction(p, el.direction) and _pickup_matches_cabin_trip_mix(p, el.onboard)


def service_elevator(
    el: Elevator,
    tick: int,
    max_passengers: int,
    landing_queues: dict[int, deque[Passenger]],
    request_journal_lines: Optional[List[str]] = None,
) -> None:
    f = el.floor
    to_remove: List[str] = [
        pid for pid, p in el.onboard.items() if p.request.dest == f
    ]
    for pid in to_remove:
        p = el.onboard.pop(pid)
        p.dropped_at = tick
        w_t = p.picked_up_at - p.request.time if p.picked_up_at is not None else None
        tr_t = p.dropped_at - p.picked_up_at if p.picked_up_at is not None else None
        tot_t = p.dropped_at - p.request.time
        logger.info(
            "tick=%s event=DROPOFF elevator=%s floor=%s passenger=%s dest=%s "
            "wait=%s travel=%s total=%s",
            tick,
            el.idx,
            f,
            p.request.passenger_id,
            p.request.dest,
            w_t,
            tr_t,
            tot_t,
        )
        if request_journal_lines is not None:
            assert w_t is not None and tr_t is not None
            request_journal_lines.append(
                _request_journal_row(
                    tick,
                    "DROPOFF",
                    p.request.passenger_id,
                    p.request.time,
                    p.request.source,
                    p.request.dest,
                    el.idx,
                    str(w_t),
                    str(tr_t),
                    str(tot_t),
                    "DELIVERED",
                )
            )

    # Shared landing queue; scan with rotation so a wrong-direction head does not block.
    q = landing_queues.get(f)
    while q and len(el.onboard) < max_passengers:
        n = len(q)
        picked_one = False
        for _ in range(n):
            if not q:
                break
            if not _pickup_allowed_at_floor(q[0], el):
                q.rotate(-1)
                continue
            p = q.popleft()
            if not q:
                landing_queues.pop(f, None)
            p.picked_up_at = tick
            p.assigned_elevator = el.idx
            el.onboard[p.request.passenger_id] = p
            w = p.picked_up_at - p.request.time
            logger.info(
                "tick=%s event=PICKUP elevator=%s floor=%s passenger=%s dest=%s wait=%s",
                tick,
                el.idx,
                f,
                p.request.passenger_id,
                p.request.dest,
                w,
            )
            if request_journal_lines is not None:
                request_journal_lines.append(
                    _request_journal_row(
                        tick,
                        "PICKUP",
                        p.request.passenger_id,
                        p.request.time,
                        p.request.source,
                        p.request.dest,
                        el.idx,
                        str(w),
                        "",
                        "",
                        "ONBOARD",
                    )
                )
            picked_one = True
            break
        if not picked_one:
            break


def _format_position_row(tick: int, elevators: Sequence[Elevator]) -> str:
    floors = ",".join(str(e.floor) for e in elevators)
    return f"{tick},{floors}"


def simulate_one_tick(
    config: SimulationConfig,
    elevators: List[Elevator],
    passengers: List[Passenger],
    landing_queues: dict[int, deque[Passenger]],
    dispatcher_rr: List[int],
    t: int,
    incoming: Sequence[RequestInput],
    log_lines: List[str],
    request_journal_lines: Optional[List[str]] = None,
) -> None:
    if incoming:
        logger.debug("tick=%s phase=assign incoming=%s", t, len(incoming))
    for req in incoming:
        _validate_request(req, config)
        if req.time != t:
            raise ValueError(
                f"incoming request {req.passenger_id!r} has time={req.time} but tick is {t}"
            )
        # Shared landing queue (bank): any elevator with spare capacity may stop and pick up.
        p = Passenger(req, -1)
        passengers.append(p)
        landing_queues.setdefault(req.source, deque()).append(p)
        logger.info(
            "tick=%s event=ASSIGN_TO_LANDING passenger=%s src=%s dest=%s queue_floor=%s",
            t,
            req.passenger_id,
            req.source,
            req.dest,
            req.source,
        )
        if request_journal_lines is not None:
            request_journal_lines.append(
                _request_journal_row(
                    t,
                    "ASSIGN",
                    req.passenger_id,
                    req.time,
                    req.source,
                    req.dest,
                    -1,
                    "",
                    "",
                    "",
                    "QUEUED_AT_PLATFORM",
                )
            )

    for el in elevators:
        service_elevator(el, t, config.max_passengers, landing_queues, request_journal_lines)

    move_elevators(
        elevators,
        config.max_passengers,
        landing_queues,
        config.assignment_strategy,
        dispatcher_rr,
    )

    log_lines.append(_format_position_row(t, elevators))


def simulate_elevator_system(
    requests: Sequence[RequestInput],
    config: SimulationConfig,
) -> SimulationResult:
    """Discrete simulation from a list of :class:`RequestInput` rows and config."""
    return run_simulation(config, requests)


def run_simulation(
    config: SimulationConfig,
    requests: Sequence[RequestInput],
) -> SimulationResult:
    """Advance one tick: arrivals to landing queues, pickup/drop, move, snapshot."""

    sorted_req = sorted(requests, key=lambda r: (r.time, r.passenger_id))
    seen_ids: set[str] = set()
    for r in sorted_req:
        if r.passenger_id in seen_ids:
            raise ValueError(f"duplicate passenger_id: {r.passenger_id!r}")
        seen_ids.add(r.passenger_id)
    for r in sorted_req:
        _validate_request(r, config)

    elevators = [
        Elevator(
            idx=i,
            floor=config.initial_floor,
            direction=0,
            waiting={},
            onboard={},
        )
        for i in range(config.num_elevators)
    ]
    passengers: List[Passenger] = []
    next_idx = 0
    log_lines: List[str] = []
    journey: List[str] = []

    landing_queues: dict[int, deque[Passenger]] = defaultdict(deque)
    dispatcher_rr: List[int] = [0]
    t = 0
    while True:
        incoming: List[RequestInput] = []
        while next_idx < len(sorted_req) and sorted_req[next_idx].time == t:
            incoming.append(sorted_req[next_idx])
            next_idx += 1

        simulate_one_tick(
            config,
            elevators,
            passengers,
            landing_queues,
            dispatcher_rr,
            t,
            incoming,
            log_lines,
            request_journal_lines=journey,
        )

        all_released = next_idx >= len(sorted_req)
        all_delivered = (not passengers) or all(
            p.dropped_at is not None for p in passengers
        )
        if all_released and all_delivered:
            break

        t += 1
        if t > 10**7:
            raise RuntimeError("simulation exceeded tick limit — check inputs")

    return SimulationResult(
        passengers=passengers,
        position_log_lines=log_lines,
        request_journal_lines=journey,
    )


def format_position_log_header(num_elevators: int) -> str:
    return "time," + ",".join(f"elevator_{i}" for i in range(num_elevators))


def write_position_log_dynamic(path: str, lines: Sequence[str], num_elevators: int) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(format_position_log_header(num_elevators) + "\n")
        for line in lines:
            f.write(line + "\n")


def print_summary(
    passengers: Sequence[Passenger],
    out: TextIO | None = None,
) -> None:
    import sys

    out = out or sys.stdout
    waits = [p.wait_time for p in passengers]
    totals = [p.total_time for p in passengers]
    travels = [p.travel_time for p in passengers]
    if not waits:
        out.write("No passengers completed.\n")
        return

    def stats(vals: List[int]) -> Tuple[int, int, float]:
        return min(vals), max(vals), sum(vals) / len(vals)

    mn_w, mx_w, av_w = stats(waits)
    mn_t, mx_t, av_t = stats(totals)
    mn_tr, mx_tr, av_tr = stats(travels)
    out.write(f"Passengers: {len(passengers)}  wait min/max/avg: {mn_w}/{mx_w}/{av_w:.2f}\n")
    out.write(f"  travel min/max/avg: {mn_tr}/{mx_tr}/{av_tr:.2f}\n")
    out.write(f"  total min/max/avg: {mn_t}/{mx_t}/{av_t:.2f}  (total = wait + travel)\n")
    out.write(f"  sums: wait={sum(waits)} travel={sum(travels)} total={sum(totals)}\n")


def write_request_journal_dynamic(path: str, lines: Sequence[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(format_request_journal_header() + "\n")
        for line in lines:
            f.write(line + "\n")


def run_simulation_to_files(
    config: SimulationConfig,
    requests: Sequence[RequestInput],
    position_log_path: str,
    request_journal_path: str | None = None,
) -> SimulationResult:
    result = run_simulation(config, requests)
    write_position_log_dynamic(position_log_path, result.position_log_lines, config.num_elevators)
    if request_journal_path:
        write_request_journal_dynamic(request_journal_path, result.request_journal_lines)
    return result
