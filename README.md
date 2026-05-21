## How to Run

**Requirements:** Python 3.10+ on your PATH. For the Web UI build, Node.js and npm are required (or use a checkout that already includes `web/dist/`).

**Setup (Windows)** — from the repository root:

```bat
scripts\setup.bat
```

Creates `.venv` when missing, upgrades `pip`, and installs `requirements.txt` and `requirements-api.txt`. If `pip` fails with SSL or certificate errors, the script retries with `--trusted-host` for PyPI hosts. When npm is available, the script also runs the web install/build step (see Web UI below).

**Setup (macOS / Linux)** — from the repository root:

```bash
chmod +x scripts/setup.sh scripts/setup-web.sh scripts/run-api.sh
./scripts/setup.sh
```

Creates `.venv` if needed, activates it for the run, and installs `requirements.txt` and `requirements-api.txt`. For SSL failures, use the `--trusted-host` guidance printed by the script or run `pip install` manually with the same flags.

**Activate the environment** for later commands:

```bash
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

**Manual setup** (if you do not use the scripts):

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |  macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt -r requirements-api.txt
```

If `pip install` fails with SSL errors:

```bash
pip install -r requirements.txt -r requirements-api.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
```

**CLI — batch simulation** — with the venv activated, from the repo root:

```bash
python main.py examples/sample_requests.csv -n 60 -e 4 -c 8
```

`-n` is the number of floors, `-e` the number of elevators, `-c` the max passengers per car. Use `--positions-log` and `--request-log` to set CSV output paths (defaults are `elevator_positions.csv` and `passenger_journey.csv`). Use `--log-level` to control logging (`INFO` by default).

Streaming mode (random traffic until you stop the process): add `--stream`. See `python main.py --help` for options.

**Web UI** — produce `web/dist/` once (from the repo root):

```bat
scripts\setup-web.bat
```

```bash
./scripts/setup-web.sh
```

Or: `cd web` then `npm install` and `npm run build`.

Start the API (repo root, venv activated):

```bat
scripts\run-api.bat
```

```bash
./scripts/run-api.sh
```

Or: `python -m uvicorn api.server:app --host 127.0.0.1 --port 8080`

Open **http://127.0.0.1:8080/** in the browser when `web/dist/` is present; API reference is at **http://127.0.0.1:8080/docs**.

## Unit tests (`tests/`)

Run from the repo root with the venv active: **`python -m pytest tests/`** (19 cases). They cover:

- **`test_simulation.py` — boarding and full runs:** Directional pickup (wrong-way waiter left at hall head while a compatible waiter behind boards; elevator moving opposite direction still boards a matching trip at queue head); **same-cabin polarity** (down-trip waiter skipped while an up-trip passenger is already onboard); single-passenger **wait/travel totals** and **floors travelled**; **no lookahead** (a far-future request does not change which car picks up an earlier passenger); **position log ticks** contiguous from zero; **`simulate_elevator_system`** vs **`run_simulation`** agreement on passengers, positions, and journey log; journey log shape (**DROPOFF** rows and **DELIVERED**); **`ValueError`** for out-of-range floors and **duplicate passenger IDs**; **max passengers per elevator** enforced (full car yields before everyone at the lobby is onboard; all riders still delivered); **`nearest`** dispatch moves only the closest car on the first step while others idle; **`SimulationConfig`** rejects an unknown **`assignment_strategy`**.
- **`test_scheduler.py` — dispatcher registry:** Unknown strategy **`get_assign_fn`** error; **`score`** alias maps to **`ScoreBased`**; **round-robin** assignment cycles elevators; **nearest** selects the elevator on the pickup floor when one is parked there; strategy helpers remain **independently instantiable**.
- **`test_streaming.py` — CLI-style RNG arrivals:** **`random_incoming_for_tick`** stamps **`RequestInput.time`** with the current simulation tick.

The FastAPI layer (`api/`) and WebSocket clients are exercised manually or via Swagger; there are no pytest modules for HTTP/WS in this repo.

## Time Spent

Approximately 6–8 hours across design, implementation, and testing.

## Assumptions and Trade-offs

- Single elevator bank; no door open/close time modeled
- One floor of travel per discrete time tick
- Passengers declare both source and destination at request time (destination dispatch)
- Position log captures end-of-tick elevator positions starting from tick 0
- Passengers join a **hall queue** at pickup floor; **`assignment_strategy`** (`nearest`, `round_robin`, **`score_based`**) selects which car is **dispatched toward** each nonempty landing each movement tick. **No lookahead**: batch runs only see requests whose time has arrived on the simulation clock at that tick (`--stream` behaves the same relative to ticks)
- Within pickup rules: **down-trips** do not board a car moving **up**; idle cars may board any trip direction; once the cabin carries passengers, new boarders must match the occupants’ declared trip polarity (either all **up-trips** with `dest > source` or all **down-trips** with `dest < source`)
- **SCAN over LOOK:** SCAN continues to the floor boundary before reversing rather than turning at the last scheduled stop
- **Dispatcher trade-off:** **`nearest`** minimises shaft distance first (ties by car index); on sparse traffic load can skew to one shaft. **`round_robin`** rotates dispatch among eligible cars; **`score_based`** combines distance, onboard load, and direction alignment—it is a heuristic whose weights materially affect imbalance vs passenger wait tails
- Duplicate passenger IDs raise a `ValueError` at input validation rather than silently overwriting

## What I'd Improve

- **Tune `score_based` weights** (distance vs load vs direction) against real distributions; optionally expose weights on CLI/API/UI
- **Zone-based scheduling:** partition floors into zones per elevator for skewed traffic (e.g. morning lobby rush)
- **Benchmarking harness:** run the same request set across strategies and compare min/max/avg wait and total shaft travel statistically
- **Richer realism:** dwell time per stop, stochastic arrivals modeled against clock time separately from tick pacing, explicit energy / reversal metrics alongside passenger SLAs
