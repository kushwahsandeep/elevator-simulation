# HTTP / WebSocket façade

**Install (no separate `pip install` step):** run **`scripts\setup.bat`** (Windows) or **`./scripts/setup.sh`** (macOS/Linux) from the repo root. That installs **`requirements.txt`** and **`requirements-api.txt`** with the same TLS retries as the rest of the project (see **`docs/multimode.md`** if setup fails).

**Run the server (recommended):** use the launcher so the working directory is always the **repository root** (otherwise Python cannot import the **`api`** package):

- **Windows:** `scripts\run-api.bat` (works from any folder, e.g. `Concepts\scripts`)
- **macOS/Linux:** `./scripts/run-api.sh`

Manual alternative **after** `cd` to the repo root with **`.venv`** active:

```bash
python -m uvicorn api.server:app --reload --host 127.0.0.1 --port 8080
```

**Windows:** If you see **`WinError 10013`** binding a port, another process may own it or it may be in an [excluded port range](https://learn.microsoft.com/en-us/troubleshoot/developer/webapps/iis/www-administration-management/using-netsh-http). Try a different `--port` (this project defaults docs to **8080** instead of 8000 for that reason).

**Server logging (stderr):** On startup the API attaches handlers so **`elevator.*`** emits **INFO** passenger events (**ASSIGN_TO_LANDING**, **PICKUP**, **DROPOFF**) instead of disappearing under uvicorn’s defaults.

| Env | Meaning |
|-----|--------|
| `SIM_API_LOG_LEVEL` | `DEBUG`, `INFO` (default), `WARNING`, … — applies to **`api`**; **`elevator`** uses the same unless `SIM_API_TICK_DEBUG` boosts it |
| `SIM_API_TICK_DEBUG` | `1` / `true` — enables **`elevator.simulation`** tick assignment **DEBUG** lines |
| `SIM_API_LOG_LIVE_TICK_MOD` | For **`/ws/live`**, log a heartbeat every *N* simulation ticks (**default `60`**, **`0`** to disable only the API heartbeat — core events still log when passengers move) |

Open **http://127.0.0.1:8080/docs** · same server serves the built UI at **http://127.0.0.1:8080/** when **`web/dist/`** exists · see **`docs/multimode.md`** for CLI / API / UI overview.
