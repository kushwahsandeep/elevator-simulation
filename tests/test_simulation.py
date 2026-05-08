"""Tests for elevator simulation."""

import pytest

from elevator.models import RequestInput, SimulationConfig
from elevator.scheduler import NearestCar
from elevator.simulation import run_simulation, simulate_elevator_system


def test_single_passenger_total_time_equals_floors_traveled():
    cfg = SimulationConfig(num_floors=5, num_elevators=1, max_passengers=4, initial_floor=1)
    reqs = [RequestInput(0, "p", 1, 4)]
    res = run_simulation(cfg, reqs)
    assert len(res.passengers) == 1
    p = res.passengers[0]
    assert p.wait_time == 0
    assert p.total_time == 3


def test_future_request_in_file_does_not_change_first_assignment():
    """No-lookahead: assignment at t=0 must not depend on a request with time>0."""
    cfg = SimulationConfig(num_floors=10, num_elevators=2, max_passengers=4, initial_floor=1)
    only_first = [RequestInput(0, "x", 2, 5)]
    with_future = [
        RequestInput(0, "x", 2, 5),
        RequestInput(100, "y", 9, 1),
    ]
    a = run_simulation(cfg, only_first, assign=NearestCar().assign).passengers[0].assigned_elevator
    b = run_simulation(cfg, with_future, assign=NearestCar().assign).passengers[0].assigned_elevator
    assert a == b


def test_log_timestamps_contiguous_from_zero():
    cfg = SimulationConfig(num_floors=3, num_elevators=2, max_passengers=2, initial_floor=1)
    reqs = [RequestInput(0, "p", 1, 2)]
    res = run_simulation(cfg, reqs)
    times = [int(line.split(",")[0]) for line in res.position_log_lines]
    assert times[0] == 0
    assert times == list(range(len(times)))


def test_simulate_elevator_system_matches_run_simulation():
    cfg = SimulationConfig(num_floors=4, num_elevators=2, max_passengers=2, initial_floor=1)
    reqs = [
        RequestInput(0, "a", 1, 3),
        RequestInput(1, "b", 2, 4),
    ]
    a = simulate_elevator_system(reqs, cfg)
    b = run_simulation(cfg, reqs)
    assert len(a.passengers) == len(b.passengers)
    assert a.position_log_lines == b.position_log_lines
    assert a.request_journal_lines == b.request_journal_lines


def test_request_journal_three_rows_per_completed_passenger():
    cfg = SimulationConfig(num_floors=5, num_elevators=1, max_passengers=4, initial_floor=1)
    reqs = [
        RequestInput(0, "p1", 1, 4),
        RequestInput(0, "p2", 2, 3),
    ]
    res = run_simulation(cfg, reqs)
    assert len(res.request_journal_lines) == 6
    drop_rows = [ln for ln in res.request_journal_lines if ",DROPOFF," in ln]
    assert len(drop_rows) == 2
    assert all("DELIVERED" in ln for ln in drop_rows)


def test_invalid_floor_raises():
    cfg = SimulationConfig(num_floors=2, num_elevators=1, max_passengers=1, initial_floor=1)
    bad = [RequestInput(0, "p", 1, 99)]
    with pytest.raises(ValueError):
        run_simulation(cfg, bad)


def test_duplicate_passenger_id_raises():
    cfg = SimulationConfig(num_floors=5, num_elevators=1, max_passengers=4, initial_floor=1)
    requests = [
        RequestInput(0, "p1", 1, 5),
        RequestInput(1, "p1", 2, 4),
    ]
    with pytest.raises(ValueError, match="duplicate passenger_id"):
        run_simulation(cfg, requests)


def test_capacity_enforced():
    """Full car must leave for drop-off even when more passengers wait at the current floor."""
    cfg = SimulationConfig(num_floors=10, num_elevators=1, max_passengers=2, initial_floor=1)
    requests = [RequestInput(0, f"p{i}", 1, 10) for i in range(3)]
    res = run_simulation(cfg, requests)
    assert len(res.passengers) == 3
    assert all(p.dropped_at is not None for p in res.passengers)
