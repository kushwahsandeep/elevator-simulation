# Web UI



React + Vite + TypeScript. The app only talks to the HTTP/WebSocket API — no Python in the browser.



## Default: no separate dev server



After **`web/dist/`** exists, **uvicorn** serves it at **http://127.0.0.1:8080/** (same host and port as the API). You only run Python.



Build **`web/dist/`** with:



- **Windows:** `scripts\setup-web.bat` (from repo root; needs Node.js + `npm` on PATH)  

- **macOS/Linux:** `./scripts/setup-web.sh`


If **`npm`** hits **`SELF_SIGNED_CERT_IN_CHAIN`**, put the same **`ca-bundle.crt`** at the repo root **`pip`** uses: **`setup-web`** tries default TLS first and **retries** with that file only if the first **`npm install`** fails.

**`scripts/setup.bat`** / **`scripts/setup.sh`** run the web build **automatically** when `npm` is available. The built **`web/dist/`** is not committed (see repo **`.gitignore`**); use **`/docs`** without a UI, or copy in a **`dist`** folder from a machine that ran **`setup-web`**, locally only.



## When you are editing React (optional `npm run dev`)



```bash

cd web

npm install

npm run dev

```



Vite prints a URL (often **http://127.0.0.1:5173**). The app calls the API at **`http://127.0.0.1:8080`** while `import.meta.env.DEV` is true. Start uvicorn in another terminal.



## Configuration



- **`VITE_API_BASE`** in **`web/.env.local`** — override API base (e.g. different port). Not needed when the UI is served by uvicorn from **`/`** on the same origin.



See **`../docs/multimode.md`** for CLI vs API vs UI.


