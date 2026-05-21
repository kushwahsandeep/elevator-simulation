# Running the simulator: CLI, API, and Web UI

The **simulation core** lives in the `elevator/` package. You can drive it in three ways; only the **CLI** touches `main.py` directly. The **API** and **UI** are optional layers that import the same core.

## 1. CLI (batch CSV)

From the repo root with `.venv` activated:

```bash
python main.py examples/sample_requests.csv -n 60 -e 4 -c 8
```

Flags: `-n` floors, `-e` elevators, `-c` capacity, `--positions-log` / `--request-log` paths, `--stream` for random traffic (see `main.py --help`).

## 2. HTTP API (FastAPI)

**Install Python deps (CLI core + pytest + FastAPI):** run the setup script once from the repo — no manual `pip install` required for normal use.

**Windows:** `scripts\setup.bat`  

**macOS / Linux:**

```bash
chmod +x scripts/setup.sh && ./scripts/setup.sh
```

This creates **`.venv`** (if missing), upgrades `pip`, and installs **`requirements.txt`** then **`requirements-api.txt`**. If PyPI TLS fails (corporate inspection), drop **`ca-bundle.crt`** in the repository root — the scripts retry install using that bundle (then trusted-hosts only). Troubleshooting-only notes (pip.ini, key PEM pitfalls) → **below**.

Start the API **from the repository root with `.venv` active**, or use **`scripts/run-api.bat`** / **`./scripts/run-api.sh`** so the process always starts in the project root (required for `import api`).

```bash
python -m uvicorn api.server:app --reload --host 127.0.0.1 --port 8080
```

On **Windows**, binding **`8000`** often hits **`WinError 10013`** (port excluded or in use); **`8080`** is the default in these docs to avoid that.

- **Swagger UI:** [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs)
- **`GET /health`** — liveness
- **`POST /simulate`** — JSON body `{ "config": {...}, "requests": [...] }` returns full `position_rows` + `passengers` in one shot
- **`GET /modes`** — path hint to this file
- **WebSocket `ws://…/ws/stream`** — send the same JSON as above (include optional `"options": { "delay_ms": 80 }`); server emits `event: started | tick | done | error` for finite tick replay.
- **`WebSocket ws://…/ws/live`** — send JSON `{ "config": {...}, "traffic": { "spawn_chance": 0.35, "max_new_per_tick": 4, "seed": null }, "options": { "delay_ms": 80 }, "requests_bootstrap": [] }`. Passengers from **`requests_bootstrap`** enqueue by **`time`**, then optional **`traffic`** may add stochastic riders each tick (set **`spawn_chance`** or **`max_new_per_tick`** to **`0`** to disable RNG). Streams `started` (+ `live: true`) then unbounded `tick` messages. Client closes socket to stop; unknown extra JSON keys are ignored.

Requests use field names **`id`** (passenger id), **`time`, `source`, `dest`** to match CSV semantics.

### pip and SSL (only if setup still fails)

Prefer **`ca-bundle.crt`** at the repo root and re-running **`scripts/setup.bat`** / **`scripts/setup.sh`**.

**Trusted hosts** *(often insufficient for MITM TLS on modern pip):*

```bash
python -m pip install -r requirements-api.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
```

