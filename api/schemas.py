from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AssignmentStrategyName = Literal["nearest", "round_robin", "score_based"]


class SimConfigSchema(BaseModel):
    num_floors: int = Field(..., ge=1)
    num_elevators: int = Field(..., ge=1)
    max_passengers: int = Field(..., ge=1)
    initial_floor: int = Field(1, ge=1)
    assignment_strategy: AssignmentStrategyName = Field(
        "nearest",
        description="Hall→car dispatch each movement tick: nearest, round_robin, or score_based.",
    )


class RequestRow(BaseModel):
    time: int = Field(..., ge=0)
    id: str = Field(..., min_length=1)
    source: int
    dest: int


class SimulateBatchBody(BaseModel):
    config: SimConfigSchema
    requests: list[RequestRow]


class StreamOptions(BaseModel):
    """Throttle between ticks on the websocket (wall clock); does not affect the model."""

    delay_ms: float = Field(280, ge=0, le=10_000)


class StreamSimBody(SimulateBatchBody):
    options: StreamOptions = Field(default_factory=StreamOptions)


class LiveTrafficParams(BaseModel):
    """Optional stochastic riders each tick during ``/ws/live`` (runs after bootstrap dequeue)."""

    spawn_chance: float = Field(
        0.35,
        ge=0,
        le=1,
        description="Independent Bernoulli per slot each tick (up to max_new_per_tick slots).",
    )
    max_new_per_tick: int = Field(4, ge=0, le=40)
    seed: int | None = None


class LiveStreamBody(BaseModel):
    """`/ws/live` payload: infinite tick stream until disconnect; pacing uses ``options.delay_ms``.

    Passengers arrive from ``requests_bootstrap`` keyed by simulation ``time``, plus optional RNG
    from ``traffic`` (set ``spawn_chance`` or ``max_new_per_tick`` to 0 to disable).
    Extra JSON keys are ignored.
    """

    model_config = {"extra": "ignore"}

    config: SimConfigSchema
    traffic: LiveTrafficParams = Field(default_factory=LiveTrafficParams)
    options: StreamOptions = Field(default_factory=StreamOptions)
    requests_bootstrap: list[RequestRow] = Field(default_factory=list)
