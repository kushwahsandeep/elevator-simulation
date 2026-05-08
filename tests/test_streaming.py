"""Streaming / random request generation."""

import random

from elevator.models import SimulationConfig
from elevator.streaming import random_incoming_for_tick


def test_random_incoming_is_marked_with_tick_time():
    cfg = SimulationConfig(num_floors=5, num_elevators=1, max_passengers=2, initial_floor=1)
    rng = random.Random(42)
    ctr = [0]
    reqs = random_incoming_for_tick(
        7, cfg, rng, arrival_probability=1.0, max_new_per_tick=1, id_counter=ctr
    )
    assert len(reqs) == 1
    assert reqs[0].time == 7
