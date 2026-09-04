# API reference

24 REST endpoints and one WebSocket. Interactive documentation is generated
from the code and served at **`/docs`** (Swagger UI) and **`/redoc`**; the
machine-readable schema is at `/openapi.json`.

Base path: `/api` (configurable via `API_PREFIX`).

- [Conventions](#conventions)
- [System](#system)
- [Traffic](#traffic)
- [Security](#security)
- [Simulation](#simulation)
- [Monitor](#monitor)
- [Configuration](#configuration)
- [WebSocket](#websocket)

---

## Conventions

**Errors.** Every failure returns the same envelope, so a client has exactly
one shape to handle:

```json
{
  "error": "invalid_can_message",
  "message": "the supplied CAN frame is not valid",
  "details": {
    "errors": [{ "field": "arbitration_id", "error": "exceeds the standard (11-bit) range" }]
  }
}
```

| Status | Code | Meaning |
| --- | --- | --- |
| 400 | `configuration_error` | The configuration is not usable; nothing was applied |
| 404 | `not_found` | No such resource |
| 409 | `simulation_error`, `monitor_error` | Invalid state transition (already running, etc.) |
| 422 | `validation_error`, `invalid_can_message` | The request failed validation |
| 500 | `internal_error` | Unexpected; the detail is in the log, never the response |
| 503 | `storage_error`, `can_interface_error` | A dependency is unavailable |

**Pagination.** List endpoints return a uniform envelope:

```json
{ "items": [], "total": 1420, "limit": 100, "offset": 0, "has_more": true }
```

`total` is the count matching the filter, ignoring pagination. `limit` accepts
1–1000.

**CAN identifiers** are accepted in query strings as decimal (`768`) or
hexadecimal (`0x300`), and always returned as both `can_id` (int) and
`can_id_hex` (string).

**Timestamps** are epoch seconds, with an ISO-8601 UTC `iso_timestamp`
alongside for display.

---

## System

### `GET /api/health`

Liveness and readiness. Used by process managers and by the dashboard to
detect a backend outage. Returns `degraded` rather than failing if the database
is unreachable.

```json
{
  "status": "healthy",
  "service": "can-sentinel",
  "version": "1.0.0",
  "environment": "production",
  "uptime_seconds": 128.4,
  "checks": {
    "database": { "connected": true, "healthy": true, "size_bytes": 4096 },
    "monitor": { "running": true },
    "simulator": { "running": false },
    "writer": { "running": true },
    "broadcaster": { "running": true }
  }
}
```

### `GET /api/status`

The composite snapshot behind the System page: `monitor`, `simulation`,
`detection`, `traffic`, `security`, `websocket`, `storage`, `telemetry`.

```bash
curl -s localhost:8000/api/status | jq '.traffic.current_rate_msg_per_s, .security.threat_level'
```

### `GET /api/version`

`{ "service", "version", "environment", "api_prefix" }`.

### `GET /api/system/events`

The audit trail — startup, shutdown, monitor and simulator transitions,
configuration changes, recorded errors.

| Parameter | Default | Notes |
| --- | --- | --- |
| `limit` | 50 | 1–500 |
| `event_type` | — | e.g. `MONITOR_STARTED` |

---

## Traffic

### `GET /api/messages`

Paginated query over persisted traffic.

| Parameter | Notes |
| --- | --- |
| `limit`, `offset` | 1–1000, ≥0 |
| `can_id` | `0x300` or `768` |
| `since`, `until` | Epoch seconds |
| `source` | `SIMULATOR`, `HARDWARE`, `INJECTED`, … |
| `flagged_only` | Only frames a detector flagged |
| `data_contains` | Hex substring of the payload |

### `GET /api/messages/recent`

The live view, served from the in-memory ring buffer — current even before the
batching writer has committed. Includes decoded signal values and any detector
verdict.

```json
{
  "timestamp": 1735900000.123,
  "can_id": 768,
  "can_id_hex": "0x300",
  "dlc": 8,
  "data": "17700000010000A5",
  "source": "SIMULATOR",
  "flagged": false,
  "label": "Vehicle Speed",
  "decoded": { "vehicle_speed_kmh": 60.0, "direction": "FORWARD", "checksum_valid": true },
  "attack_types": []
}
```

| Parameter | Notes |
| --- | --- |
| `limit` | 1–1000, default 100 |
| `can_id`, `flagged_only` | As above |
| `search` | Matches the payload or the identifier text |

### `GET /api/traffic/statistics`

Live counters plus per-identifier totals from the persisted history: rate,
peak, unique identifiers, flagged and invalid counts, `by_source`,
`top_can_ids`, `stored_messages`. `since_seconds` restricts the stored counts.

### `GET /api/traffic/rate`

Instantaneous rate, the per-second history behind the dashboard chart, and the
flood thresholds — so the chart can draw its threshold lines from the same
source the detector uses.

```json
{
  "current_rate_msg_per_s": 285.0,
  "peak_rate_msg_per_s": 1785.0,
  "history": [{ "timestamp": 1735900000.0, "rate_msg_per_s": 285.0, "attacks": 0 }],
  "flood_threshold_msg_per_s": 600.0,
  "flood_suspicious_threshold_msg_per_s": 420.0
}
```

---

## Security

### `GET /api/attacks`

Paginated query over persisted events. Filters: `attack_type`, `severity`,
`status`, `detector`, `can_id`, `since`, `until`. Invalid enum values are
rejected with 422.

### `GET /api/attacks/recent`

The newest events, with database IDs so they can be triaged.

```json
{
  "id": 42,
  "timestamp": 1735900000.5,
  "attack_type": "FAKE_SPEED",
  "threat_level": "ATTACK",
  "severity": "HIGH",
  "detector": "fake_speed",
  "can_id_hex": "0x300",
  "confidence": 0.82,
  "description": "Forged vehicle speed: 255.0 km/h reported on 0x300, above the 200 km/h attack threshold",
  "evidence": {
    "observed_speed_kmh": 255.0,
    "attack_threshold_kmh": 200.0,
    "exceeded_by_kmh": 55.0,
    "rule": "speed_above_attack_threshold"
  },
  "status": "NEW"
}
```

### `GET /api/attacks/statistics`

Distribution by type, severity, status and detector, the busiest identifiers,
and a bucketed timeline stacked by severity.

| Parameter | Default | Notes |
| --- | --- | --- |
| `since_seconds` | all time | Window to aggregate over |
| `bucket_seconds` | 60 | Timeline bucket width, 1–3600 |
| `buckets` | 60 | Buckets to return, 1–500 |

### `GET /api/security/summary`

One call backing the dashboard header, alert feed and detector panel: threat
level, active alerts, totals, recent events, and per-detector state.

### `GET /api/attacks/{event_id}` · `PATCH /api/attacks/{event_id}`

Fetch one event, or move it between `NEW`, `ACKNOWLEDGED` and `RESOLVED`.

```bash
curl -X PATCH localhost:8000/api/attacks/42 \
     -H 'Content-Type: application/json' -d '{"status":"ACKNOWLEDGED"}'
```

---

## Simulation

### `POST /api/simulation/start`

Starts the traffic generator, **starting the monitor first if it is not already
running** — the response reports this as `monitor_started`, so the convenience
is visible rather than magic. Returns 409 if the simulation is already running.

```jsonc
{
  "mode": "FAKE_SPEED",        // NORMAL | FAKE_SPEED | CAN_FLOOD | MIXED | CUSTOM
  "flood_rate": 1200,          // frames/s, CAN_FLOOD and MIXED
  "flood_can_id": 0,           // default 0x000, the highest-priority identifier
  "fake_speed_value": 255,     // km/h, FAKE_SPEED and MIXED
  "fake_speed_rate": 100,      // injected frames/s
  "traffic_scale": 1.0,        // multiplier on normal traffic
  "custom_frames": [           // required for CUSTOM
    { "can_id": 291, "data": "DEADBEEF", "interval_ms": 100 }
  ]
}
```

Every field is optional. All modes except `CUSTOM` also emit normal vehicle
traffic, so an attack is always layered over a realistic bus.

### `POST /api/simulation/mode`

Switches mode live without interrupting the stream. **Fields left out keep
their current value**, so switching to `FAKE_SPEED` does not silently reset
flood parameters you tuned a moment ago. The response includes `previous_mode`.

### `POST /api/simulation/stop` · `POST /api/simulation/reset`

Stop is idempotent. Reset returns the vehicle model and live counters to zero;
stored history is not deleted.

### `GET /api/simulation/status`

Running state, mode, generated rate, frame counts, the live vehicle model
(speed, RPM, gear, throttle, brake, coolant, fuel, steering, odometer), and the
list of available modes.

### `POST /api/simulation/inject`

Transmits one operator-supplied frame. Fully validated first — an out-of-range
identifier or oversized payload is rejected with 422 and never reaches the
detectors. The quickest way to demonstrate the identifier-anomaly detector.

```bash
curl -X POST localhost:8000/api/simulation/inject \
     -H 'Content-Type: application/json' -d '{"can_id":291,"data":"DEADBEEF"}'
```

Returns 202 with the accepted frame, or 409 if the bus is not open.

---

## Monitor

### `POST /api/monitor/start`

Opens the configured CAN interface and starts the receive loop. 409 if already
running; 503 if the interface cannot be opened (no adapter in `python-can`
mode, for instance) — with the channel and bus type in `details`.

### `POST /api/monitor/stop`

Stops the receive loop and closes the interface. **Stops the simulator first**,
since it would have nowhere to transmit. Idempotent.

### `GET /api/monitor/status`

Running state, uptime, batches processed, errors, and the interface's own
statistics — received, sent, **dropped**, errors, and queue depth.

---

## Configuration

### `GET /api/config`

The current runtime document: `detection`, `can`, `retention`, plus a
`revision` that increments on every change.

### `PUT /api/config`

Partial update — only the sections and fields supplied change.

```bash
curl -X PUT localhost:8000/api/config \
     -H 'Content-Type: application/json' \
     -d '{"detection": {"flood_threshold": 400, "fake_speed_threshold": 180}}'
```

```json
{
  "revision": 3,
  "changed": ["detection.flood_threshold", "detection.fake_speed_threshold"],
  "restart_required": [],
  "detection": { "...": "..." },
  "defaults_note": "Detection thresholds are demonstration values, not vehicle safety limits."
}
```

- **Detection changes take effect on the very next frame.**
- **Bus changes** (`can.channel`, `can.bitrate`, `can.interface`) apply the next
  time the monitor starts, and are listed in `restart_required`.
- **Invalid combinations are rejected atomically** with 400 — nothing is
  half-applied. Unknown fields are rejected with 422.

### `POST /api/config/reset`

Discards runtime edits and reloads the environment-provided defaults.

---

## WebSocket

### `/ws/traffic`

A push channel. On connect the server immediately sends a `SYSTEM_STATUS`
snapshot so the dashboard renders without waiting for the first tick.

**Envelope** — identical for every event:

```json
{
  "event": "ATTACK_DETECTED",
  "timestamp": "2025-01-03T12:00:00.500000+00:00",
  "sequence": 1421,
  "data": { }
}
```

| Event | Cadence | `data` |
| --- | --- | --- |
| `SYSTEM_STATUS` | On connect, then every 5 s | The `/api/status` document |
| `CAN_MESSAGE` | Every 250 ms | `{ messages[], count, observed, sampled, interval_ms }` |
| `ATTACK_DETECTED` | Immediately | One security event, with evidence |
| `TRAFFIC_RATE_UPDATE` | Every second | Rate, alert counts, threat level |
| `SIMULATION_STATUS` | On change | Simulator state |
| `MONITOR_STATUS` | On change | Monitor state |
| `CONFIG_UPDATED` | On change | `{ revision, config }` |

**On `CAN_MESSAGE` batching.** Frames are batched and *sampled* rather than
sent individually: at 2000 msg/s, one frame per message would saturate the
socket and lock up the browser. `count` is how many were sent, `observed` is
how many actually arrived, and `sampled` is true when they differ — so the UI
can be honest about showing a sample while its counters stay exact.

**Client commands** (optional):

```json
{"action": "ping", "id": 7}   →  {"event": "PONG",          "data": {"echo": 7}}
{"action": "status"}          →  {"event": "SYSTEM_STATUS", "data": {...}}
```

Anything else — an unknown action, malformed JSON, a non-object, or a frame
over 4 KB — gets an `ERROR` event rather than a dropped connection.

**Reliability.** Each client has its own bounded queue and sender task, so one
slow consumer cannot stall the pipeline or the other clients; frames are
dropped for that client alone and counted in `/api/status`. The server accepts
up to `WS_MAX_CLIENTS` (32) and closes further attempts with code 1013. The
dashboard reconnects automatically with exponential backoff and jitter, and
sends a heartbeat every 25 s.

### Minimal client

```python
import asyncio, json, websockets

async def main() -> None:
    async with websockets.connect("ws://localhost:8000/ws/traffic") as socket:
        async for raw in socket:
            event = json.loads(raw)
            if event["event"] == "ATTACK_DETECTED":
                data = event["data"]
                print(f"{data['severity']:8} {data['attack_type']:18} {data['description']}")

asyncio.run(main())
```
