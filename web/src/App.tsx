import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/** Matches elevator.simulation CSV-style journey rows (tick is first CSV field). */
const JOURNAL_HEADER =
  "tick,event,passenger_id,request_time,source,dest,elevator,wait_time,travel_time,total_time,status";

function positionHeader(numElevators: number): string {
  return ["tick", ...Array.from({ length: numElevators }, (_, i) => `elev_${i}`)].join(",");
}

function csvLeadingInt(line: string): number | null {
  const m = line.match(/^(\d+)/);
  if (!m) return null;
  return parseInt(m[1], 10);
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = window.setTimeout(resolve, ms);
    const onAbort = () => {
      window.clearTimeout(t);
      reject(new DOMException("aborted", "AbortError"));
    };
    if (signal.aborted) {
      window.clearTimeout(t);
      reject(new DOMException("aborted", "AbortError"));
      return;
    }
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

const ASSIGNMENT_STRATEGIES = ["nearest", "round_robin", "score_based"] as const;
type AssignmentStrategy = (typeof ASSIGNMENT_STRATEGIES)[number];

type SimConfigForm = {
  num_floors: number;
  num_elevators: number;
  max_passengers: number;
  initial_floor: number;
  assignment_strategy: AssignmentStrategy;
};

type RequestRowForm = { time: number; id: string; source: number; dest: number };

const DEFAULT_CONFIG: SimConfigForm = {
  num_floors: 12,
  num_elevators: 4,
  max_passengers: 6,
  initial_floor: 1,
  assignment_strategy: "nearest",
};

const DEFAULT_PASSENGER_LINES = `0 a 1 8
0 b 1 5
1 c 3 11`;

function parsePassengerLines(
  text: string,
  allowEmpty = false
): { ok: true; rows: RequestRowForm[] } | { ok: false; error: string } {
  const rows: RequestRowForm[] = [];
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i].trim();
    if (!raw || raw.startsWith("#")) continue;
    const parts = raw.split(/\s+/).filter(Boolean);
    if (parts.length !== 4) {
      return {
        ok: false,
        error: `Line ${i + 1}: need four values (time id source dest), got ${parts.length}. Example: 0 a 1 8`,
      };
    }
    const time = Number(parts[0]);
    const source = Number(parts[2]);
    const dest = Number(parts[3]);
    if (!Number.isFinite(time) || time < 0 || !Number.isInteger(time)) {
      return { ok: false, error: `Line ${i + 1}: time must be a non-negative integer` };
    }
    if (!Number.isFinite(source) || !Number.isFinite(dest)) {
      return { ok: false, error: `Line ${i + 1}: source and dest must be numbers` };
    }
    const id = parts[1];
    if (!id) {
      return { ok: false, error: `Line ${i + 1}: passenger id is required` };
    }
    rows.push({ time, id, source, dest });
  }
  if (rows.length === 0) {
    if (allowEmpty) {
      return { ok: true, rows: [] };
    }
    return { ok: false, error: "Add at least one passenger line (time id source dest)" };
  }
  return { ok: true, rows };
}

function clampInt(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, Math.trunc(value)));
}

function viteApiEnvOverride(): string | undefined {
  const raw = import.meta.env.VITE_API_BASE as unknown;
  if (raw == null) return undefined;
  const s = String(raw).trim();
  return s === "" ? undefined : s.replace(/\/$/, "");
}

/** HTTP origin (scheme+host+port) for WebSocket derivation; aligns with REST. */
function httpOriginForSockets(): string {
  const override = viteApiEnvOverride();
  if (override) return override;
  if (import.meta.env.DEV) return "http://127.0.0.1:8080";
  if (typeof window === "undefined" || !window.location) return "http://127.0.0.1:8080";
  if (window.location.protocol === "file:") return "http://127.0.0.1:8080";
  return `${window.location.protocol}//${window.location.host}`;
}

/** REST URLs: `/path` same-origin when the SPA is bundled with FastAPI; dev hits :8080. */
function apiUrl(endpoint: string): string {
  const ep = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  const override = viteApiEnvOverride();
  if (override) return `${override}${ep}`;
  if (import.meta.env.DEV) return `http://127.0.0.1:8080${ep}`;
  if (typeof window === "undefined" || !window.location) return `http://127.0.0.1:8080${ep}`;
  if (window.location.protocol === "file:") return `http://127.0.0.1:8080${ep}`;
  return ep;
}

function wsOriginFromHttp(): string {
  const u = new URL(httpOriginForSockets());
  const proto = u.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${u.host}`;
}

function apiTargetLabel(): string {
  const v = viteApiEnvOverride();
  if (v) return v;
  if (import.meta.env.DEV) return "http://127.0.0.1:8080";
  if (typeof window !== "undefined" && window.location?.protocol !== "file:") {
    return `${window.location.protocol}//${window.location.host}`;
  }
  return "http://127.0.0.1:8080";
}

function apiPortHint(): string {
  try {
    const p = new URL(httpOriginForSockets()).port;
    return p || (httpOriginForSockets().includes("https") ? "443" : "80");
  } catch {
    return "8080";
  }
}

