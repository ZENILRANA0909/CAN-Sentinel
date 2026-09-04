# Architecture

How CAN-Sentinel is put together, and why it is put together that way.

- [Layers](#layers)
- [The data flow](#the-data-flow)
- [The CAN abstraction](#the-can-abstraction)
- [The frame model](#the-frame-model)
- [The pipeline](#the-pipeline)
- [Concurrency model](#concurrency-model)
- [Back-pressure and bounded state](#back-pressure-and-bounded-state)
- [Storage](#storage)
- [Streaming](#streaming)
- [Configuration](#configuration)
- [Error handling](#error-handling)
- [Lifecycle](#lifecycle)
- [Performance](#performance)
- [Decisions and trade-offs](#decisions-and-trade-offs)

---

## Layers

Each layer knows only about the one beneath it. The detectors do not know where
frames came from, the pipeline does not know how they are stored, and the
dashboard does not know whether the bus is real.

| Layer | Package | Responsibility |
| --- | --- | --- |
| Interface | `app/api` | HTTP routes, WebSocket, request validation, error translation |
| Services | `app/services` | Pipeline, monitor lifecycle, simulation control, statistics, streaming |
| Domain | `app/detection`, `app/simulation` | Detectors, engine, vehicle model, traffic generation |
| CAN | `app/can` | Frame model, signal catalog, interface abstraction and backends |
| Storage | `app/storage`, `app/models` | Engine, repositories, batching writer, retention |
| Core | `app/core` | Settings, runtime config, logging, error hierarchy |

Dependencies point strictly downward. `app/detection` imports from `app/can`
and `app/core`; nothing in `app/can` imports a service. That is what makes the
detectors testable with a handful of hand-built frames and no application at
all.

## The data flow

There is exactly one path a frame can take, and it is the same whether the
frame came from the simulator or a physical adapter:

```
Simulator ──send()──▶ CanInterface ──receive_batch()──▶ MonitorService
                                                              │
                                                              ▼
                                                     MessagePipeline
                                                              │
                     ┌────────────────┬───────────────────────┼──────────────────┐
                     ▼                ▼                       ▼                  ▼
              TrafficStatistics  DetectionEngine     PersistenceWriter      Broadcaster
                (in-memory)      (4 detectors)        (bounded queue)      (per-client queues)
                                       │                      │                  │
                                       ▼                      ▼                  ▼
                               DetectionResult[]          SQLite            WebSocket clients
                                       │
                                       ▼
                                EventThrottler ──▶ reportable events
```

The composition root is `ApplicationState` (`app/services/state.py`). It builds
every service once, wires the dependencies, and owns startup and shutdown.
Routes reach it through a FastAPI dependency rather than a module-level
singleton — which is exactly what lets the test-suite construct a fully
isolated application, with its own database and its own services, per test.

## The CAN abstraction

`BaseCanInterface` is the seam that makes the rest of the system
hardware-agnostic:

```python
class BaseCanInterface(abc.ABC):
    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def send(self, message: CanMessage) -> None: ...
    async def receive(self, timeout: float | None = 0.5) -> CanMessage | None: ...
    async def receive_batch(self, max_items: int, timeout: float = 0.25) -> list[CanMessage]: ...
```

The base class owns the bounded inbound queue, the lifecycle state machine
(`CLOSED → OPENING → OPEN | ERROR`), and the statistics — so every backend gets
consistent drop accounting for free.

| Backend | Class | Notes |
| --- | --- | --- |
| `virtual` | `VirtualCanInterface` | In-process loopback. `send()` delivers to `receive()`. This is what makes the whole system demonstrable with no hardware. |
| `python-can` | `PythonCanInterface` | Real adapters. `python-can` is blocking and thread-oriented, so a daemon thread drains `bus.recv()` and hands frames back with `loop.call_soon_threadsafe`. |
| `mock` | `MockCanInterface` | Scriptable, with a transmit log and injectable failures. Used by the test-suite. |

`receive_batch` exists for throughput: one `await` per batch instead of one per
frame, which is the difference between keeping up with a flood and falling
behind it.

## The frame model

`CanMessage` is a frozen Pydantic model, and it is where invalid data stops.
Validation covers the identifier range (11-bit vs 29-bit, checked against the
`is_extended_id` flag), the payload limit (8 bytes classic, the discrete CAN FD
lengths otherwise), DLC/payload consistency, non-negative timestamps and a
non-empty channel. Payloads are accepted as `bytes`, `bytearray`, `list[int]`
or a hex string in any common spelling.

It is frozen because a frame that has been admitted to the pipeline is
evidence: nothing downstream should be able to alter what was observed.

Alongside it, `app/can/signals.py` is a small hand-written signal catalog — the
role a DBC file plays for a real vehicle. It gives the seven simulated frames
encoders and decoders, so the UI can show `speed = 96.4 km/h` instead of raw
bytes, and so the Fake Speed detector has a well-defined signal to inspect.

## The pipeline

`MessagePipeline.process_batch` runs each stage over the whole batch:

1. **Analyse** — the detection engine runs all four detectors.
2. **Record** — statistics fold the frame into rolling counters.
3. **Decorate** — attach the decoded signals, the label, and any verdict.
4. **Buffer** — append to the bounded in-memory ring used by the live view.
5. **Persist** — hand rows to the writer's queue (non-blocking).
6. **Stream** — buffer the frame for the next flush; publish alerts immediately.

Batch orientation keeps the per-frame cost low. The in-memory ring is what
`/api/messages/recent` serves, so the live view is current even before the
batching writer has committed — while `/api/messages` queries the database for
history.

## Concurrency model

Everything runs on one asyncio event loop, with blocking work pushed off it:

| Task | Cadence | Purpose |
| --- | --- | --- |
| `can-sentinel-monitor` | Continuous | Drains the interface into the pipeline |
| `can-sentinel-simulator` | 5 ms tick | Generates traffic |
| `can-sentinel-db-writer` | 0.5 s | Commits batched rows on a worker thread |
| `can-sentinel-ws-flush` | 250 ms | Flushes the sampled frame buffer |
| `can-sentinel-telemetry` | 1 s | Samples statistics, publishes rate updates |
| `can-sentinel-retention` | 60 s | Prunes old rows on a worker thread |
| `can-sentinel-ws-<id>` | Per client | One sender task per WebSocket client |

Every database call from async code goes through `asyncio.to_thread`, so the
loop is never blocked on disk.

**One subtlety worth recording, because it caused a real bug:**
`asyncio.to_thread` work **cannot be cancelled**. Cancelling the task that
awaits it leaves the worker thread running — and if the engine is disposed
meanwhile, that thread uses a closed SQLite connection and the process dies
with a native access violation. Both the writer and the retention service
therefore stop by *signalling an event and awaiting the loop*, never by
cancelling it mid-write.

## Back-pressure and bounded state

A monitor that runs out of memory under attack is worse than no monitor. Every
buffer in the system is bounded, and every drop is counted and surfaced.

| Buffer | Bound | Overflow behaviour |
| --- | --- | --- |
| Interface inbound queue | `CAN_RECEIVE_QUEUE_SIZE` (20 000) | Drop **oldest**, count it — keeps the monitor current rather than stalling the producer |
| Writer message queue | `DB_WRITE_QUEUE_SIZE` (20 000) | Drop, count |
| Writer **event** queue | 5 000, separate | Dedicated so a traffic flood can never push an attack record out — dropping evidence would defeat the product |
| Live history ring | `HISTORY_BUFFER_SIZE` (2 000) | Discard oldest |
| Per-client WebSocket queue | `WS_CLIENT_QUEUE_SIZE` (200) | Drop oldest, count per client |
| Flood detector window | Time-based, plus a hard cap | Expire by timestamp; sweep stale identifiers once per window |
| Frequency detector | 96 arrivals per ID, 4 096 IDs | Evict least-recently-active |
| Throttle table | 8 192 keys | Prune keys that have not recurred |

The detectors' bounds are asserted directly by tests: a 200-second run must not
accumulate state, and a table of 300 identifiers must shrink to one once the
others fall out of the window.

## Storage

Three tables, all indexed on the columns the API actually filters by:

| Table | Holds | Key indexes |
| --- | --- | --- |
| `can_messages` | Recorded traffic | `timestamp`, `can_id`, `flagged`, `(timestamp, can_id)`, `(can_id, timestamp)` |
| `security_events` | Detections that crossed the reporting threshold | `timestamp`, `attack_type`, `severity`, `status`, `detector`, `can_id` |
| `system_events` | Lifecycle audit trail | `timestamp`, `event_type`, `severity` |

Timestamps are stored as epoch floats: every query in the product is a range or
ordering query, and a float comparison beats parsing a datetime on SQLite.

SQLAlchemy is used **synchronously** on purpose. An async driver buys nothing
here — SQLite serialises writes regardless — and it would make the batching
writer considerably harder to reason about. Instead every call is pushed to a
worker thread.

`PersistenceWriter` batches rows and commits them in one transaction.
`RetentionService` enforces both a row-count ceiling and a maximum age. Alembic
owns migrations; `create_all` is the fallback so a fresh clone and the
test-suite work without a migration step.

> **On the in-memory database:** SQLite's `:memory:` mode needs a `StaticPool`,
> which hands every thread the *same* connection — and sqlite3 raises
> `InterfaceError: bad parameter or other API misuse` if two threads use one
> connection at once. `Database.session()` therefore serialises access with a
> lock when (and only when) the pool shares a connection. A file-backed
> database uses a `QueuePool`, gives each thread its own connection, and needs
> no lock.

## Streaming

`Broadcaster` fans events out to connected dashboards, deliberately with two
different delivery paths:

- **Security and status events are published immediately.** An attack alert
  that arrives a quarter of a second late is a worse product.
- **Raw frames are buffered and flushed on a timer,** carrying a *sample* plus
  the true observed count. Under a 2000 msg/s flood, pushing every frame would
  saturate the socket and lock the browser up. The dashboard needs a readable
  stream and an accurate rate; the `sampled` and `observed` fields let it be
  honest about the difference.

Each client has its own bounded queue and its own sender task, so one lagging
browser can never stall the pipeline or the other clients. That is asserted by
a test that connects a client which never drains.

## Configuration

Two layers, deliberately distinct:

- **`Settings`** — process configuration, read once from the environment, cached
  and immutable. Nothing else in the codebase reads `os.environ`.
- **`ConfigService` / `RuntimeConfig`** — the tunable subset (detection
  thresholds, allowlist, bus parameters, retention), changeable at runtime
  through `PUT /api/config`.

Detectors hold a reference to the `ConfigService`, not to individual values, and
read thresholds through a property on every frame. That is why a threshold
change takes effect on the very next frame with no rebuild — and why a test can
flip a verdict mid-stream by changing configuration.

Updates are validated as a whole document before being applied, so an invalid
combination is rejected atomically and nothing is left half-changed. Fields
that only take effect on the next monitor start are reported back in
`restart_required`.

## Error handling

Every deliberate error derives from `CanSentinelError` and carries an HTTP
status and a stable error code, so the API layer can translate it into one
consistent envelope without leaking a stack trace:

| Exception | Status | Code |
| --- | --- | --- |
| `InvalidCanMessageError` | 422 | `invalid_can_message` |
| `ConfigurationError` | 400 | `configuration_error` |
| `ResourceNotFoundError` | 404 | `not_found` |
| `SimulationError` / `MonitorError` | 409 | `simulation_error` / `monitor_error` |
| `CanInterfaceError` / `StorageError` | 503 | `can_interface_error` / `storage_error` |

Failures are contained rather than propagated:

- A detector that raises is logged; the other detectors still run.
- A malformed frame from hardware is discarded without taking down the reader.
- The monitor failing to open the bus is recorded as a system event; the API
  keeps serving.
- A WebSocket client that errors is disconnected; the broadcaster continues.
- A configuration listener that raises does not break the update.

## Lifecycle

Startup, in dependency order: schema → writer → retention → broadcaster →
telemetry → monitor (if `MONITOR_AUTOSTART`) → simulator (if
`SIMULATOR_AUTOSTART`). Shutdown reverses it and tolerates partial startup, so
a failure halfway through still tears down cleanly.

Every transition is written to `system_events`, which is what lets a reviewer
answer *"was the monitor actually running when that attack was recorded?"*
after the fact.

## Performance

Measured on the reference machine (Windows 11, Python 3.13, SQLite on disk):

| Metric | Value |
| --- | --- |
| Detection engine throughput | ~11,850 frames/s (all four detectors) |
| Sustained end-to-end rate | ~2,300 msg/s with full recording |
| Simulated normal bus | 285 msg/s across 7 identifiers |
| `/api/health` under a 2286 msg/s flood | 6 ms median, 144 ms max |
| Frames dropped at 2286 msg/s | 0 (interface and writer) |
| Events emitted vs suppressed at that rate | 15 vs 29,133 |

The end-to-end ceiling is the Python event loop, not the detectors. Beyond it,
`PERSIST_CAN_MESSAGES=false` removes the largest remaining cost.

## Decisions and trade-offs

**Synchronous SQLAlchemy over an async driver.** SQLite serialises writes
anyway; the batching writer is far easier to reason about synchronously; and
`asyncio.to_thread` keeps the loop free. The cost is one extra thread hop per
query.

**Rate-based flood detection, never cumulative.** A counter that only goes up
would eventually trip on any long session and could never recover. The cost is
carrying a rolling window of timestamps — bounded, and swept once per window.

**Throttled event emission.** Without it a flood writes thousands of rows a
second and floods the WebSocket. The cost is that repeats inside a cooldown are
counted rather than individually stored, which is why the suppressed count
travels in the evidence. Escalation always bypasses the cooldown.

**Sampled frame streaming.** The alternative is an unusable dashboard under
load. The cost is that the visible trace is not every frame — so the payload
says so explicitly, and the counters remain exact.

**Frozen learned baselines.** A detector that kept re-learning would adapt to
the attack it is meant to catch. The cost is that an identifier first seen
*during* an attack learns the wrong baseline — documented as a known
limitation.

**One shared WebSocket for the whole dashboard, split across two React
contexts.** Raw frames arrive several times a second while status changes
rarely; keeping them in separate contexts means a page showing only counters
does not re-render on every frame batch.
