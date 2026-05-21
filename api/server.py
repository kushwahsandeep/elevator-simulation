"""FastAPI app: batch REST + WebSocket tick replay (core stays import-only)."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from elevator.models import Elevator, RequestInput, SimulationConfig
from elevator.simulation import _validate_request, run_simulation, simulate_one_tick

from api.schemas import LiveStreamBody, SimConfigSchema, SimulateBatchBody, StreamSimBody


LIVE_WS_MAX_TICKS = 5_000_000

logger = logging.getLogger("api.server")


def configure_logging() -> None:
    """Route ``elevator`` and ``api`` loggers to stderr with sane defaults under uvicorn.

    Env:

    - ``SIM_API_LOG_LEVEL``: ``DEBUG``, ``INFO`` (default), ``WARNING``, …
    - ``SIM_API_TICK_DEBUG``: ``1`` / ``true`` — per-tick ``elevator.simulation`` debug lines
    """

    raw = os.environ.get("SIM_API_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, raw, logging.INFO)

    tick_dbg = os.environ.get("SIM_API_TICK_DEBUG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    # Child loggers propagate to ``elevator``; parent must accept DEBUG when tick debug is on.
    elevator_level = logging.DEBUG if tick_dbg else level

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    elev = logging.getLogger("elevator")
    elev.setLevel(elevator_level)
    elev.handlers.clear()
    h_el = logging.StreamHandler(sys.stderr)
    h_el.setLevel(elevator_level)
    h_el.setFormatter(formatter)
    elev.addHandler(h_el)
    elev.propagate = False

    api_pkg = logging.getLogger("api")
    api_pkg.setLevel(level)
    api_pkg.handlers.clear()
    h_api = logging.StreamHandler(sys.stderr)
    h_api.setLevel(level)
    h_api.setFormatter(formatter)
    api_pkg.addHandler(h_api)
    api_pkg.propagate = False


@asynccontextmanager
async def _lifespan(app: FastAPI):
    configure_logging()
    live_mod = int(os.environ.get("SIM_API_LOG_LIVE_TICK_MOD", "60") or "0")

    wd = _REPO_ROOT / "web" / "dist"
    if (wd / "index.html").is_file() and not (wd / "assets").is_dir():
        logger.warning(
            "%s exists but %s/assets/ is missing — the browser will get blank UI (404 on JS/CSS). "
            "Run scripts/setup-web.bat or ./scripts/setup-web.sh.",
            wd / "index.html",
            wd,
        )

    logger.info(
        "Elevator API ready — core logs: ASSIGN/PICKUP/DROPOFF (INFO). Env: "
        "SIM_API_LOG_LEVEL=DEBUG | SIM_API_TICK_DEBUG=1 (per-tick assign) | SIM_API_LOG_LIVE_TICK_MOD=%s (live heartbeat, 0=off)",
        live_mod,
    )
    yield


app = FastAPI(
    title="Elevator simulation API",
    version="1.0.0",
    description="Facade over ``elevator``: synchronous batch + realtime tick playback.",
    lifespan=_lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _config_from_schema(c: SimConfigSchema) -> SimulationConfig:
    init = min(max(1, c.initial_floor), c.num_floors)
    return SimulationConfig(
        num_floors=c.num_floors,
        num_elevators=c.num_elevators,
        max_passengers=c.max_passengers,
        initial_floor=init,
        assignment_strategy=c.assignment_strategy,
    )


def _to_domain(body: SimulateBatchBody) -> tuple[SimulationConfig, list[RequestInput]]:
    cfg = _config_from_schema(body.config)
    reqs = [
        RequestInput(time=r.time, passenger_id=r.id, source=r.source, dest=r.dest)
        for r in body.requests
    ]
    return cfg, reqs


def _spawn_random_arrivals(
    tick: int,
    cfg: SimulationConfig,
    rng: random.Random,
    *,
    max_new_per_tick: int,
    spawn_chance: float,
) -> list[RequestInput]:
    arrivals: list[RequestInput] = []
    if max_new_per_tick <= 0 or spawn_chance <= 0:
        return arrivals
    for _ in range(max_new_per_tick):
        if rng.random() >= spawn_chance:
            continue
        pk = rng.getrandbits(32)
        pid = f"rnd-{tick}-{pk & 0xFFFFFFFF:08x}"
        src = rng.randint(1, cfg.num_floors)
        dst = rng.randint(1, cfg.num_floors)
        for _guard in range(48):
            if dst != src:
                break
            dst = rng.randint(1, cfg.num_floors)
        else:
            dst = src + 1 if src < cfg.num_floors else src - 1
        arrivals.append(RequestInput(time=tick, passenger_id=pid, source=src, dest=dst))
    return arrivals


def _passenger_summaries(passengers):
    rows = []
    for p in passengers:
        wt = tt = tot = None
        if p.picked_up_at is not None:
            wt = p.picked_up_at - p.request.time
        if p.picked_up_at is not None and p.dropped_at is not None:
            tt = p.dropped_at - p.picked_up_at
            tot = p.dropped_at - p.request.time
        rows.append(
            {
                "id": p.request.passenger_id,
                "request_time": p.request.time,
                "source": p.request.source,
                "dest": p.request.dest,
                "assigned_elevator": p.assigned_elevator,
                "picked_up_at": p.picked_up_at,
                "dropped_at": p.dropped_at,
                "wait_ticks": wt,
                "travel_ticks": tt,
                "total_ticks": tot,
            }
        )
    return rows


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/simulate")
def simulate_batch(body: SimulateBatchBody):
    t0 = time.perf_counter()
    try:
        cfg, reqs = _to_domain(body)
        logger.info(
            "POST /simulate passengers=%s floors=%s elevators=%s capacity=%s assignment_strategy=%s",
            len(reqs),
            cfg.num_floors,
            cfg.num_elevators,
            cfg.max_passengers,
            cfg.assignment_strategy,
        )
        result = run_simulation(cfg, reqs)
    except ValueError as e:
        logger.warning("POST /simulate rejected: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "POST /simulate finished ticks=%s passengers=%s journal_rows=%s duration_ms=%.1f",
        len(result.position_log_lines),
        len(result.passengers),
        len(result.request_journal_lines),
        elapsed_ms,
    )

    rows = []
    ne = cfg.num_elevators
    for line in result.position_log_lines:
        parts = line.split(",")
        tick = int(parts[0])
        floors = [int(x) for x in parts[1 : 1 + ne]]
        rows.append({"tick": tick, "elevator_floors": floors})

    return {
        "config": body.config.model_dump(),
        "position_rows": rows,
        "passengers": _passenger_summaries(result.passengers),
        "journal_lines": result.request_journal_lines,
    }


@app.websocket("/ws/stream")
async def stream_ticks(websocket: WebSocket):
    await websocket.accept()
    t_wall0 = time.perf_counter()
    try:
        raw = await websocket.receive_json()
        body = StreamSimBody.model_validate(raw)
        cfg, reqs = _to_domain(body)
        logger.info(
            "ws/stream start passengers=%s floors=%s elevators=%s assignment_strategy=%s delay_ms=%s",
            len(reqs),
            cfg.num_floors,
            cfg.num_elevators,
            cfg.assignment_strategy,
            body.options.delay_ms,
        )
        t_sim0 = time.perf_counter()
        result = run_simulation(cfg, reqs)
        logger.info(
            "ws/stream run_simulation done total_ticks=%s passengers=%s journal_rows=%s sim_ms=%.1f",
            len(result.position_log_lines),
            len(result.passengers),
            len(result.request_journal_lines),
            (time.perf_counter() - t_sim0) * 1000,
        )
    except ValidationError as e:
        logger.warning("ws/stream validation failed on client payload: %s", e.errors())
        await websocket.send_json({"event": "error", "detail": e.errors().__str__()})
        await websocket.close(code=4400)
        return
    except ValueError as e:
        logger.warning("ws/stream rejected: %s", e)
        await websocket.send_json({"event": "error", "detail": str(e)})
        await websocket.close(code=4400)
        return
    except Exception as e:
        logger.exception("ws/stream unexpected error before replay: %s", e)
        await websocket.send_json({"event": "error", "detail": repr(e)})
        await websocket.close(code=4500)
        return

    opts = body.options
    nf, ne = cfg.num_floors, cfg.num_elevators
    total_ticks = len(result.position_log_lines)

    try:
        await websocket.send_json(
            {
                "event": "started",
                "num_floors": nf,
                "num_elevators": ne,
                "total_ticks": total_ticks,
                "journal_lines": result.request_journal_lines,
                "position_log_lines": result.position_log_lines,
                "passengers": _passenger_summaries(result.passengers),
                "assignment_strategy": body.config.assignment_strategy,
            }
        )

        last_tick = 0
        for line in result.position_log_lines:
            parts = line.split(",")
            tick = int(parts[0])
            last_tick = tick
            floors = [int(x) for x in parts[1 : 1 + ne]]
            await websocket.send_json(
                {"event": "tick", "tick": tick, "floors": floors, "total_ticks": total_ticks}
            )
            if opts.delay_ms > 0:
                await asyncio.sleep(opts.delay_ms / 1000.0)

        await websocket.send_json(
            {
                "event": "done",
                "last_tick": last_tick,
                "passengers": _passenger_summaries(result.passengers),
            }
        )
        logger.info(
            "ws/stream replay finished last_tick=%s wall_ms_since_accept=%.1f",
            last_tick,
            (time.perf_counter() - t_wall0) * 1000,
        )
    except asyncio.CancelledError:
        raise
    except RuntimeError:
        logger.debug("ws/stream replay RuntimeError (client likely gone)")


@app.websocket("/ws/live")
async def stream_live(websocket: WebSocket):
    """Infinite horizon: advance the clock each tick until the client disconnects.

    Arrivals: ``requests_bootstrap`` keyed by ``time``, then optional RNG from ``traffic``.
    """
    await websocket.accept()
    live_tick_mod = int(os.environ.get("SIM_API_LOG_LIVE_TICK_MOD", "60") or "0")
    body: LiveStreamBody | None = None
    try:
        raw = await websocket.receive_json()
        body = LiveStreamBody.model_validate(raw)
    except ValidationError as e:
        logger.warning("ws/live validation failed on client payload: %s", e.errors())
        await websocket.send_json({"event": "error", "detail": e.errors().__str__()})
        await websocket.close(code=4400)
        return
    except Exception as e:
        logger.exception("ws/live unexpected error reading config: %s", e)
        await websocket.send_json({"event": "error", "detail": repr(e)})
        await websocket.close(code=4500)
        return

    cfg = _config_from_schema(body.config)
    rng = random.Random(body.traffic.seed)

    bootstrap_reqs: list[RequestInput] = []
    try:
        for row in sorted(body.requests_bootstrap, key=lambda r: (r.time, r.id)):
            req = RequestInput(
                time=row.time, passenger_id=row.id, source=row.source, dest=row.dest
            )
            _validate_request(req, cfg)
            bootstrap_reqs.append(req)
    except ValueError as e:
        logger.warning("ws/live bootstrap rejected: %s", e)
        await websocket.send_json({"event": "error", "detail": str(e)})
        await websocket.close(code=4400)
        return

    pending = deque(bootstrap_reqs)
    elevators = [
        Elevator(
            idx=i,
            floor=cfg.initial_floor,
            direction=0,
            waiting={},
            onboard={},
        )
        for i in range(cfg.num_elevators)
    ]
    passengers: list = []
    landing_queues: dict[int, deque] = defaultdict(deque)
    dispatcher_rr: list[int] = [0]
    log_lines: list[str] = []
    journey: list[str] = []
    ne = cfg.num_elevators
    nf = cfg.num_floors
    opts = body.options

    logger.info(
        "ws/live starting floors=%s elevators=%s assignment_strategy=%s seed=%s "
        "max_new_per_tick=%s spawn_chance=%s bootstrap_requests=%s delay_ms=%s tick_log_every=%s",
        nf,
        ne,
        cfg.assignment_strategy,
        body.traffic.seed,
        body.traffic.max_new_per_tick,
        body.traffic.spawn_chance,
        len(bootstrap_reqs),
        opts.delay_ms,
        live_tick_mod or "disabled",
    )

    try:
        await websocket.send_json(
            {
                "event": "started",
                "live": True,
                "num_floors": nf,
                "num_elevators": ne,
                "total_ticks": 0,
                "journal_lines": [],
                "position_log_lines": [],
                "passengers": [],
                "traffic": body.traffic.model_dump(),
                "assignment_strategy": body.config.assignment_strategy,
            }
        )
    except (WebSocketDisconnect, RuntimeError):
        return

    try:
        t = 0
        while t < LIVE_WS_MAX_TICKS:
            incoming: list[RequestInput] = []
            while pending and pending[0].time < t:
                stale = pending.popleft()
                logger.warning(
                    "ws/live bootstrap passenger %r time=%s before live clock %s",
                    stale.passenger_id,
                    stale.time,
                    t,
                )
                await websocket.send_json(
                    {
                        "event": "error",
                        "detail": (
                            f"Bootstrap passenger {stale.passenger_id!r} has "
                            f"request.time={stale.time} before live clock {t}"
                        ),
                    }
                )
                await websocket.close(code=4400)
                return
            while pending and pending[0].time == t:
                incoming.append(pending.popleft())

            incoming.extend(
                _spawn_random_arrivals(
                    t,
                    cfg,
                    rng,
                    max_new_per_tick=body.traffic.max_new_per_tick,
                    spawn_chance=body.traffic.spawn_chance,
                )
            )

            if live_tick_mod > 0 and t > 0 and t % live_tick_mod == 0:
                logger.info(
                    "ws/live tick=%s incoming=%s passengers=%s journal_rows=%s pending_bootstrap=%s",
                    t,
                    len(incoming),
                    len(passengers),
                    len(journey),
                    len(pending),
                )

            jour_before = len(journey)
            try:
                simulate_one_tick(
                    cfg,
                    elevators,
                    passengers,
                    landing_queues,
                    dispatcher_rr,
                    t,
                    incoming,
                    log_lines,
                    request_journal_lines=journey,
                )
            except ValueError as e:
                logger.warning("ws/live simulate_one_tick failed at t=%s: %s", t, e)
                await websocket.send_json({"event": "error", "detail": str(e)})
                await websocket.close(code=4400)
                return

            jour_delta = journey[jour_before:]
            pos_line = log_lines[-1]
            parts = pos_line.split(",")
            floors = [int(parts[1 + i]) for i in range(ne)]

            tick_payload = {
                "event": "tick",
                "tick": t,
                "floors": floors,
                "live": True,
                "total_ticks": 0,
                "position_row": pos_line,
                "passengers": _passenger_summaries(passengers),
            }
            if jour_delta:
                tick_payload["journal_delta"] = jour_delta

            try:
                await websocket.send_json(tick_payload)
            except (WebSocketDisconnect, RuntimeError):
                break

            if opts.delay_ms > 0:
                await asyncio.sleep(opts.delay_ms / 1000.0)

            t += 1

    except WebSocketDisconnect:
        logger.info("ws/live client disconnected")


@app.get("/modes")
def modes():
    """Where to learn CLI vs API vs UI (see repo ``docs/multimode.md``)."""
    path = (_REPO_ROOT / "docs" / "multimode.md").resolve()
    return {"doc": str(path)}


# --- Built React UI (optional): same origin as API at http://127.0.0.1:8080/ -----------------
_UI_DIST = _REPO_ROOT / "web" / "dist"
_UI_INDEX = _UI_DIST / "index.html"

_UI_FALLBACK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Elevator simulation — UI</title>
</head>
<body style="font-family:system-ui,sans-serif;max-width:42rem;margin:2rem auto;line-height:1.55">
  <h1>Web UI bundle not present</h1>
  <p>The React app is built into <code>web/dist/</code>. This folder is missing here.</p>
  <p><strong>Build locally (needs Node.js + npm):</strong><br/>
     Windows: <code>scripts\\setup-web.bat</code> · macOS/Linux: <code>./scripts/setup-web.sh</code><br/>
     Then restart the API and open this page again.</p>
  <p><strong>No npm:</strong> use a checkout that includes a committed <code>web/dist/</code>, or call the API from <a href="/docs">/docs</a> (Swagger).</p>
</body>
</html>"""


if _UI_INDEX.is_file():
    # Serve the Vite bundle explicitly: mount "/" as StaticFiles can shadow or fight
    # framework routes on some Starlette/FastAPI versions. Only `/` and `/assets/*` are needed.
    _assets = _UI_DIST / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="ui-assets")

    @app.get("/", include_in_schema=False)
    async def _ui_index():
        return FileResponse(
            path=str(_UI_INDEX),
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )
else:

    @app.get("/", include_in_schema=False)
    async def _ui_placeholder():
        return HTMLResponse(content=_UI_FALLBACK_HTML, status_code=200)
