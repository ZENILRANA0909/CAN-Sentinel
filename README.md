<div align="center">

# CAN-Sentinel

**Automotive CAN Bus Intrusion Detection & Monitoring Platform**

A real-time security monitor for the Controller Area Network — the bus that
carries engine, brake and steering messages inside every modern vehicle.

[![Version](https://img.shields.io/badge/version-1.0.0-38bdf8)](#)
[![Python](https://img.shields.io/badge/python-3.12+-3776ab)](#)
[![React](https://img.shields.io/badge/react-18-61dafb)](#)
[![Tests](https://img.shields.io/badge/tests-387%20passing-22c55e)](#testing)
[![Coverage](https://img.shields.io/badge/backend%20coverage-94%25-22c55e)](#testing)
[![License](https://img.shields.io/badge/license-MIT-64748b)](LICENSE)

</div>

> [!IMPORTANT]
> **This is a demonstration and research platform.** It is not certified,
> validated, or suitable for deployment in a real vehicle. Its detection
> thresholds are illustrative values chosen so attacks are visible within
> seconds on a laptop — they are **not** derived from any automotive safety
> standard. See [Security limitations](#security-limitations).

---

## Table of contents

- [The problem](#the-problem)
- [What CAN-Sentinel does](#what-can-sentinel-does)
- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Detection engine](#detection-engine)
- [The dashboard](#the-dashboard)
- [Attack demonstrations](#attack-demonstrations)
- [Technology stack](#technology-stack)
- [Project structure](#project-structure)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running with real CAN hardware](#running-with-real-can-hardware)
- [API reference](#api-reference)
- [WebSocket stream](#websocket-stream)
- [Testing](#testing)
- [Deployment](#deployment)
- [Screenshots](#screenshots)
- [Troubleshooting](#troubleshooting)
- [Security limitations](#security-limitations)
- [Known limitations](#known-limitations)
- [Future improvements](#future-improvements)
- [License](#license)

---

## The problem

The CAN bus was designed in the 1980s for reliability in a closed system, and
it shows: **there is no authentication, no encryption, and no sender identity**.
Any device physically attached to the bus can transmit any message, and every
ECU will believe it.

That was acceptable when the only things on the bus were factory-installed
modules. It is not acceptable now that vehicles expose infotainment systems,
telematics modems, OBD-II dongles, and over-the-air update channels — each one
a potential route onto the same bus that carries braking and steering data.

Two attacks follow directly from the missing authentication:

| Attack | How it works | Why it matters |
| --- | --- | --- |
| **Message spoofing** | An attacker transmits a frame with a legitimate ECU's identifier — say, vehicle speed — and receivers cannot tell it apart from the genuine one. | Instrument clusters, ADAS features and transmission logic all act on a value that is simply false. |
| **Bus flooding (DoS)** | CAN arbitration gives the lowest identifier priority. Flooding the bus with `0x000` frames starves every other ECU of bus access. | Legitimate safety messages are delayed or never delivered. |

Because the protocol cannot be fixed without replacing every ECU in the
vehicle, the practical defence is **detection**: watch the bus, learn what
normal looks like, and raise an alert when it stops looking normal.

That is what CAN-Sentinel does.

---

## What CAN-Sentinel does

```
 ┌─────────────┐   ┌──────────────┐   ┌──────────┐   ┌───────────────┐   ┌──────────┐
 │  Simulator  │──▶│CAN interface │──▶│ Receiver │──▶│   Detection   │──▶│ Database │
 │      or     │   │  (abstract)  │   │ pipeline │   │    engine     │   │ + stream │
 │  real bus   │   └──────────────┘   └──────────┘   └───────────────┘   └────┬─────┘
 └─────────────┘                                                              │
                                                          REST + WebSocket ◀──┘
                                                                   │
                                                          ┌────────▼─────────┐
                                                          │  React dashboard │
                                                          └──────────────────┘
```

- **Generates a realistic vehicle bus** — seven periodic frames (engine RPM,
  coolant temperature, vehicle speed, brakes, steering, transmission, body
  control) driven by a small vehicle model, at their true periods, so the
  values are physically coherent. ~285 msg/s with no hardware required.
- **Monitors any CAN source** through one abstraction: the built-in virtual
  bus, a real adapter via `python-can`, or a deterministic mock for tests.
- **Detects four classes of attack** with four independent detectors, each
  producing an explicit verdict and the evidence behind it.
- **Records everything** to SQLite with bounded retention, and streams live
  events to the browser over a WebSocket.
- **Presents it as a security operations dashboard** — live trace, alert feed
  with expandable evidence, analytics, attack simulation controls, system
  health, and live-tunable thresholds.

Everything is wired end-to-end. There are no mock responses, no hardcoded
chart data, and no buttons that do nothing.

---

## Quick start

```bash
git clone <your-repository-url> CAN-Sentinel
cd CAN-Sentinel

# Backend
python -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt   # Windows: backend\.venv\Scripts\pip
cd backend && ../backend/.venv/bin/uvicorn app.main:app --reload

# Dashboard, in a second terminal
cd frontend && npm install && npm run dev
```

Dashboard on <http://localhost:5173>, API docs on <http://localhost:8000/docs>.
Go to the **Simulator** page and press **Start**. Traffic appears immediately.
Switch the mode to **Fake Speed** or **CAN Flood** and press **Apply mode** to
watch detection happen live.

For a scripted walkthrough that narrates each phase:

```bash
python scripts/demo.py
```

See [Installation](#installation) for platform-specific detail, or `make dev`
to run both servers together if you have `make`.

---

## Architecture

The system is layered so that no component knows more than it needs to. The
detectors do not know where frames came from; the pipeline does not know how
they are stored; the dashboard does not know whether the bus is real.

```
                         ┌──────────────────────────────────────┐
                         │        ApplicationState              │
                         │   (composition root; owns all)       │
                         └──────────────────────────────────────┘
                                          │
    ┌──────────────┬────────────┬─────────┴────────┬──────────────┬─────────────┐
    ▼              ▼            ▼                  ▼              ▼             ▼
┌────────┐   ┌──────────┐  ┌─────────┐      ┌───────────┐  ┌───────────┐ ┌───────────┐
│Monitor │   │Simulation│  │Pipeline │      │ Detection │  │ Storage   │ │Broadcaster│
│service │   │ service  │  │         │      │  engine   │  │ writer +  │ │(WebSocket)│
└───┬────┘   └────┬─────┘  └────┬────┘      └─────┬─────┘  │ retention │ └─────┬─────┘
    │             │             │                 │        └─────┬─────┘       │
    ▼             ▼             │           ┌─────┴─────┐        ▼             ▼
┌─────────────────────────┐     │           │ 4 detectors│   ┌────────┐   ┌─────────┐
│   BaseCanInterface      │─────┘           └───────────┘   │ SQLite │   │ Clients │
│ virtual │ python-can │ mock │                             └────────┘   └─────────┘
└─────────────────────────┘
```

Three decisions shape everything else:

**1. The CAN interface is an abstraction, not a driver.**
`BaseCanInterface` defines `open`/`close`/`send`/`receive`/`receive_batch` with
bounded queues and drop accounting. `VirtualCanInterface` is an in-process
loopback bus; `PythonCanInterface` drives real hardware from a reader thread;
`MockCanInterface` is scriptable for tests. Swapping between them is one
environment variable, and nothing downstream changes.

**2. The event throttler is what makes the monitor survivable.**
Under a 2000 msg/s flood the detectors produce a verdict 2000 times a second.
Writing a row and pushing a WebSocket frame for each would turn the monitor
into the denial of service it exists to detect. The throttler collapses a
continuing condition into one event per cooldown, records how many were
suppressed in the evidence, and **still emits immediately when severity
escalates** — so a worsening attack is never hidden behind a cooldown.

> Measured on the reference machine: a 2286 msg/s flood produced **15 stored
> events and 29,133 suppressed verdicts**, with zero frames dropped anywhere
> and a median `/api/health` latency of **6 ms**.

**3. Nothing blocks the receive loop.**
Database writes go to a bounded queue drained by a background task on a worker
thread. WebSocket frames go to per-client bounded queues with their own sender
tasks, so one slow browser cannot stall the pipeline. Every queue counts what
it drops, and those counters are on the System page.

Full detail in [`docs/architecture.md`](docs/architecture.md).

---

## Detection engine

Four detectors run over every frame. Each returns an **explicit** verdict —
`NORMAL`, `SUSPICIOUS`, or `ATTACK` — never `None`, never a silent pass.

| Detector | Catches | Method |
| --- | --- | --- |
| **Fake Speed** | Forged vehicle-speed frames | Magnitude against a plausible range, **plus** a kinematic check that catches a spoofed value still inside the normal range |
| **CAN Flood** | Bus saturation / DoS | Message rate over a **rolling time window**, globally and per identifier |
| **ID Anomaly** | Unauthorised transmitters | Arbitration IDs outside the vehicle's known set, escalating when they persist |
| **Frequency Anomaly** | Frame injection, ECU suppression | Observed period against a catalogued or learned baseline |

Two design points worth calling out:

- **The flood detector is rate-based, never cumulative.** A counter that only
  goes up would eventually trip on any long-running session and could never
  recover. Samples expire out of the window, stale per-identifier buckets are
  swept once per window, and memory stays bounded over arbitrarily long runs —
  which the test-suite asserts directly.

- **The frequency detector freezes its learned baseline.** For an identifier
  not in the signal catalog it learns a period from the first samples and then
  stops learning. A detector that kept re-learning would quietly accept the
  very attack it exists to catch.

Severity ladder:

| Level | Meaning |
| --- | --- |
| `INFO` | Normal traffic |
| `LOW` / `MEDIUM` | Suspicious — worth attention, not yet conclusive |
| `HIGH` | Confirmed attack |
| `CRITICAL` | Extreme magnitude (e.g. flood beyond the critical multiplier) |

Every event carries structured evidence — the observed value, the threshold it
crossed, the rule that fired, and how many repeats were suppressed — so an
alert can be justified rather than merely asserted.

Full detail, including every threshold and its rationale, in
[`docs/detection.md`](docs/detection.md).

---

## The dashboard

Seven pages, all driven by live backend data:

| Page | What it is for |
| --- | --- |
| **Dashboard** | The whole network at a glance: status, rate, totals, attacks, active alerts, bus-load chart with threshold lines, attack distribution, live trace, and detector status. |
| **Live Traffic** | Full CAN trace with decoded signal values, search, identifier filter, sort, attacks-only filter, and pause-to-inspect. |
| **Security** | Every persisted event with expandable evidence, filters by type/severity/status, and triage (acknowledge / resolve). |
| **Analytics** | Bus-load history, attack frequency over time by severity, type and severity distribution, busiest and most suspicious identifiers, detector activity. |
| **Simulator** | Mode control, attack parameters, live vehicle state, and single-frame injection. |
| **System** | Monitor, interface, storage, writer, retention, detector internals, audit trail, and WebSocket state. |
| **Settings** | Live-tunable detection thresholds, bus parameters and retention limits, with server-side validation. |

The interface is built to read like a security operations console: a dark,
low-chroma surface so alert colour actually means something, monospaced
numerics for anything an engineer will compare, and severity encoded as **text
plus colour** rather than colour alone.

When an attack begins, the alert appears without a refresh, the threat badge
changes, counters increment, the chart updates, and the offending frames are
highlighted in the trace — all from the same WebSocket event.

---

## Attack demonstrations

Each of these can be driven from the Simulator page, or from the command line.
Detection typically appears within one to three seconds.

### 1. Normal traffic (the baseline)

```bash
curl -X POST localhost:8000/api/simulation/start \
     -H 'Content-Type: application/json' -d '{"mode":"NORMAL"}'
```

**Expect:** ~285 msg/s across 7 identifiers, threat level `NORMAL`, and **zero
alerts**. A monitor that cries wolf on clean traffic is worthless, so this is
the most important case in the suite.

### 2. Fake Speed attack

```bash
curl -X POST localhost:8000/api/simulation/mode \
     -H 'Content-Type: application/json' \
     -d '{"mode":"FAKE_SPEED","fake_speed_value":255,"fake_speed_rate":100}'
```

Forged `0x300` frames reporting 255 km/h are injected **alongside** the genuine
ECU, which keeps transmitting at 50 Hz — exactly what a real injection looks
like.

**Expect:**
- `FAKE_SPEED` · **HIGH** · confidence ≈ 0.82
  > *Forged vehicle speed: 255.0 km/h reported on 0x300, above the 200 km/h attack threshold*
- `FREQUENCY_ANOMALY` · **MEDIUM** — because 0x300 is now transmitting ~3× its
  20 ms baseline. Two independent detectors corroborating one attack.

### 3. CAN Flood attack

```bash
curl -X POST localhost:8000/api/simulation/mode \
     -H 'Content-Type: application/json' -d '{"mode":"CAN_FLOOD","flood_rate":1500}'
```

Floods the bus with `0x000` — the highest-priority identifier, which is what a
real DoS injector would choose.

**Expect:**
- `CAN_FLOOD` · **CRITICAL** · bus rate ~1785 msg/s, ~3× the 600 msg/s threshold
- `ID_ANOMALY` · **CRITICAL** — `0x000` is not in the allowlist
- Zero dropped frames; suppressed-verdict count climbing into the thousands

### 4. Identifier anomaly

```bash
for i in $(seq 6); do
  curl -X POST localhost:8000/api/simulation/inject \
       -H 'Content-Type: application/json' -d '{"can_id":291,"data":"DEADBEEF"}'
done
```

**Expect:** `ID_ANOMALY` · **SUSPICIOUS** on the first sighting, escalating to
**ATTACK** once `0x123` persists past the escalation count.

### 5. Recovery

```bash
curl -X POST localhost:8000/api/simulation/mode \
     -H 'Content-Type: application/json' -d '{"mode":"NORMAL"}'
```

**Expect:** the flood detector's measured rate returns below the threshold
within one window; the dashboard's threat badge clears once the 30-second
active-alert window elapses. Both behaviours are asserted by the test-suite.

Step-by-step scripts and expected output: [`docs/simulation.md`](docs/simulation.md).

---

## Technology stack

| Layer | Choice | Why |
| --- | --- | --- |
| API | **FastAPI** + Uvicorn | Async, and generates the OpenAPI docs from the same models that validate requests |
| Validation | **Pydantic v2** | One schema validates the CAN frame, the API body and the config document |
| CAN | **python-can** | The standard Python CAN library; used only behind the interface abstraction |
| Storage | **SQLAlchemy 2.0** + SQLite | Synchronous on purpose — SQLite serialises writes anyway, and it keeps the batching writer simple to reason about |
| Migrations | **Alembic** | Reversible schema, verified both directions |
| Dashboard | **React 18** + TypeScript + Vite | Strict types end-to-end from the API models |
| Styling | **Tailwind CSS** | A single design-token set keeps seven pages visually coherent |
| Charts | **Recharts** | Composable, and lets threshold reference lines sit on the same axis as the data |
| Tests | **pytest** + Vitest + Testing Library | 387 tests |
| Deployment | systemd / process manager + nginx | See [docs/deployment.md](docs/deployment.md) |

---

## Project structure

```
CAN-Sentinel/
├── backend/
│   ├── app/
│   │   ├── api/routes/       REST endpoints and the WebSocket
│   │   ├── can/              Frame model, signal catalog, interface abstraction
│   │   │   ├── message.py        CanMessage — validated, immutable
│   │   │   ├── signals.py        Encode/decode for the seven vehicle frames
│   │   │   ├── interface.py      BaseCanInterface
│   │   │   ├── virtual.py        In-process loopback bus
│   │   │   ├── python_can.py     Real hardware
│   │   │   └── mock.py           Scriptable, for tests
│   │   ├── core/             Settings, logging, errors, runtime config
│   │   ├── detection/        Detector contract, four detectors, the engine
│   │   ├── models/           SQLAlchemy ORM models
│   │   ├── schemas/          API request/response models
│   │   ├── services/         Pipeline, monitor, simulation, statistics, streaming
│   │   ├── simulation/       Vehicle model, modes, traffic generator
│   │   ├── storage/          Engine, repositories, batching writer, retention
│   │   └── main.py           Application factory
│   ├── alembic/              Migrations
│   └── tests/                336 tests
├── frontend/
│   └── src/
│       ├── components/       charts · layout · security · traffic · ui
│       ├── hooks/            Polling, live-data contexts, rate series
│       ├── pages/            The seven pages
│       ├── providers/        WebSocket provider with auto-reconnect
│       ├── services/         Typed REST client
│       ├── types/            Mirrors of the backend schemas
│       └── utils/            Formatting and the severity vocabulary
├── simulator/                Standalone CLI traffic generator
├── config/profiles/          Ready-made threshold profiles
├── docs/                     Architecture, API, detection, simulation, testing, deployment
├── scripts/                  demo.py · setup_vcan.sh · verify.sh
├── tests/                    Black-box tests against a running deployment
├── Makefile
└── .env.example
```

---

## Installation

**Prerequisites:** Python 3.12+, Node.js 20+.

<details open>
<summary><b>Linux / macOS</b></summary>

```bash
make install        # creates the venv and installs both toolchains
make env            # creates .env from .env.example
make dev            # runs backend and dashboard together
```

Without `make`:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
cd frontend && npm install && cd ..
cp .env.example .env

cd backend && ../backend/.venv/bin/uvicorn app.main:app --reload   # terminal 1
cd frontend && npm run dev                                          # terminal 2
```

</details>

<details>
<summary><b>Windows</b></summary>

`make` is not usually available, so run the commands directly. PowerShell:

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements-dev.txt
cd frontend; npm install; cd ..
Copy-Item .env.example .env

# Terminal 1
cd backend; ..\backend\.venv\Scripts\python -m uvicorn app.main:app --reload
# Terminal 2
cd frontend; npm run dev
```

Two Windows-specific notes:

- The event loop's timer granularity is ~15.6 ms, coarser than the 10 ms
  engine-RPM frame period. The simulator compensates by emitting catch-up
  frames stamped at their scheduled times, so the measured frame rate is
  correct on Windows too.
- SocketCAN does not exist on Windows. Use `CAN_INTERFACE=virtual` (the
  default), or a vendor adapter with the matching `CAN_BUSTYPE`.

</details>

Both servers reload on save. The dashboard proxies `/api` and `/ws` to the
backend, so the browser stays on one origin exactly as it does in production.

---

## Configuration

Everything is environment-driven, documented inline in
[`.env.example`](.env.example). Nothing reads `os.environ` directly — it all
flows through one validated `Settings` object.

The values you are most likely to change:

```bash
CAN_INTERFACE=virtual                # virtual | python-can | mock
CAN_CHANNEL=can0
CAN_BITRATE=500000

FLOOD_THRESHOLD=600                  # msg/s; above this the bus rate is an attack
FLOOD_WINDOW_SECONDS=1
FAKE_SPEED_THRESHOLD=200             # km/h
ALLOWED_CAN_IDS=0x100,0x200,0x300,0x400,0x500,0x600,0x700

DATABASE_URL=sqlite:///./data/can_sentinel.db
```

Ready-made profiles live in [`config/profiles/`](config/profiles/):
`high-sensitivity` for demonstrations, `low-noise` for long runs,
`hardware-socketcan` for a real bus.

**Detection thresholds are also tunable at runtime** from the Settings page or
`PUT /api/config`. Detection changes take effect on the very next frame; bus
changes apply the next time the monitor starts, and the response tells you
which is which. Invalid combinations are rejected atomically — nothing is
half-applied.

---

## Running with real CAN hardware

The same code path serves hardware; only the backend changes.

```bash
# Linux: create a virtual CAN interface to try it without an adapter
sudo scripts/setup_vcan.sh                 # creates and brings up vcan0

# Point CAN-Sentinel at it
CAN_INTERFACE=python-can CAN_BUSTYPE=socketcan CAN_CHANNEL=vcan0 \
  uvicorn app.main:app --app-dir backend

# Generate traffic onto the real bus from another terminal
python simulator/can_sentinel_sim.py --backend python-can --channel vcan0
```

For a physical adapter, set `CAN_BUSTYPE` to the matching `python-can`
interface (`socketcan`, `pcan`, `kvaser`, `vector`, `slcan`, …) and
`CAN_CHANNEL` to the device name.

> Before trusting the identifier-anomaly detector on a real vehicle, replace
> `ALLOWED_CAN_IDS` with that vehicle's actual identifier set — otherwise every
> genuine frame is reported as an anomaly.

**Only monitor a vehicle you own or are explicitly authorised to test.** The
frame-injection features write to the bus; never point them at a moving
vehicle.

---

## API reference

Interactive documentation is generated from the code at **`/docs`** (Swagger)
and **`/redoc`**. 24 endpoints; the full reference with request and response
examples is in [`docs/api.md`](docs/api.md).

| Area | Endpoints |
| --- | --- |
| **System** | `GET /api/health` · `GET /api/status` · `GET /api/version` · `GET /api/system/events` |
| **Traffic** | `GET /api/messages` · `/messages/recent` · `/traffic/statistics` · `/traffic/rate` |
| **Security** | `GET /api/attacks` · `/attacks/recent` · `/attacks/statistics` · `/attacks/{id}` · `/security/summary` · `PATCH /api/attacks/{id}` |
| **Simulation** | `POST /api/simulation/start` · `/stop` · `/mode` · `/reset` · `/inject` · `GET /api/simulation/status` |
| **Monitor** | `POST /api/monitor/start` · `/stop` · `GET /api/monitor/status` |
| **Config** | `GET /api/config` · `PUT /api/config` · `POST /api/config/reset` |

Every failure returns the same envelope, so clients have one thing to handle:

```json
{
  "error": "invalid_can_message",
  "message": "the supplied CAN frame is not valid",
  "details": { "errors": [{ "field": "arbitration_id", "error": "exceeds the standard (11-bit) range" }] }
}
```

---

## WebSocket stream

One endpoint — **`/ws/traffic`** — carries every live update.

```json
{
  "event": "ATTACK_DETECTED",
  "timestamp": "2025-01-03T12:00:00.500000+00:00",
  "sequence": 1421,
  "data": { "attack_type": "FAKE_SPEED", "severity": "HIGH", "evidence": { "...": "..." } }
}
```

| Event | Cadence |
| --- | --- |
| `SYSTEM_STATUS` | On connect (seeds the dashboard immediately), then every 5 s |
| `CAN_MESSAGE` | Batched every 250 ms, sampled under load — carries `count`, `observed` and `sampled` so the UI can be honest about what it is showing |
| `ATTACK_DETECTED` | Immediately, per reportable event |
| `TRAFFIC_RATE_UPDATE` | Every second |
| `SIMULATION_STATUS` / `MONITOR_STATUS` / `CONFIG_UPDATED` | On change |

Frames are batched rather than sent individually because pushing 2000 frames a
second would saturate the socket and lock up the browser — the dashboard needs
a *readable* stream and an *accurate* rate, and gets both.

Clients may send `{"action":"ping"}` or `{"action":"status"}`. Anything else
gets an error frame rather than a dropped connection. The dashboard reconnects
automatically with exponential backoff and jitter.

---

## Testing

```bash
make test          # or: cd backend && pytest -q
make test-frontend # or: cd frontend && npx vitest run
make verify        # every gate: lint, typecheck, tests, build
```

| Suite | Count | Covers |
| --- | --- | --- |
| Backend unit + integration | **336** | Frame validation, all four detectors, engine and throttling, storage, writer, retention, simulator, vehicle model, all three interfaces, config, logging, REST API, WebSocket, full attack scenarios |
| Dashboard | **51** | Formatting and the severity vocabulary, the API client's error handling, component rendering and accessibility |
| Live deployment | opt-in | Black-box HTTP against a running instance, including the nginx proxy and real latency |

**Backend coverage: 94%.**

The tests that matter most are the ones that assert the awkward cases:

- Normal traffic raises **zero** alerts (the false-positive gate).
- The flood detector's memory does not grow over a 200-second run.
- The frequency detector's learned baseline is **frozen** against a later attack.
- A forged sample never becomes the kinematic baseline, so a clean recovery is
  not itself reported as an anomaly.
- Under a 2000 msg/s flood, no frame is dropped at any layer and every frame
  the interface received reached the detection engine.
- Escalating severity bypasses the cooldown; de-escalating does not.

Details, including why the latency assertion lives in the live suite rather
than the in-process one, are in [`docs/testing.md`](docs/testing.md).

---

## Deployment

Run the backend with any process manager (systemd, NSSM, pm2, ...) and serve
the dashboard's production build (`npm run build`) from any static file host
or reverse proxy. Putting both behind one origin avoids CORS entirely.

Full instructions — systemd unit file, nginx reverse-proxy config, TLS,
environment for production, database backups, and a hardening checklist — are
in [`docs/deployment.md`](docs/deployment.md).

---

## Screenshots

Screenshots are not committed to the repository. To capture your own, follow
the short recipe in [`docs/screenshots/README.md`](docs/screenshots/README.md) —
it lists the exact sequence that produces the most representative views
(normal traffic, an active Fake Speed attack, the evidence panel, and the flood
plateau on the Analytics chart).

---

## Troubleshooting

<details>
<summary><b>The dashboard says "Backend unreachable" or "Reconnecting"</b></summary>

The API is not answering. Check `curl localhost:8000/api/health`. In
development, confirm the Vite dev server is proxying to the right place — set
`VITE_PROXY_TARGET` if the backend is not on `localhost:8000`. The dashboard
keeps retrying with backoff and shows a banner rather than a blank screen, so
historical data stays usable while the stream is down.
</details>

<details>
<summary><b>No traffic appears</b></summary>

Monitoring and simulation are separate. The monitor opens the bus; the
simulator puts traffic on it. Check `GET /api/simulation/status` — if it says
`running: false`, press **Start** on the Simulator page. Starting the
simulation will start the monitor for you and says so in the response.
</details>

<details>
<summary><b>Normal traffic is raising flood alerts</b></summary>

`FLOOD_THRESHOLD` is below your bus's normal load. The simulated bus runs at
~285 msg/s; a real powertrain bus is often much busier. Measure your baseline
on the Analytics page, then set the threshold well above it — the
`hardware-socketcan` profile starts at 2500 msg/s for this reason.
</details>

<details>
<summary><b>Every frame on my real vehicle is an ID anomaly</b></summary>

Expected: `ALLOWED_CAN_IDS` still holds the simulator's identifiers. Replace it
with your vehicle's actual set, or clear it entirely — an empty allowlist
disables the detector explicitly and says so in its verdict, rather than
silently reporting everything as clean.
</details>

<details>
<summary><b>"could not open CAN channel" in python-can mode</b></summary>

The adapter is missing, the interface is down, or the `CAN_BUSTYPE` is wrong.
On Linux, `ip link show can0` should report `UP`; use
`sudo scripts/setup_vcan.sh` to create a virtual bus for testing. The API keeps
serving when the interface fails to open — the failure is recorded as a system
event and shown on the System page, rather than taking the process down.
</details>

<details>
<summary><b>Tests fail with "database is locked" or an sqlite3 InterfaceError</b></summary>

Should not happen on a current build. Access to a shared in-memory SQLite
connection is serialised, and both background writers stop gracefully before
the engine is disposed, because `asyncio.to_thread` work cannot be cancelled.
If you hit it, make sure no stray server is holding the same database file.
</details>

---

## Security limitations

**CAN-Sentinel is a demonstration and research platform.** Please read this
section before drawing any conclusion from it.

- **It is not a vehicle safety system.** It is not developed to ISO 26262, has
  no functional-safety analysis, no ASIL rating, and no automotive validation.
  Nothing here should influence a real vehicle's behaviour.
- **The thresholds are illustrative.** 200 km/h, 600 msg/s and 15 km/h/s were
  chosen so attacks are visible within seconds against the built-in simulator.
  They are not derived from any standard and would need to be established
  empirically for any real vehicle.
- **Detection is not prevention.** The system observes and reports. It does not
  filter, block, or alter bus traffic, and on an unauthenticated bus it
  fundamentally cannot.
- **A sophisticated attacker can evade it.** These detectors look for
  statistical and range anomalies. An attacker who suppresses the genuine ECU
  and injects at exactly its rate, with values inside the plausible range,
  would not trip any of them. That limit is inherent to anomaly detection, and
  the real fix is message authentication (AUTOSAR SecOC or similar).
- **Checksums are not a control.** The signal catalog decodes the counter and
  additive checksum that many production ECUs carry, and the UI displays them —
  but no detector relies on them, because the simulator's spoofing modes
  compute a valid checksum exactly as a competent attacker would.
- **The API is unauthenticated.** It is intended for a trusted local network or
  a laptop. It exposes controls that transmit onto the bus. Put it behind
  authentication and TLS before exposing it anywhere else.
- **Only test what you are authorised to test.** Injecting frames onto a
  vehicle bus can affect its behaviour. Never point this at a moving vehicle or
  one you do not own.

---

## Known limitations

- **A frame that stops entirely** produces no further frames to inspect, so the
  frequency detector cannot report complete silence — only lateness in frames
  that do arrive. Detecting a fully silenced ECU needs a per-identifier
  liveness timer, which is listed below.
- **A learned frequency baseline is only as good as the traffic it was learned
  from.** If an unknown identifier first appears *during* an attack, the attack
  rate becomes its baseline. Catalogued identifiers are unaffected.
- **SQLite serialises writes.** Fine for a single-node monitor at the rates
  measured here; a multi-node deployment or sustained multi-thousand msg/s
  recording would want a server database.
- **Sustained throughput is bounded by the Python event loop.** The measured
  ceiling on the reference machine is roughly 2300 msg/s end-to-end with
  recording on. Higher rates need `PERSIST_CAN_MESSAGES=false`, or a different
  runtime for the hot path.
- **The dashboard samples the frame stream** under load. Counters and rates
  stay exact; the visible trace does not show every frame, and says so.

---

## Future improvements

- **Per-identifier liveness timers** to close the silenced-ECU gap above.
- **Machine-learning detection** — an autoencoder or one-class SVM over frame
  timing and payload entropy, to catch attacks that stay inside every
  configured range. Worth doing *after* the rule-based layer, not instead of it:
  rules are explainable, and an alert without evidence is hard to act on.
- **DBC file import** so the signal catalog comes from a real vehicle database
  instead of a hand-written one.
- **Replay from `candump` logs** for offline analysis of captured traffic.
- **Message authentication demonstration** — implement AUTOSAR SecOC-style
  MACs on the simulated bus to show what actually fixes the root cause.
- **Multi-bus monitoring**, since real vehicles have several segmented buses.
- **Alert forwarding** to syslog, webhook or a SIEM.
- **Authentication and TLS** on the API.

---

## License

Released under the [MIT License](LICENSE).

Built as an engineering demonstration of automotive network security
monitoring. If you use it for teaching or research, the
[Security limitations](#security-limitations) section is the part worth
repeating to your audience.