type PassengerSummary = {
  id: string;
  request_time: number;
  source: number;
  dest: number;
  assigned_elevator: number;
  picked_up_at: number | null;
  dropped_at: number | null;
  wait_ticks: number | null;
  travel_ticks: number | null;
  total_ticks: number | null;
};

type TickRow = { tick: number; elevator_floors: number[] };

function statsForTick(
  tickNow: number,
  passengers: PassengerSummary[],
  numElevators: number,
  totalTicks: number
) {
  let waiting = 0;
  let onboard = 0;
  let delivered = 0;
  let waitSum = 0;
  let deliveredWithWait = 0;
  const loadByElevator = Array.from({ length: numElevators }, () => 0);

  for (const p of passengers) {
    if (p.request_time > tickNow) continue;

    const droppedOk = p.dropped_at !== null && p.dropped_at <= tickNow;
    if (droppedOk) {
      delivered++;
      if (typeof p.wait_ticks === "number") {
        waitSum += p.wait_ticks;
        deliveredWithWait++;
      }
      continue;
    }

    const pickedOk = p.picked_up_at !== null && p.picked_up_at <= tickNow;
    if (pickedOk) {
      onboard++;
      const e = p.assigned_elevator;
      if (e >= 0 && e < numElevators) loadByElevator[e]++;
      continue;
    }

    waiting++;
  }

  const pct =
    totalTicks > 0 ? Math.min(100, Math.round(((tickNow + 1) / Math.max(totalTicks, 1)) * 100)) : 0;

  return {
    waiting,
    onboard,
    delivered,
    avgWaitDeliveredsoFar:
      deliveredWithWait > 0 ? Math.round((waitSum / deliveredWithWait) * 10) / 10 : null,
    loadByElevator,
    pct,
    totalPassengers: passengers.length,
    totalTicks,
  };
}

function filterLogsByTick(lines: readonly string[], maxTickInclusive: number): string[] {
  return lines.filter((line) => {
    const v = csvLeadingInt(line);
    return v !== null && v <= maxTickInclusive;
  });
}

/** Split simulator CSV lines into cells (no quoted-field edge cases today). */
function splitCsvCells(line: string): string[] {
  return line.split(",");
}

function padRow(cells: string[], colCount: number): string[] {
  const out = cells.slice(0, colCount);
  while (out.length < colCount) {
    out.push("");
  }
  return out;
}

