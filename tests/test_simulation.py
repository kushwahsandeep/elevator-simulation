"""Tests for elevator simulation."""

from collections import deque

import pytest

from elevator.models import Elevator, Passenger, RequestInput, SimulationConfig
from elevator.simulation import run_simulation, service_elevator, simulate_elevator_system


def test_directional_pickup_skips_wrong_direction_head():
    """Up-bound car skips a down-trip at queue head but may board a compatible waiter behind."""
    down_waiter = Passenger(RequestInput(0, "want_down", 5, 4), assigned_elevator=-1)
    up_goer = Passenger(RequestInput(0, "want_up", 5, 10), assigned_elevator=-1)
    landing_queues: dict[int, deque[Passenger]] = {5: deque([down_waiter, up_goer])}
    el = Elevator(idx=0, floor=5, direction=1, waiting={}, onboard={})
    service_elevator(el, tick=42, max_passengers=4, landing_queues=landing_queues, request_journal_lines=None)
    assert "want_up" in el.onboard
    assert landing_queues.get(5) == deque([down_waiter])
    assert len(el.onboard) == 1


def test_up_trip_at_head_when_lift_moves_down_is_boarded_without_rotation():
    up_only = Passenger(RequestInput(3, "up_only", 2, 9), assigned_elevator=-1)
    landing_queues: dict[int, deque[Passenger]] = {2: deque([up_only])}
    el = Elevator(idx=0, floor=2, direction=-1, waiting={}, onboard={})
    service_elevator(el, tick=9, max_passengers=4, landing_queues=landing_queues, request_journal_lines=None)

    assert "up_only" in el.onboard
    assert 2 not in landing_queues


def test_non_empty_cabin_skips_opposite_declared_trip_at_head():
    """Cannot mix up-trips and down-trips while anyone remains onboard."""
    onboard_up = Passenger(RequestInput(0, "already_up", 4, 10), assigned_elevator=0)
    onboard_up.picked_up_at = 1
    down_waiter = Passenger(RequestInput(0, "want_down", 5, 2), assigned_elevator=-1)
    landing_queues: dict[int, deque[Passenger]] = {5: deque([down_waiter])}
    el = Elevator(idx=0, floor=5, direction=0, waiting={}, onboard={onboard_up.request.passenger_id: onboard_up})
    service_elevator(el, tick=9, max_passengers=4, landing_queues=landing_queues, request_journal_lines=None)
    assert list(el.onboard.keys()) == ["already_up"]
    assert landing_queues.get(5) == deque([down_waiter])


def test_single_passenger_total_time_equals_floors_traveled():
    cfg = SimulationConfig(num_floors=5, num_elevators=1, max_passengers=4, initial_floor=1)
    reqs = [RequestInput(0, "p", 1, 4)]
    res = run_simulation(cfg, reqs)
    assert len(res.passengers) == 1
    p = res.passengers[0]
    assert p.wait_time == 0
    assert p.total_time == 3


def test_future_request_in_file_does_not_change_who_picks_passenger_up():
    """No lookahead: elevator that serves an early request must not change when later requests exist."""
    cfg = SimulationConfig(num_floors=10, num_elevators=2, max_passengers=4, initial_floor=1)
    only_first = [RequestInput(0, "x", 2, 5)]
    with_future = [
        RequestInput(0, "x", 2, 5),
        RequestInput(100, "y", 9, 1),
    ]
    a = run_simulation(cfg, only_first).passengers[0].assigned_elevator
    b = run_simulation(cfg, with_future).passengers[0].assigned_elevator
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


def test_nearest_dispatches_one_car_toward_hall_others_stay_idle_first_move():
    cfg = SimulationConfig(
        num_floors=100,
        num_elevators=5,
        max_passengers=4,
        initial_floor=1,
        assignment_strategy="nearest",
    )
    reqs = [RequestInput(0, "a", 90, 92)]
    res = run_simulation(cfg, reqs)
    parts = res.position_log_lines[0].split(",")
    floors = [int(x) for x in parts[1:]]
    assert floors[0] == 2 and floors[1:] == [1, 1, 1, 1]


def test_invalid_assignment_strategy_on_config_raises():
    with pytest.raises(ValueError, match="assignment_strategy"):
        SimulationConfig(
            num_floors=5,
            num_elevators=2,
            max_passengers=2,
            assignment_strategy="invalid",
        )