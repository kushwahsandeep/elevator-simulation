from __future__ import annotations

import csv
import logging
from collections import deque
from dataclasses import dataclass, field
from io import StringIO
from typing import Callable, List, Optional, Sequence, TextIO, Tuple

from .models import Elevator, Passenger, RequestInput, SimulationConfig
from .movement import (
    move_one_floor,
    scan_next_target,
    stop_floors_for_elevator,
    update_direction_after_move,
)
from .scheduler import NearestCar

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


def service_elevator(
    el: Elevator,
    tick: int,
    max_passengers: int,
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

    q = el.waiting.get(f)
    while q and len(el.onboard) < max_passengers:
        p = q.popleft()
        if not q:
            el.waiting.pop(f, None)
        p.picked_up_at = tick
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


def _format_position_row(tick: int, elevators: Sequence[Elevator]) -> str:
    floors = ",".join(str(e.floor) for e in elevators)
    return f"{tick},{floors}"


def move_elevators(elevators: List[Elevator], max_passengers: int) -> None:
    for el in elevators:
        stops = stop_floors_for_elevator(el, max_passengers)
        if not stops:
            el.direction = 0
            continue
        if el.direction == 0:
            t_up = scan_next_target(el.floor, stops, 1)
            t_dn = scan_next_target(el.floor, stops, -1)
            assert t_up is not None and t_dn is not None
            du = abs(t_up - el.floor)
            dd = abs(t_dn - el.floor)
            if du < dd or (du == dd and t_up >= el.floor):
                el.direction = 1 if t_up >= el.floor else -1
            else:
                el.direction = -1 if t_dn <= el.floor else 1

        target = scan_next_target(el.floor, stops, el.direction)
        assert target is not None
        new_floor, _ = move_one_floor(el.floor, target)
        el.floor = new_floor
        stops_after = stop_floors_for_elevator(el, max_passengers)
        if stops_after:
            el.direction = update_direction_after_move(new_floor, stops_after, el.direction)
        else:
            el.direction = 0


def simulate_one_tick(
    config: SimulationConfig,
    elevators: List[Elevator],
    passengers: List[Passenger],
    t: int,
    incoming: Sequence[RequestInput],
    assign_fn: Callable[[RequestInput, List[Elevator]], int],
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
        e_idx = assign_fn(req, elevators)
        if not 0 <= e_idx < len(elevators):
            raise ValueError("assign() returned invalid elevator index")
        p = Passenger(req, e_idx)
        passengers.append(p)
        elevators[e_idx].waiting.setdefault(req.source, deque()).append(p)
        logger.info(
            "tick=%s event=ASSIGN elevator=%s passenger=%s src=%s dest=%s queue_floor=%s",
            t,
            e_idx,
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
                    e_idx,
                    "",
                    "",
                    "",
                    "QUEUED_AT_PLATFORM",
                )
            )

    for el in elevators:
        service_elevator(el, t, config.max_passengers, request_journal_lines)

    move_elevators(elevators, config.max_passengers)

    log_lines.append(_format_position_row(t, elevators))


def simulate_elevator_system(
    requests: Sequence[RequestInput],
    config: SimulationConfig,
    assign: Callable[[RequestInput, List[Elevator]], int] | None = None,
) -> SimulationResult:
    """Discrete simulation from a list of :class:`RequestInput` rows and config."""
    return run_simulation(config, requests, assign=assign)


def run_simulation(
    config: SimulationConfig,
    requests: Sequence[RequestInput],
    assign: Callable[[RequestInput, List[Elevator]], int] | None = None,
) -> SimulationResult:
    """Advance one tick at a time: assign -> service/move -> snapshot."""
    assign_fn = assign or NearestCar().assign
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
            t,
            incoming,
            assign_fn,
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
