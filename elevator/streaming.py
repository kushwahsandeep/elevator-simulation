from __future__ import annotations

import logging
import random
import sys
import time
from collections import defaultdict, deque
from typing import List, Optional, TextIO

from .models import Elevator, Passenger, RequestInput, SimulationConfig
from .simulation import (
    SimulationResult,
    format_position_log_header,
    format_request_journal_header,
    simulate_one_tick,
)

logger = logging.getLogger(__name__)


def random_incoming_for_tick(
    t: int,
    config: SimulationConfig,
    rng: random.Random,
    *,
    arrival_probability: float,
    max_new_per_tick: int,
    id_counter: List[int],
) -> List[RequestInput]:
    """Bernoulli arrivals at simulation time ``t`` (never future-dated requests)."""
    if max_new_per_tick < 0:
        raise ValueError("max_new_per_tick must be >= 0")
    if not 0.0 <= arrival_probability <= 1.0:
        raise ValueError("arrival_probability must be in [0, 1]")
    out: List[RequestInput] = []
    n = config.num_floors
    for _ in range(max_new_per_tick):
        if rng.random() >= arrival_probability:
            continue
        src = rng.randint(1, n)
        dest = rng.randint(1, n)
        while dest == src:
            dest = rng.randint(1, n)
        id_counter[0] += 1
        pid = f"gen_{id_counter[0]}"
        out.append(RequestInput(time=t, passenger_id=pid, source=src, dest=dest))
    return out


def one_random_request(
    t: int,
    config: SimulationConfig,
    rng: random.Random,
    id_counter: List[int],
) -> RequestInput:
    """One random ``RequestInput`` with ``time=t``."""
    n = config.num_floors
    src = rng.randint(1, n)
    dest = rng.randint(1, n)
    while dest == src:
        dest = rng.randint(1, n)
    id_counter[0] += 1
    pid = f"gen_{id_counter[0]}"
    return RequestInput(time=t, passenger_id=pid, source=src, dest=dest)


def _should_inject_paced(
    t: int,
    inject_every_ticks: int,
    skip_first_tick: bool,
) -> bool:
    """True when paced mode should inject at tick ``t``."""
    if inject_every_ticks < 1:
        raise ValueError("inject_every_ticks must be >= 1")
    if t % inject_every_ticks != 0:
        return False
    if t == 0 and skip_first_tick:
        return False
    return True


def run_streaming_until_interrupt(
    config: SimulationConfig,
    *,
    rng: random.Random,
    arrival_probability: float,
    max_new_per_tick: int,
    position_log_path: Optional[str] = None,
    request_journal_path: Optional[str] = None,
    tick_out: Optional[TextIO] = None,
    inject_every_ticks: int = 100,
    burst_stream: bool = False,
    skip_first_tick: bool = False,
    sleep_seconds_per_new_request: float = 0.0,
) -> SimulationResult:
    """Run until Ctrl+C (stop generating), then simulate until everyone is dropped off."""

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
    landing_queues: dict[int, deque[Passenger]] = defaultdict(deque)
    dispatcher_rr: List[int] = [0]
    log_lines: List[str] = []
    journal_lines: Optional[List[str]] = [] if request_journal_path else None
    id_counter = [0]
    log_file = open(position_log_path, "w", encoding="utf-8") if position_log_path else None
    journal_file = (
        open(request_journal_path, "w", encoding="utf-8") if request_journal_path else None
    )
    journal_flushed = 0
    try:
        if log_file:
            log_file.write(format_position_log_header(config.num_elevators) + "\n")
        if journal_file:
            journal_file.write(format_request_journal_header() + "\n")

        t = 0
        cancelled = False

        while True:
            incoming: List[RequestInput] = []
            if not cancelled:
                try:
                    if burst_stream:
                        incoming = random_incoming_for_tick(
                            t,
                            config,
                            rng,
                            arrival_probability=arrival_probability,
                            max_new_per_tick=max_new_per_tick,
                            id_counter=id_counter,
                        )
                    else:
                        if _should_inject_paced(
                            t,
                            inject_every_ticks,
                            skip_first_tick=skip_first_tick,
                        ):
                            req = one_random_request(t, config, rng, id_counter)
                            incoming = [req]
                            logger.info(
                                "tick=%s event=NEW_REQUEST passenger=%s src=%s dest=%s",
                                t,
                                req.passenger_id,
                                req.source,
                                req.dest,
                            )
                except KeyboardInterrupt:
                    cancelled = True
                    sys.stdout.write(
                        "\nStopping random generator (Ctrl+C). "
                        "Draining in-flight passengers…\n"
                    )

            if sleep_seconds_per_new_request > 0 and incoming:
                time.sleep(sleep_seconds_per_new_request * len(incoming))

            simulate_one_tick(
                config,
                elevators,
                passengers,
                landing_queues,
                dispatcher_rr,
                t,
                incoming,
                log_lines,
                request_journal_lines=journal_lines,
            )

            if journal_file is not None and journal_lines is not None:
                while journal_flushed < len(journal_lines):
                    journal_file.write(journal_lines[journal_flushed] + "\n")
                    journal_flushed += 1

            line = log_lines[-1]
            if log_file:
                log_file.write(line + "\n")
            if tick_out is not None:
                tick_out.write(line + "\n")

            if cancelled:
                all_delivered = (not passengers) or all(
                    p.dropped_at is not None for p in passengers
                )
                if all_delivered:
                    break

            t += 1
            if t > 10**7:
                raise RuntimeError("streaming simulation exceeded tick limit")
        logger.info(
            "streaming done last_tick=%s passengers=%s",
            t,
            len(passengers),
        )
    finally:
        if log_file:
            log_file.close()
        if journal_file:
            journal_file.close()

    return SimulationResult(
        passengers=passengers,
        position_log_lines=log_lines,
        request_journal_lines=journal_lines or [],
    )