**Proper CA PEM** (`-----BEGIN CERTIFICATE-----`, optionally combined with [certifi](https://pypi.org/project/certifi/)’s bundle):

```bash
python -m pip install -r requirements-api.txt --cert C:\path\to\corp-ca-bundle.crt
```

Setup retries **`pip upgrade`**, **`requirements.txt`**, and **`requirements-api.txt`** — each plain `pip`, then with **`ca-bundle.crt`**, then trusted-host-only. To mirror that by hand:

```bash
python -m pip install -r requirements-api.txt --cert ca-bundle.crt --trusted-host pypi.org --trusted-host files.pythonhosted.org
```

### npm TLS (Web UI build, `SELF_SIGNED_CERT_IN_CHAIN`)

Place the PEM at the repository root (**same folder as `requirements.txt` / `requirements-api.txt`**), saved as **`ca-bundle.crt`** (exact spelling). **`scripts/setup-web.bat`** / **`scripts/setup-web.sh`** try **`npm install`** with the **default trust store first**; **only if that fails**, they retry with **`NODE_EXTRA_CA_CERTS`** and **`npm install --cafile=...`** when **`ca-bundle.crt`** exists. (**`scripts/setup.bat`** / **`setup.sh`** already use the same pattern for **`pip`**.)

**Manual (**bash**) if you configure npm yourself:**

```bash
export NODE_EXTRA_CA_CERTS="$(pwd)/ca-bundle.crt"
cd web && npm install --cafile="$(pwd)/../ca-bundle.crt"
```

Manual (**Windows cmd**, adjust path):

```bat
set NODE_EXTRA_CA_CERTS=C:\workspace\Concepts\ca-bundle.crt
cd web
npm install --cafile=C:\workspace\Concepts\ca-bundle.crt
```

Avoid **`npm config set strict-ssl false`** unless IT explicitly allows it; prefer a **`BEGIN CERTIFICATE`** bundle as for pip.

### PEM files named `public.pem` / `private.pem` at the repo root

If those files contain **`-----BEGIN PUBLIC KEY-----`** and **`-----BEGIN PRIVATE KEY-----`**, they are a **cryptographic key pair**, not TLS CA certificates. **Do not** pass them to **`pip install --cert`**: that flag is for **`-----BEGIN CERTIFICATE-----`** PEMs used to verify HTTPS servers.

- **`private.pem`**: Secret material — **never commit** it to git.

To fix PyPI TLS behind inspection, obtain a **`BEGIN CERTIFICATE`** chain from IT or export your org’s issuing/root CA in PEM form, concatenate with certifi’s bundle if needed, and use that path with **`--cert`** or **`SSL_CERT_FILE`**.

You can also set (session or system env): `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` to your CA-bundle PEM before running `pip`.

**Persist for all pip installs** (user config, Windows example path)

Create or edit `%APPDATA%\pip\pip.ini`:

```ini
[global]
trusted-host = pypi.org files.pythonhosted.org
cert = C:\path\to\combined-ca-bundle.pem
```

Use a **single PEM** that chains: public CAs (or [certifi](https://pypi.org/project/certifi/)’s bundle) **plus** your corporate root(s). IT often provides this file.

**Last resort (lab only):** an internal mirror (Artifactory / Nexus) with instructions from IT, or insecure HTTP indexes — avoid for anything sensitive.

**Note:** Prefer keeping **`ca-bundle.crt`** untracked (see `.gitignore`) if IT treats it as internal-only.

## 3. Web UI (React)

The UI is decoupled: it calls the API only (never imports Python).

**Recommended (Python only):** build the static app into **`web/dist/`** with **`scripts/setup-web.bat`** or **`./scripts/setup-web.sh`** (requires Node.js + npm once). **`scripts/setup.bat`** / **`scripts/setup.sh`** run that step automatically when **`npm`** is on your PATH.

Then start uvicorn as in §2 and open **http://127.0.0.1:8080/** — the **same** FastAPI process serves REST, WebSocket, and the built React files.

On **some Windows setups**, **`http://localhost:8080`** resolves to **`[::1]`** (IPv6) while uvicorn listens only on **IPv4** — the browser shows “can’t reach this site” and nothing appears in uvicorn logs. Use **`127.0.0.1`** in the URL, or start with **`set ELEVATOR_API_HOST=0.0.0.0`** before **`scripts\run-api.bat`** and open **`http://127.0.0.1:8080/`**. No second terminal, unless **`web/dist/`** is missing (you will see a short help page at `/` with a link to **`/docs`**).

Teams without Node can use **Swagger** at **`/docs`**, or build on another machine with npm and copy **`web/dist/`** into the tree locally (do not commit it; **`web/dist/`** is gitignored so everyone runs **`scripts/setup-web`** after clone when they want the UI).

The UI uses fields that mirror the HTTP body: **`config`** (`num_floors`, `num_elevators`, **`max_passengers` = riders each elevator may carry at once**, `initial_floor`, **`assignment_strategy`** = hall→car dispatcher for movement: `nearest`, `round_robin`, or `score_based`, default **`nearest`**) plus **passenger lines** (one row per requested ride: **`time id source dest`**). The **`requests`** array is built from those lines; **`max_passengers` does not create extra riders**. Expand **Payload preview** in the UI to inspect the JSON (WebSocket payloads include **`options.delay_ms`**; REST **`POST /simulate`** omits **`options`**). For **`/ws/live`**, the same lines populate **`requests_bootstrap`** while optional RNG traffic is controlled in the dashboard; once the server sends **`started`** with **`live: true`**, the passenger box switches to a **read-only live arrivals** feed that appends each new rider line as ticks stream; Stop restores the editable textarea.

### Troubleshooting (blank UI, no uvicorn logs)

1. **Use HTTP, not `file://`.** Opening `web/dist/index.html` from Explorer double‑click uses `file:///…`. Browsers typically **block ES module scripts** for that URL, which yields a **blank page** — and nothing hits uvicorn (so **no access logs**). Start the API and open **`http://127.0.0.1:8080/`** instead.
2. **Confirm assets load.** Browser DevTools → **Network**: `GET /` should be **200**, then **`GET /assets/…\.js`** and **`.css`** also **200**. If the JS/CSS are **404**, rebuild (`scripts/setup-web` or `npm run build` under `web/`) and restart uvicorn — stale `index.html` can reference old hashed filenames.
3. **Vite dev + API:** UI at **`http://127.0.0.1:5173`**, API on **8080** — after you start a REST or WS run from the UI, you should see **`POST /simulate`** and/or **`/ws/stream`** in uvicorn’s access log (`--access-log`; default ON).

**Optional (front-end development):** Vite dev server for hot reload:

```bash
cd web
npm install
npm run dev
```

Open Vite’s URL (often [http://127.0.0.1:5173](http://127.0.0.1:5173)) while uvicorn runs on **8080**.

**Prerequisite:** uvicorn must be running for the UI to call the API.

## Architecture

```
elevator/     # core (discrete-time simulation)
main.py       # CLI entry
api/          # FastAPI HTTP + WebSocket only
web/          # React client only
```

No business logic is duplicated in `api/` or `web/`; the API is a thin adapter over `run_simulation`.
