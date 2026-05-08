## How to Run

**First-time setup (recommended):** Requires **Python 3.10+** on your PATH.

On **Windows**, from the project root (you can double‑click the file in Explorer or run in Command Prompt):

```bat
scripts\setup.bat
```

This creates **`.venv`** (if missing), upgrades `pip`, and installs **`requirements.txt`**. If install fails with SSL or certificate issues (common behind a corporate proxy), the script retries using `--trusted-host pypi.org --trusted-host files.pythonhosted.org`.

On **macOS / Linux**:

```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

This creates **`.venv`** if needed, activates it for the script’s run, and installs dependencies. If `pip` fails with SSL/proxy errors, the script prints the same `--trusted-host …` command you can run manually.

Activate the environment when you work in the repo:

```bash
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

The scripts are optional: you can recreate the same layout with the manual commands below.

**Setup (manual):**

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

If `pip install` fails with SSL errors, try:

```bash
pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
```

**Run simulation:**

```bash
python main.py examples/sample_requests.csv -n 60 -e 4 -c 8
```

Flags: `-n` floors, `-e` elevators, `-c` capacity per elevator, `--positions-log` output CSV path.

**Programmatic API:**

```python
from elevator import RequestInput, SimulationConfig, simulate_elevator_system

result = simulate_elevator_system(
    [RequestInput(0, "p1", 1, 51), RequestInput(10, "p2", 20, 1)],
    SimulationConfig(num_floors=60, num_elevators=4, max_passengers=8),
)
```

**Run tests:**

```bash
python -m pytest tests/ -v
```

## Time Spent

Approximately 6–8 hours across design, implementation, and testing.

## Assumptions and Trade-offs

- Single elevator bank; no door open/close time modeled
- One floor of travel per discrete time tick
- Passengers declare both source and destination at request time (destination dispatch)
- Position log captures end-of-tick elevator positions starting from tick 0
- Elevators are assigned immediately at request time — no lookahead into future requests
- **SCAN over LOOK:** SCAN continues to the floor boundary before reversing rather than turning at the last scheduled stop. Simpler to reason about and sufficient for the request volumes in scope.
- **Nearest car over round robin:** Nearest car minimises expected wait time on sparse traffic. Round robin distributes load more evenly but produces higher average wait. On sparse multi-elevator runs, nearest car can concentrate trips on one elevator — this is a known trade-off noted in analysis of the position log output.
- Duplicate passenger IDs raise a ValueError at input validation rather than silently overwriting

## What I'd Improve

- **Scoring-based assignment:** replace nearest car with a weighted score combining distance, current load, and direction alignment. The `AssignmentStrategy` Protocol in `elevator/scheduler.py` is already in place to support alternative schedulers without touching the core simulation loop.
- **Zone-based scheduling:** partition floors into zones per elevator for skewed traffic patterns (e.g. morning rush concentrated on floor 1). Would significantly reduce load imbalance visible on sparse multi-elevator runs.
- **Benchmarking harness:** run multiple scheduling strategies against the same request set and compare min/max/avg wait and total distance — this would make the algorithm trade-offs quantitative rather than qualitative.
- **Capacity-aware assignment:** current nearest car does not penalise elevators near capacity. A scoring approach would naturally deprioritise full or near-full cars.