function CsvDataGrid({
  headers,
  lines,
  emptyLabel,
  variant,
}: {
  headers: string[];
  lines: readonly string[];
  emptyLabel: string;
  variant: "journey" | "positions";
}) {
  const colCount = headers.length;

  const bodyRows =
    lines.length > 0
      ? lines.map((line, ri) => {
          const cells = padRow(splitCsvCells(line), colCount);
          return (
            <tr key={`${ri}:${line.slice(0, 32)}`}>
              {cells.map((cell, ci) => (
                <td key={ci}>{cell === "" ? "—" : cell}</td>
              ))}
            </tr>
          );
        })
      : null;

  return (
    <div className="log-table-wrap">
      <table className={`log-grid${variant === "positions" ? " log-grid-pos" : ""}`}>
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th key={i}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {bodyRows ? (
            bodyRows
          ) : (
            <tr className="log-grid-empty">
              <td colSpan={colCount}>{emptyLabel}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function App() {
  const [simConfig, setSimConfig] = useState<SimConfigForm>(DEFAULT_CONFIG);
  const [passengerLines, setPassengerLines] = useState(DEFAULT_PASSENGER_LINES);
  const apiLabel = apiTargetLabel();
  const [playbackMs, setPlaybackMs] = useState(320);

  /** `finite`: one-shot replay / `continuous`: WS `/ws/live` bootstrap + optional RNG arrivals */
  type WsTrafficMode = "finite" | "continuous";
  const [wsTrafficMode, setWsTrafficMode] = useState<WsTrafficMode>("finite");
  const [liveSpawnChance, setLiveSpawnChance] = useState(0.35);
  const [liveMaxNewPerTick, setLiveMaxNewPerTick] = useState(4);
  const [continuousReplay, setContinuousReplay] = useState(false);

  const [status, setStatus] = useState<string>("idle");
  const [err, setErr] = useState<string | null>(null);
  const [progress, setProgress] = useState<string>("Ready");

  const [nf, setNf] = useState(12);
  const [ne, setNe] = useState(4);
  const [floors, setFloors] = useState<number[]>([1, 1, 1, 1]);
  const [tick, setTick] = useState(0);
  const [passengersSnap, setPassengersSnap] = useState<PassengerSummary[]>([]);
  const [journalLines, setJournalLines] = useState<string[]>([]);
  const [positionLines, setPositionLines] = useState<string[]>([]);
  const [totalTicksState, setTotalTicksState] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const playbackAbort = useRef<AbortController | null>(null);
  /** Dedupe passenger ids when appending rows to the live `/ws/live` request feed. */
  const seenPassengerIdsRef = useRef<Set<string>>(new Set());
  /** Bootstrap + RNG arrivals as `time id src dst` lines while continuous WS is active. */
  const [liveRequestFeed, setLiveRequestFeed] = useState("");
  /** Read-only arrival textarea only after server `started` with live=true (editable bootstrap until then). */
  const [liveArrivalFeedOpen, setLiveArrivalFeedOpen] = useState(false);

  const bumpPlayback = () => {
    playbackAbort.current?.abort();
    playbackAbort.current = new AbortController();
    return playbackAbort.current.signal;
  };

  const stopPlayback = () => {
    playbackAbort.current?.abort();
    playbackAbort.current = null;
  };

  function stopStream(): void {
    stopPlayback();
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setContinuousReplay(false);
    setLiveArrivalFeedOpen(false);
  }

  useEffect(
    () => () => {
      stopStream();
    },
    []
  );

  const liveStats = useMemo(
    () => statsForTick(tick, passengersSnap, ne, Math.max(totalTicksState, 1)),
    [tick, passengersSnap, ne, totalTicksState]
  );

  const journeyVisible = useMemo(
    () => filterLogsByTick(journalLines, tick),
    [journalLines, tick]
  );
  const positionsVisible = useMemo(
    () => filterLogsByTick(positionLines, tick),
    [positionLines, tick]
  );

  async function runRest(): Promise<void> {
    stopStream();
    setErr(null);
    setStatus("playing REST replay…");

    let signal: AbortSignal;
    try {
      signal = bumpPlayback();
    } catch {
      return;
    }

    const parsedLines = parsePassengerLines(passengerLines);
    if (!parsedLines.ok) {
      setErr(parsedLines.error);
      setStatus("error");
      return;
    }

    const nfloors = clampInt(simConfig.num_floors, 1, 500);
    const cfgNorm = {
      num_floors: nfloors,
      num_elevators: clampInt(simConfig.num_elevators, 1, 64),
      max_passengers: clampInt(simConfig.max_passengers, 1, 500),
      initial_floor: clampInt(simConfig.initial_floor, 1, nfloors),
      assignment_strategy: simConfig.assignment_strategy,
    };
    const obj = { config: cfgNorm, requests: parsedLines.rows };

    try {
      const r = await fetch(apiUrl("/simulate"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(obj),
      });

      const data = await r.json();
      if (!r.ok) {
        setErr(typeof data.detail === "string" ? data.detail : JSON.stringify(data));
        setStatus("error");
        return;
      }

      const cfg = obj.config as { num_floors: number; num_elevators: number };
      setNf(cfg.num_floors);
      setNe(cfg.num_elevators);

      const rows = data.position_rows as TickRow[];
      const ps = data.passengers as PassengerSummary[];
      const jn = (data.journal_lines as string[]) ?? [];
      setPassengersSnap(ps);
      setJournalLines(jn);
      setTotalTicksState(rows.length);
      const posBuilt = rows.map((row) =>
        [row.tick, ...row.elevator_floors.slice(0, cfg.num_elevators)].join(",")
      );
      setPositionLines(posBuilt);

      if (rows.length === 0) {
        setFloors(new Array(cfg.num_elevators).fill(1));
        setTick(0);
        setProgress("REST · 0 ticks");
        setStatus("done");
        return;
      }

      for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        setTick(row.tick);
        setFloors(row.elevator_floors.slice(0, cfg.num_elevators));
        const tot = rows.length;
        setProgress(`REST replay · tick ${row.tick + 1} / ${tot} · ${playbackMs}ms`);
        if (i < rows.length - 1) {
          await sleep(Math.max(0, playbackMs), signal).catch(() => {
            throw new DOMException("aborted", "AbortError");
          });
        }
      }

      setProgress(`REST · finished · ${rows.length} ticks · ${playbackMs}ms pacing`);
      setStatus("done");
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        setProgress("Stopped");
        setStatus("idle");
        return;
      }
      const msg = e instanceof Error ? e.message : String(e);
      setErr(msg);
      setStatus("error");
    }
  }

  const runStream = useCallback(() => {
    stopStream();
    setErr(null);

    const continuous = wsTrafficMode === "continuous";
    const parsedLines = parsePassengerLines(passengerLines, continuous);
    if (!parsedLines.ok) {
      setErr(parsedLines.error);
      setStatus("error");
      return;
    }

    if (!continuous) {
      seenPassengerIdsRef.current.clear();
      setLiveRequestFeed("");
    }

    setContinuousReplay(continuous);
    setStatus(continuous ? "live" : "streaming…");

    const nfloors = clampInt(simConfig.num_floors, 1, 500);
    const cfgNorm = {
      num_floors: nfloors,
      num_elevators: clampInt(simConfig.num_elevators, 1, 64),
      max_passengers: clampInt(simConfig.max_passengers, 1, 500),
      initial_floor: clampInt(simConfig.initial_floor, 1, nfloors),
      assignment_strategy: simConfig.assignment_strategy,
    };
    const nelev = cfgNorm.num_elevators;

    const body =
      continuous ?
        {
          config: cfgNorm,
          traffic: {
            spawn_chance: Math.min(1, Math.max(0, liveSpawnChance)),
            max_new_per_tick: clampInt(liveMaxNewPerTick, 0, 40),
          },
          options: { delay_ms: playbackMs },
          requests_bootstrap: parsedLines.rows.map((r) => ({
            time: r.time,
            id: r.id,
            source: r.source,
            dest: r.dest,
          })),
        }
      : {
          config: cfgNorm,
          requests: parsedLines.rows,
          options: { delay_ms: playbackMs },
        };

    setNf(cfgNorm.num_floors);
    setNe(nelev);
    setFloors(new Array(nelev).fill(cfgNorm.initial_floor));
    setTick(0);

    const wsPath = continuous ? "/ws/live" : "/ws/stream";
    const wsUrl = `${wsOriginFromHttp()}${wsPath}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => ws.send(JSON.stringify(body));

    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data as string) as Record<string, unknown>;
      const event = msg.event as string;

      if (event === "error") {
        const d = msg.detail;
        setErr(typeof d === "string" ? d : JSON.stringify(d));
        setStatus("error");
        setContinuousReplay(false);
        setLiveArrivalFeedOpen(false);
        ws.close();
        return;
      }

      if (event === "started") {
        const isLive = Boolean(msg.live);
        setContinuousReplay(isLive);
        const total = typeof msg.total_ticks === "number" ? msg.total_ticks : 0;
        setTotalTicksState(total);
        setPassengersSnap((msg.passengers as PassengerSummary[]) ?? []);
        if (isLive) {
          seenPassengerIdsRef.current.clear();
          for (const r of parsedLines.rows) {
            seenPassengerIdsRef.current.add(r.id);
          }
          const seedLines = parsedLines.rows.map((r) => `${r.time} ${r.id} ${r.source} ${r.dest}`);
          const bootPassengers = (msg.passengers as PassengerSummary[]) ?? [];
          for (const p of bootPassengers) {
            if (seenPassengerIdsRef.current.has(p.id)) continue;
            seenPassengerIdsRef.current.add(p.id);
            seedLines.push(`${p.request_time} ${p.id} ${p.source} ${p.dest}`);
          }
          setLiveRequestFeed(seedLines.join("\n") + (seedLines.length > 0 ? "\n" : ""));
          setLiveArrivalFeedOpen(true);
          setJournalLines([]);
          setPositionLines([]);
          setProgress(
            `live ~${liveSpawnChance.toFixed(2)} chance x ${clampInt(liveMaxNewPerTick, 0, 40)} tries/tick + bootstrap · ${playbackMs}ms`
          );
        } else {
          setLiveArrivalFeedOpen(false);
          setJournalLines((msg.journal_lines as string[]) ?? []);
          setPositionLines((msg.position_log_lines as string[]) ?? []);
          setProgress(`stream · connecting · ${total} ticks · ~${playbackMs}ms server pacing`);
        }
        return;
      }

      if (event === "tick") {
        const floorsMsg = msg.floors as number[] | undefined;
        if (!floorsMsg) return;
        const t = (msg.tick as number) ?? 0;
        setTick(t);
        setFloors(floorsMsg.slice(0, nelev));

        const isLiveTick = Boolean(msg.live);
        const deltas = msg.journal_delta as string[] | undefined;
        if (Array.isArray(deltas) && deltas.length > 0) {
          setJournalLines((prev) => [...prev, ...deltas]);
        }
        const posRow = msg.position_row as string | undefined;
        if (typeof posRow === "string" && posRow.length > 0) {
          setPositionLines((prev) => [...prev, posRow]);
        }

        const pListTick = msg.passengers as PassengerSummary[] | undefined;
        if (Array.isArray(pListTick)) {
          setPassengersSnap(pListTick);
          if (isLiveTick) {
            let blob = "";
            for (const p of pListTick) {
              if (seenPassengerIdsRef.current.has(p.id)) continue;
              seenPassengerIdsRef.current.add(p.id);
              blob += `${p.request_time} ${p.id} ${p.source} ${p.dest}\n`;
            }
            if (blob.length > 0) {
              setLiveRequestFeed((prev) => prev + blob);
            }
          }
        }

        if (isLiveTick) {
          setProgress(`live · tick ${t} · ${playbackMs}ms pacing`);
        } else {
          const totKnown = typeof msg.total_ticks === "number" ? msg.total_ticks : undefined;
          setProgress(
            totKnown !== undefined
              ? `stream · tick ${t + 1} / ${totKnown} · ${playbackMs}ms`
              : `stream · tick ${t} · ${playbackMs}ms`
          );
        }
        return;
      }

      if (event === "done") {
        setContinuousReplay(false);
        const plist = msg.passengers as PassengerSummary[] | undefined;
        if (Array.isArray(plist)) {
          setPassengersSnap(plist);
        }
        const lastRaw = msg.last_tick;
        const lt = typeof lastRaw === "number" ? String(lastRaw) : "—";
        setProgress(`stream · complete · last tick ${lt}`);
        setStatus("done");
      }
    };

    ws.onerror = () => {
      setErr(
        `WebSocket failed — ensure the API is running (expected ${httpOriginForSockets()} ; port ${apiPortHint()}). Scripts: scripts/run-api.bat`
      );
      setStatus("error");
      setContinuousReplay(false);
      setLiveArrivalFeedOpen(false);
    };

    ws.onclose = () => {
      wsRef.current = null;
      setContinuousReplay(false);
      setLiveArrivalFeedOpen(false);
      setStatus((prev) => {
        if (prev === "done" || prev === "error") return prev;
        if (prev === "live" || prev === "streaming…") return "idle";
        return prev;
      });
    };
  }, [
    apiLabel,
    liveSpawnChance,
    liveMaxNewPerTick,
    passengerLines,
    playbackMs,
    simConfig,
    wsTrafficMode,
  ]);

  const outboundPreview = useMemo((): Record<string, unknown> | null => {
    if (wsTrafficMode === "continuous") {
      return null;
    }
    const parsed = parsePassengerLines(passengerLines);
    if (!parsed.ok) return null;
    const nfloors = clampInt(simConfig.num_floors, 1, 500);
    const cfg = {
      num_floors: nfloors,
      num_elevators: clampInt(simConfig.num_elevators, 1, 64),
      max_passengers: clampInt(simConfig.max_passengers, 1, 500),
      initial_floor: clampInt(simConfig.initial_floor, 1, nfloors),
      assignment_strategy: simConfig.assignment_strategy,
    };
    return { config: cfg, requests: parsed.rows, options: { delay_ms: playbackMs } };
  }, [simConfig, passengerLines, playbackMs, wsTrafficMode]);

  return (
    <div className="app-shell">
      <header className="hero hero-compact">
        <div className="hero-bar">
          <div className="hero-titles">
            <h1>Elevator simulator</h1>
            <p className="hero-mini muted">
              Discrete-time bank · <code>POST /simulate</code> ·{" "}
              <code title="finite replay">WS /ws/stream</code> ·{" "}
              <code title="live random + bootstrap">WS /ws/live</code>
            </p>
          </div>
          <code className="hero-api mono" title="API base URL">
            {apiLabel}
          </code>
        </div>
      </header>

      <main className="layout layout-wide">
        <section className="card card-accent dash-board">
          <div className="dash-main">
              <div className="dash-toolbar">
                <label className="field-label toolbar-delay">
                  <span>Tick delay ({playbackMs} ms)</span>
                  <input
                    type="range"
                    min={40}
                    max={1200}
                    step={20}
                    value={playbackMs}
                    onChange={(e) => setPlaybackMs(Number(e.target.value))}
                  />
                  <div className="range-hints">
                    <span>snap</span>
                    <span>cinematic</span>
                  </div>
                </label>
              </div>

              <fieldset className="traffic-fieldset">
                <legend className="dash-section-sub">WebSocket traffic</legend>
                <div className="mode-toggle-row">
                  <label className="mode-option">
                    <input
                      type="radio"
                      name="wsMode"
                      checked={wsTrafficMode === "finite"}
                      onChange={() => setWsTrafficMode("finite")}
                    />
                    <span>
                      Finite replay — <code>/ws/stream</code> drains a fixed tick plan.
                    </span>
                  </label>
                  <label className="mode-option">
                    <input
                      type="radio"
                      name="wsMode"
                      checked={wsTrafficMode === "continuous"}
                      onChange={() => setWsTrafficMode("continuous")}
                    />
                    <span>
                      Continuous <code>/ws/live</code> until Stop — scenario lines bootstrap first ticks, then optional
                      random arrivals (below).
                    </span>
                  </label>
                </div>
              </fieldset>

              {wsTrafficMode === "continuous" && (
                <div className="live-traffic-controls">
                  <p className="muted live-traffic-hint">
                    Each tick: up to <strong>{clampInt(liveMaxNewPerTick, 0, 40)}</strong> tries; each has{' '}
                    <strong>{Math.round(liveSpawnChance * 100)}%</strong> chance to spawn one random rider (
                    <code className="nowrap">traffic.spawn_chance</code>).
                  </p>
                  <label className="field-label compact-range">
                    <span>Spawn chance per try ({Math.round(liveSpawnChance * 100)}%)</span>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      step={5}
                      value={Math.round(liveSpawnChance * 100)}
                      onChange={(e) => setLiveSpawnChance(Number(e.target.value) / 100)}
                    />
                  </label>
                  <label className="field-num slim">
                    Max tries per tick
                    <input
                      type="number"
                      min={0}
                      max={40}
                      value={liveMaxNewPerTick}
                      onChange={(e) =>
                        setLiveMaxNewPerTick(clampInt(Number(e.target.value), 0, 40))
                      }
                    />
                  </label>
                </div>
              )}

              <div className="config-grid">
                <label className="field-num">
                  num_floors
                  <input
                    type="number"
                    min={1}
                    max={500}
                    value={simConfig.num_floors}
                    onChange={(e) =>
                      setSimConfig((c) => {
                        const nf = clampInt(Number(e.target.value), 1, 500);
                        return {
                          ...c,
                          num_floors: nf,
                          initial_floor: clampInt(c.initial_floor, 1, nf),
                        };
                      })
                    }
                  />
                </label>
                <label className="field-num">
                  num_elevators
                  <input
                    type="number"
                    min={1}
                    max={64}
                    value={simConfig.num_elevators}
                    onChange={(e) =>
                      setSimConfig((c) => ({
                        ...c,
                        num_elevators: clampInt(Number(e.target.value), 1, 64),
                      }))
                    }
                  />
                </label>
                <label className="field-num">
                  <span className="field-num-title">
                    max_passengers
                    <span className="field-num-sub muted" title="Not total riders">
                      per elevator capacity
                    </span>
                  </span>
                  <input
                    type="number"
                    min={1}
                    max={500}
                    aria-describedby="hint-max-passengers"
                    value={simConfig.max_passengers}
                    onChange={(e) =>
                      setSimConfig((c) => ({
                        ...c,
                        max_passengers: clampInt(Number(e.target.value), 1, 500),
                      }))
                    }
                  />
                  <span id="hint-max-passengers" className="sr-only">
                    Maximum passengers allowed on one elevator at once. Add more rider lines below to simulate more
                    people.
                  </span>
                </label>
                <label className="field-num">
                  initial_floor
                  <input
                    type="number"
                    min={1}
                    max={simConfig.num_floors}
                    value={simConfig.initial_floor}
                    onChange={(e) =>
                      setSimConfig((c) => ({
                        ...c,
                        initial_floor: clampInt(
                          Number(e.target.value),
                          1,
                          Math.max(1, c.num_floors)
                        ),
                      }))
                    }
                  />
                </label>
              </div>

              <fieldset className="traffic-fieldset">
                <legend className="dash-section-sub">Dispatcher (assignment strategy)</legend>
                <p className="config-hint muted assign-strategy-lede">
                  Shared hall queues — any car may pick up passengers at a landing. Each tick, the model assigns
                  nonempty halls to specific cars for navigation so empty shafts do not all chase the same floor. This
                  mirrors <code className="nowrap">config.assignment_strategy</code> on the API.
                </p>
                <div className="mode-toggle-row">
                  <label className="mode-option">
                    <input
                      type="radio"
                      name="assignStrategy"
                      checked={simConfig.assignment_strategy === "nearest"}
                      onChange={() =>
                        setSimConfig((c) => ({ ...c, assignment_strategy: "nearest" }))
                      }
                    />
                    <span>
                      <strong>Nearest car</strong>{" "}
                      <span className="muted">
                        (<code className="nowrap">nearest</code>)
                      </span>
                    </span>
                  </label>
                  <label className="mode-option">
                    <input
                      type="radio"
                      name="assignStrategy"
                      checked={simConfig.assignment_strategy === "round_robin"}
                      onChange={() =>
                        setSimConfig((c) => ({ ...c, assignment_strategy: "round_robin" }))
                      }
                    />
                    <span>
                      <strong>Round robin</strong>{" "}
                      <span className="muted">
                        (<code className="nowrap">round_robin</code>)
                      </span>
                    </span>
                  </label>
                  <label className="mode-option">
                    <input
                      type="radio"
                      name="assignStrategy"
                      checked={simConfig.assignment_strategy === "score_based"}
                      onChange={() =>
                        setSimConfig((c) => ({ ...c, assignment_strategy: "score_based" }))
                      }
                    />
                    <span>
                      <strong>Score based</strong>{" "}
                      <span className="muted">
                        (<code className="nowrap">score_based</code>)
                      </span>
                    </span>
                  </label>
                </div>
              </fieldset>

              <label className="field-label scenario-label">
                <span>
                  {liveArrivalFeedOpen ? (
                    <>
                      Live arrivals (<code>requests</code>) — streams new riders while{" "}
                      <code>/ws/live</code> runs · <code className="nowrap">time id source dest</code>
                      <span className="muted">
                        {" "}
                        · Stop to edit bootstrap lines for the next run.
                      </span>
                    </>
                  ) : (
                    <>
                      Passengers (<code>requests</code>) — one per line:{" "}
                      <code className="nowrap">time id source dest</code>
                      <span className="muted"> · empty lines and </span>
                      <code>#</code>
                      <span className="muted"> comments ignored · </span>
                      {wsTrafficMode === "continuous" ? (
                        <span className="muted">
                          For <strong>continuous</strong> mode: textarea is bootstrap; RNG fills in after unless both
                          controls above are zero.
                        </span>
                      ) : (
                        <span className="muted">
                          Scenario WebSocket replay uses exactly these rider lines once.
                        </span>
                      )}
                    </>
                  )}
                </span>
                {liveArrivalFeedOpen ? (
                  <textarea
                    className="scenario-box scenario-live-feed"
                    spellCheck={false}
                    readOnly
                    aria-label="live passenger arrivals"
                    value={liveRequestFeed}
                  />
                ) : (
                  <textarea
                    className="scenario-box"
                    spellCheck={false}
                    aria-label="passenger request lines"
                    value={passengerLines}
                    onChange={(e) => setPassengerLines(e.target.value)}
                  />
                )}
              </label>

              {outboundPreview != null && wsTrafficMode === "finite" && (
                <details className="api-preview">
                  <summary>Payload preview (built for WebSocket; REST sends the same without options)</summary>
                  <pre className="api-preview-pre">{JSON.stringify(outboundPreview, null, 2)}</pre>
                </details>
              )}

              <div className="btn-row">
                <button type="button" className="btn-primary" onClick={() => void runRest()}>
                  Run &amp; replay (REST)
                </button>
                <button type="button" className="btn-primary" onClick={runStream}>
                  {wsTrafficMode === "continuous"
                    ? "Start live (WS)"
                    : "Stream scenario (WS)"}
                </button>
                <button type="button" className="btn-ghost" onClick={stopStream}>
                  Stop
                </button>
              </div>
              <div className={`status-chip ${status === "error" ? "bad" : ""}`}>
                <span className="status-label">{progress}</span>
                <span className="muted">· {status}</span>
              </div>
              {err != null && <div className="banner-error">{err}</div>}
          </div>
        </section>

        <section className="card shafts-card">
          <div className="card-head tight">
            <h2>Shafts</h2>
            <p className="card-desc muted">Lobby is floor 1 at the bottom; cars glide with eased motion.</p>
          </div>
          <div className="live-stats-above-shafts card-nested" aria-label="Live simulation stats">
            <p className="live-stats-strip-lede muted">
              Tick <strong>{tick}</strong>.{" "}
              {continuousReplay ? (
                <>Continuous stream — grids grow until you press Stop.</>
              ) : (
                <>
                  Batch runs freeze stats when REST or finite <code>/ws/stream</code> replay finishes.
                </>
              )}
            </p>
            <div className="live-stats-strip-metrics">
              <div className="cs-item">
                <span className="cs-k">Delivered</span>
                <span className="cs-v">{liveStats.delivered}</span>
              </div>
              <div className="cs-item">
                <span className="cs-k">Waiting</span>
                <span className="cs-v accent-warn">{liveStats.waiting}</span>
              </div>
              <div className="cs-item">
                <span className="cs-k">Onboard</span>
                <span className="cs-v accent-ok">{liveStats.onboard}</span>
              </div>
              <div className="cs-item">
                <span className="cs-k">Avg wait</span>
                <span className="cs-v">{liveStats.avgWaitDeliveredsoFar ?? "—"}</span>
              </div>
              <div className="cs-item">
                <span className="cs-k">Timeline</span>
                <span className="cs-v">
                  {continuousReplay ?
                    <>
                      live <span className="muted">tick {tick}</span>
                    </>
                  : <>
                      {liveStats.pct}% <span className="muted">/ {liveStats.totalTicks}</span>
                    </>
                  }
                </span>
              </div>
              <div className="cs-item">
                <span className="cs-k">Passengers</span>
                <span className="cs-v">{liveStats.totalPassengers}</span>
              </div>
            </div>
            <div className="live-stats-strip-loads">
              <span className="cs-k">Loads</span>
              <div className="load-chips">
                {liveStats.loadByElevator.map((n, ei) => (
                  <span key={ei} className="chip" title={`Elevator ${ei}`}>
                    e{ei}: <strong>{n}</strong>
                  </span>
                ))}
              </div>
            </div>
          </div>
          <BuildingView
            numFloors={nf}
            numElevators={ne}
            elevatorFloors={floors}
            simTick={tick}
            playbackMs={playbackMs}
            passengers={passengersSnap}
          />
        </section>

        <section className="logs-grid">
          <div className="card log-card log-card-journey">
            <h3 className="log-title">Passenger journey</h3>
            <CsvDataGrid
              headers={splitCsvCells(JOURNAL_HEADER)}
              lines={journeyVisible}
              emptyLabel="(no events yet)"
              variant="journey"
            />
          </div>
          <div className="card log-card log-card-positions">
            <h3 className="log-title">Elevator positions</h3>
            <CsvDataGrid
              headers={splitCsvCells(positionHeader(ne))}
              lines={positionsVisible}
              emptyLabel="(no snapshots yet)"
              variant="positions"
            />
          </div>
        </section>
      </main>
    </div>
  );
}

function abbrevPassengerId(id: string): string {
  const s = String(id);
  return s.length <= 6 ? s : `${s.slice(0, 5)}…`;
}

/** Roof = higher floor label → trip “up” means destination above source. */
function passengerTripDirection(p: { source: number; dest: number }): "up" | "down" {
  if (p.dest > p.source) return "up";
  if (p.dest < p.source) return "down";
  return "up";
}

function countTripDirections(passengersList: PassengerSummary[]): { up: number; down: number } {
  let up = 0;
  let down = 0;
  for (const p of passengersList) {
    if (passengerTripDirection(p) === "up") up++;
    else down++;
  }
  return { up, down };
}

/** True when `simTick` is after the passenger has requested but before they are picked up this tick (not yet onboard). */
function passengerWaitingAtTick(p: PassengerSummary, tick: number): boolean {
  if (p.request_time > tick) return false;
  const pick = p.picked_up_at;
  if (pick != null && pick <= tick) return false;
  return true;
}

function passengerOnboardAtTick(p: PassengerSummary, tick: number): boolean {
  const pick = p.picked_up_at;
  if (pick == null || pick > tick) return false;
  const drop = p.dropped_at;
  if (drop != null && drop <= tick) return false;
  return true;
}

function BuildingView({
  numFloors,
  numElevators,
  elevatorFloors,
  simTick,
  playbackMs,
  passengers,
}: {
  numFloors: number;
  numElevators: number;
  elevatorFloors: number[];
  simTick: number;
  playbackMs: number;
  passengers: PassengerSummary[];
}) {
  const rowH = Math.min(38, Math.max(22, Math.floor(720 / Math.max(numFloors, 1))));
  const carFadeMs = Math.min(440, Math.max(120, Math.round(Number(playbackMs) * 0.35)));

  const cols =
    elevatorFloors.length >= numElevators
      ? elevatorFloors.slice(0, numElevators)
      : [
          ...elevatorFloors,
          ...new Array(numElevators - elevatorFloors.length).fill(1),
        ];

  const landingWaiters = passengers.filter(
    (p) =>
      passengerWaitingAtTick(p, simTick) && p.source >= 1 && p.source <= numFloors
  );
  const landingByFloor = new Map<number, PassengerSummary[]>();
  for (const p of landingWaiters) {
    const arr = landingByFloor.get(p.source) ?? [];
    arr.push(p);
    landingByFloor.set(p.source, arr);
  }

  const gridTemplateColumns = `2.5rem minmax(5.5rem, min(40vw, 14rem)) repeat(${Math.max(numElevators, 1)}, minmax(1.85rem, 1fr))`;
  /** Top row = highest floor number (roof); bottom = floor 1. */
  const floorRowsDescending = Array.from({ length: numFloors }, (_, i) => numFloors - i);

  return (
    <div className="building-card-inner building-card-horizontal">
      <div className="building-toolbar">
        <div className="tick-pill mono building-floors-pill" title={`Simulation tick ${simTick} · row 1 = floor ${numFloors} (roof) · bottom = floor 1`}>
          Floors <strong>1–{numFloors}</strong>
          <span className="muted" style={{ fontWeight: 400, marginLeft: "0.35rem" }}>
            (roof at top row)
          </span>
        </div>
        <p className="building-legend muted">
          <span className="wait-chip wait-chip-row wait-chip--trip-up legend-sample">▲</span> landing, trip{" "}
          <strong className="mono">up</strong> ·{" "}
          <span className="wait-chip wait-chip-row wait-chip--trip-down legend-sample">▼</span> landing, trip{" "}
          <strong className="mono">down</strong> · cabin counts show{" "}
          <span className="mono">↑n</span>/<span className="mono">↓n</span> (mixed loads split) · {numElevators}{" "}
          shafts
        </p>
      </div>
      <div className="building-floor-matrix" style={{ ["--floor-row-h" as string]: `${rowH}px` }}>
        <div className="floor-row floor-row--header" style={{ gridTemplateColumns }}>
          <div className="floor-num floor-num--corner" aria-hidden />
          <div className="floor-hall-heading" title="Landing (outside elevators)">
            Landing
          </div>
          {cols.slice(0, numElevators).map((_, ei) => (
            <div key={`h-e${ei}`} className="floor-shaft-heading mono" title={`Elevator ${ei}`}>
              E{ei}
            </div>
          ))}
        </div>
        {floorRowsDescending.map((floor) => {
          const waitHere = landingByFloor.get(floor) ?? [];
          return (
            <div
              key={`fl-${floor}`}
              className="floor-row"
              style={{ gridTemplateColumns, minHeight: `${rowH}px` }}
              title={`Floor ${floor}`}
            >
              <div className="floor-num mono">{floor}</div>
              <div className="floor-hall-landing">
                {waitHere.length > 0 ?
                  <div className="floor-hall-wait-group">
                    {waitHere.map((p) => {
                      const trip = passengerTripDirection(p);
                      return (
                        <span
                          key={p.id}
                          className={`wait-chip wait-chip-row wait-chip--trip-${trip}`}
                          title={`${p.id}: ${p.source}→${p.dest} (${trip} trip)`}
                        >
                          {trip === "up" ? "▲" : "▼"}
                          {abbrevPassengerId(p.id)}
                        </span>
                      );
                    })}
                  </div>
                :
                  <span className="floor-hall-empty muted" aria-hidden>
                    —
                  </span>
                }
              </div>
              {cols.slice(0, numElevators).map((fl, ei) => {
                const clamped = Math.min(Math.max(fl, 1), numFloors);
                const onboardHere = passengers.filter(
                  (p) => p.assigned_elevator === ei && passengerOnboardAtTick(p, simTick)
                );
                const { up: onUp, down: onDn } = countTripDirections(onboardHere);
                const carHere = clamped === floor;
                return (
                  <div key={`${ei}-${floor}`} className="floor-shaft-cell">
                    {carHere ?
                      <div
                        className={
                          onboardHere.length > 0 ?
                            "car-lift-box car-lift-box--loaded"
                          : "car-lift-box car-lift-box--empty"
                        }
                        style={{ transition: `opacity ${carFadeMs}ms ease-out` }}
                        title={
                          onboardHere.length > 0 ?
                            `Elevator ${ei}: ${onboardHere.length} onboard (${onUp} trip up, ${onDn} trip down) — ${onboardHere.map((p) => `${p.id} ${p.source}→${p.dest}`).join("; ")}`
                          : `Elevator ${ei} (empty)`
                        }
                      >
                        {onboardHere.length > 0 ?
                          onUp > 0 && onDn > 0 ?
                            <div className="car-lift-split mono">
                              <span className="car-lift-trip car-lift-trip--up">↑{onUp}</span>
                              <span className="car-lift-trip car-lift-trip--down">↓{onDn}</span>
                            </div>
                          : <span
                              className={`car-lift-count mono ${onUp > 0 ? "car-lift-count--up" : "car-lift-count--down"}`}
                            >
                              {onUp > 0 ? "↑" : "↓"}
                              {onboardHere.length}
                            </span>

                        : null}
                      </div>
                    :
                      <span className="shaft-slot-quiet" aria-hidden />
                    }
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
