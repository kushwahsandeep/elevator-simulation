from __future__ import annotations

import argparse
import logging
import random
import sys

from pathlib import Path

from elevator.io import load_requests_from_csv
from elevator.models import SimulationConfig
from elevator.output_paths import prepare_positions_csv, prepare_requests_journal_csv
from elevator.simulation import print_summary, run_simulation_to_files
from elevator.streaming import run_streaming_until_interrupt


def _configure_logging(level: str) -> None:
    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=lvl,
        format="%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Discrete-time destination-dispatch elevator simulation",
    )
    p.add_argument(
        "requests_csv",
        nargs="?",
        default=None,
        help="CSV with header time,id,source,dest (not used with --stream)",
    )
    p.add_argument(
        "--stream",
        action="store_true",
        help="Random passengers until Ctrl+C, then drain (paced by simulation ticks or --burst-stream)",
    )
    p.add_argument("-n", "--floors", type=int, required=True, help="Number of floors (1..n)")
    p.add_argument("-e", "--elevators", type=int, required=True, help="Number of elevators")
    p.add_argument(
        "-c",
        "--capacity",
        type=int,
        required=True,
        help="Max passengers per elevator",
    )
    p.add_argument(
        "--initial-floor",
        type=int,
        default=1,
        help="Starting floor for all elevators (default 1)",
    )
    p.add_argument(
        "--positions-log",
        default="elevator_positions.csv",
        help="CSV path: one row per simulation tick with elevator floors.",
    )
    p.add_argument(
        "--request-log",
        default="passenger_journey.csv",
        help="CSV path: per-request lifecycle (ASSIGN / PICKUP / DROPOFF) with wait_time, "
        "travel_time, total_time, and status columns. Deleted/truncated each run.",
    )
    p.add_argument(
        "--no-request-log",
        action="store_true",
        help="Skip writing the per-request journey CSV (saves disk for long demos). INFO logs unchanged.",
    )
    p.add_argument(
        "--no-positions-log",
        action="store_true",
        help="With --stream: skip writing the position CSV (defaults to writing it). "
        "Use for long demos if the file grows too large.",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        help="Python log level: DEBUG, INFO, WARNING, ... (default INFO)",
    )
    p.add_argument("--seed", type=int, default=None, help="RNG seed for --stream")
    p.add_argument(
        "--arrival-p",
        type=float,
        default=0.25,
        help="With --burst-stream: per-slot probability of a new request (0..1)",
    )
    p.add_argument(
        "--max-per-tick",
        type=int,
        default=2,
        help="With --burst-stream: max random draws per simulation tick",
    )
    p.add_argument(
        "--print-ticks",
        action="store_true",
        help="Print every CSV tick row to stdout (very noisy)",
    )
    p.add_argument(
        "--inject-every-ticks",
        type=int,
        default=100,
        help="With --stream (paced mode, default): add one random passenger every N **simulation** ticks (no wall-clock time).",
    )
    p.add_argument(
        "--burst-stream",
        action="store_true",
        help="Stress: random arrivals every *simulation tick* (uses --arrival-p / --max-per-tick; can create huge logs).",
    )
    p.add_argument(
        "--assignment-strategy",
        default="nearest",
        choices=["nearest", "round_robin", "score_based"],
        help="Hall->car dispatcher: nearest (min distance, tie-break car index), round_robin, or score_based",
    )
    p.add_argument(
        "--sleep-after-request",
        type=float,
        default=0.0,
        help="With --stream only: real-time seconds to sleep after each *new* passenger is added "
        "(total sleep = value x number of passengers added that tick). Default 0 (full speed). Demo only.",
    )
    args = p.parse_args(argv)

    if args.stream and args.inject_every_ticks < 1:
        p.error("--inject-every-ticks must be >= 1")
    if args.stream and args.sleep_after_request < 0:
        p.error("--sleep-after-request must be >= 0")

    _configure_logging(args.log_level)

    config = SimulationConfig(
        num_floors=args.floors,
        num_elevators=args.elevators,
        max_passengers=args.capacity,
        initial_floor=args.initial_floor,
        assignment_strategy=args.assignment_strategy,
    )
    if args.stream:
        rng = random.Random(args.seed)
        pos_path: str | None = None if args.no_positions_log else prepare_positions_csv(
            args.positions_log
        )
        journal_path: str | None = (
            None if args.no_request_log else prepare_requests_journal_csv(args.request_log)
        )
        result = run_streaming_until_interrupt(
            config,
            rng=rng,
            arrival_probability=args.arrival_p,
            max_new_per_tick=args.max_per_tick,
            position_log_path=pos_path,
            request_journal_path=journal_path,
            tick_out=sys.stdout if args.print_ticks else None,
            inject_every_ticks=args.inject_every_ticks,
            burst_stream=args.burst_stream,
            skip_first_tick=False,
            sleep_seconds_per_new_request=args.sleep_after_request,
        )
        print_summary(result.passengers)
        if pos_path:
            print(f"Wrote streaming position CSV (absolute): {Path(pos_path).resolve()}", file=sys.stdout)
        else:
            print(
                "Position CSV skipped (--no-positions-log). "
                "Interactive logs (ASSIGN/PICKUP/DROPOFF) still print to this terminal.",
                file=sys.stdout,
            )
        if journal_path:
            print(
                f"Wrote request journey CSV (absolute): {Path(journal_path).resolve()}",
                file=sys.stdout,
            )
        else:
            print(
                "Request journey CSV skipped (--no-request-log). Event lines still appear in logging.",
                file=sys.stdout,
            )
        return 0

    if not args.requests_csv:
        p.error("requests_csv is required unless you pass --stream")
    out_csv = prepare_positions_csv(args.positions_log)
    journey_csv = None if args.no_request_log else prepare_requests_journal_csv(args.request_log)
    result = run_simulation_to_files(
        config,
        load_requests_from_csv(args.requests_csv),
        out_csv,
        request_journal_path=journey_csv,
    )
    print_summary(result.passengers)
    print(f"Wrote position CSV (absolute): {Path(out_csv).resolve()}", file=sys.stdout)
    if journey_csv:
        print(f"Wrote request journey CSV (absolute): {Path(journey_csv).resolve()}", file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
