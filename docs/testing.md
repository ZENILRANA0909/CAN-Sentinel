# Testing

387 automated tests, plus an opt-in suite that runs against a live deployment.

- [Running the tests](#running-the-tests)
- [The three suites](#the-three-suites)
- [Backend coverage](#backend-coverage)
- [What the tests actually assert](#what-the-tests-actually-assert)
- [Test design](#test-design)
- [Why latency is measured in the live suite](#why-latency-is-measured-in-the-live-suite)
- [Bugs the tests found](#bugs-the-tests-found)
- [Adding a detector test](#adding-a-detector-test)

---

## Running the tests

```bash
make verify              # every gate: lint, typecheck, tests, build
```

Individually:

```bash
cd backend && pytest -q                          # 336 tests, ~38 s
cd backend && pytest --cov=app --cov-report=term-missing
cd backend && ruff check .

cd frontend && npx vitest run                    # 51 tests, ~4 s
cd frontend && npx tsc -b --noEmit
cd frontend && npx eslint .
cd frontend && npm run build

# Black-box, against a running instance
# start the backend, then:
CAN_SENTINEL_URL=http://localhost:8000 pytest tests/ -v
```

Useful selectors:

```bash
pytest tests/test_detectors_flood.py -v
pytest -k "recovery or throttl" -v
pytest -m integration          # end-to-end scenarios only
pytest -m "not slow"
```

---

## The three suites

| Suite | Location | Count | Speed | Covers |
| --- | --- | --- | --- | --- |
| Backend | `backend/tests/` | 336 | ~38 s | Everything below the HTTP layer, plus the API and WebSocket in-process |
| Dashboard | `frontend/src/**/*.test.*` | 51 | ~4 s | Formatting, the API client, component rendering and accessibility |
| Live deployment | `tests/` | opt-in | varies | Black-box HTTP against a real server, including the nginx proxy |

### Backend

| File | Tests | Focus |
| --- | --- | --- |
| `test_can_message.py` | 40 | Frame validation: identifier ranges, payload limits, CAN FD lengths, DLC consistency, immutability, `python-can` interop |
| `test_detectors_fake_speed.py` | 22 | Magnitude and kinematic rules, boundaries, recovery, live retuning |
| `test_detectors_flood.py` | 20 | Window behaviour, thresholds, bursts, expiry, per-identifier flood, **memory bounds** |
| `test_detectors_anomaly.py` | 26 | Identifier allowlist and escalation; frequency baselines, learning and freezing |
| `test_detection_engine.py` | 27 | Aggregation, throttling, escalation, fault isolation |
| `test_storage.py` | 33 | Database, repositories, pagination, the batching writer, retention |
| `test_simulator.py` | 46 | Signal codec, vehicle model, all three interfaces, every simulation mode |
| `test_core.py` | 49 | Settings, runtime config, logging, error hierarchy, pipeline validation |
| `test_api.py` | 47 | Every endpoint: success, validation, conflict, not-found |
| `test_websocket.py` | 19 | Handshake, commands, event stream, malformed input, slow clients |
| `test_integration.py` | 14 | Full attack scenarios end-to-end |

---

## Backend coverage

**94% overall.** The uncovered remainder is almost entirely the `python-can`
hardware backend, which cannot be exercised without an adapter.

| Area | Coverage |
| --- | --- |
| `app/detection/` | 92–98% |
| `app/services/` | 88–99% |
| `app/storage/` | 86–93% |
| `app/can/` (excluding hardware) | 78–98% |
| `app/can/python_can.py` | 25% — needs real hardware |
| `app/core/` | 96–98% |
| `app/simulation/` | 96–99% |

Coverage is a floor, not a goal. The tests below are the ones worth reading.

---

## What the tests actually assert

The valuable tests are the awkward ones — the cases where a naive
implementation looks fine until it does not.

### No false positives on clean traffic

```python
async def test_normal_traffic_raises_no_alerts(client):
    await client.post("/api/simulation/start", json={"mode": "NORMAL"})
    await asyncio.sleep(3.0)
    summary = (await client.get("/api/security/summary")).json()
    assert summary["attacks_total"] == 0
    assert summary["threat_level"] == "NORMAL"
```

A monitor that cries wolf is worthless. This is the single most important test
in the suite, and it is why the default thresholds are calibrated against the
simulator's actual 285 msg/s load rather than picked from the air.

The kinematic equivalent runs the vehicle model for 5 000 steps and asserts the
worst acceleration stays under the detector's plausibility limit — so the
guarantee holds by construction, not by luck.

### Detector memory does not grow

```python
def test_window_does_not_grow_without_limit(detector):
    for second in range(200):
        burst(detector, 20, start=1000.0 + second, span=0.9)
    state = detector.snapshot()["state"]
    assert state["samples_retained"] <= 40      # not 200 seconds' worth
```

This is the bug a cumulative counter would have. A companion test feeds 300
identifiers and asserts the table shrinks to one after the window passes —
which is what caught a real defect where stale per-identifier buckets were only
swept at capacity.

### A learned baseline is frozen against a later attack

```python
def test_learned_baseline_is_frozen_against_a_later_attack(detector):
    stream(detector, can_id=0x321, period=0.05, count=30)         # learn 50 ms
    result = stream(detector, can_id=0x321, period=0.002, count=40, start=1100.0)
    assert result.detected is True
    assert result.evidence["expected_period_ms"] == pytest.approx(50.0, rel=0.05)
```

A detector that kept re-learning would quietly accept the attack it exists to
catch.

### Recovery is not itself an alert

```python
def test_returns_to_normal_after_an_attack_stops(detector):
    detector.inspect(make_speed_message(60.0, 1000.0))
    assert detector.inspect(make_speed_message(255.0, 1001.0)).threat_level is ThreatLevel.ATTACK
    recovered = detector.inspect(make_speed_message(62.0, 1005.0))
    assert recovered.threat_level is ThreatLevel.NORMAL
```

Because a forged sample never becomes the kinematic baseline, the drop from a
spoofed 255 km/h back to a real 62 km/h is not reported as a second attack.

### Escalation always beats the cooldown

```python
def test_escalation_bypasses_the_cooldown():
    throttler.should_emit("k", Severity.MEDIUM, now=100.0, cooldown=60.0)
    emit, _ = throttler.should_emit("k", Severity.CRITICAL, now=100.1, cooldown=60.0)
    assert emit is True
```

An attack that is getting worse must never be hidden behind a cooldown. The
converse is also asserted: de-escalation does not bypass it.

### Nothing is dropped under flood

```python
async def test_nothing_is_dropped_under_flood(client):
    await client.post("/api/simulation/start", json={"mode": "CAN_FLOOD", "flood_rate": 2000.0})
    ...
    assert interface["dropped"] == 0
    assert writer["messages_dropped"] == 0
    assert status["detection"]["analysed_messages"] == interface["received"]
```

Every frame the interface received reached the detection engine — the property
that would silently break if any queue were mis-sized.

### One broken detector does not stop the others

A deliberately exploding detector is registered alongside a real one; the real
one still produces its verdict and the pipeline continues.

### One slow client cannot stall the pipeline

A WebSocket client that never drains its queue is connected; the broadcaster
drops frames for that client alone, counts them, and keeps serving everyone
else.

---

## Test design

**Complete isolation.** Every test gets its own `ApplicationState` with its own
in-memory database and its own services. Nothing is shared at module scope, so
tests can run in any order and cannot leak state.

**Deterministic time.** Detector tests pass explicit timestamps rather than
sleeping:

```python
def burst(detector, count, *, start, span=0.9):
    step = span / max(count - 1, 1)
    for index in range(count):
        detector.inspect(make_message(timestamp=start + index * step))
```

Exactly 150 frames spread over 0.9 s is exactly 150 msg/s against a 1 s window.
No sleeps, no flakiness, and the arithmetic in the assertion is obvious.

**Polling, never fixed sleeps,** where real time is unavoidable (integration
tests wait on background tasks). `poll_until` retries with a timeout, so a slow
machine is slow rather than failing.

**Configuration as a test tool.** Because detectors read thresholds through the
config service on every frame, a test can flip a verdict mid-stream:

```python
assert detector.inspect(msg(150.0)).threat_level is ThreatLevel.SUSPICIOUS
config_service.update({"detection": {"fake_speed_threshold": 100.0, ...}})
assert detector.inspect(msg(150.0)).threat_level is ThreatLevel.ATTACK
```

**Locale independence.** One frontend test originally asserted
`formatCompact(1_500_000)` matched `1.5M`; on an `en-IN` runner `Intl` produces
`15L`. The assertion now checks the contract — a materially shorter string —
rather than one locale's spelling.

---

## Why latency is measured in the live suite

The in-process suite runs the application on the **same event loop as the
test**, through httpx's `ASGITransport`. Under a 2000 msg/s flood the simulator,
the receive loop and the test driver all compete for that one loop, and ten
health checks measured 40–170 seconds.

That number says nothing about the product. Measured against a real Uvicorn
server, the same flood gives:

| Metric | Value |
| --- | --- |
| `/api/health` × 10 | 0.25 s total, **6 ms median**, 144 ms max |
| `/api/status` × 10 | 0.28 s total, 31 ms median |
| Bus rate | 2286 msg/s |
| Frames dropped | 0 |
| Events emitted / suppressed | 15 / 29,133 |

So the in-process test asserts what it can validly assert — every request
succeeds, and no frame is dropped at any layer — and the latency assertion
lives in `tests/test_live_deployment.py`, where it runs against a real server
over a real socket.

This distinction matters more generally: **an in-process ASGI harness is a
correctness tool, not a performance one.**

---

## Bugs the tests found

Recorded because they are the honest argument for writing the tests.

| Bug | Found by |
| --- | --- |
| Stale per-identifier buckets in the flood detector were only swept at capacity, so a scanning attacker could leave state behind and `top_talkers` reported rates for silent identifiers | `test_identifier_table_is_pruned` |
| `asyncio.to_thread` work cannot be cancelled — cancelling the writer or retention task left a worker thread using a SQLite connection **after** the engine was disposed, crashing the process with a native access violation | A hard crash during integration teardown |
| A shared in-memory SQLite connection used by two worker threads raised `InterfaceError: bad parameter or other API misuse`; `healthcheck` bypassed the lock that fixed it | The API returning 503 under flood |
| Searching `0x300` never matched, because the needle was uppercased but `can_id_hex` was not — present in both the backend filter and the dashboard filter | `test_history_filters` |
| A sub-millisecond learned period rendered as `"0 ms"` in an event description | The scripted demonstration |
| The simulator halved a frame's period when it fell behind, inflating its rate and making the frequency detector see an injection that was really scheduler lag | Comparing measured vs catalogued rates |
| Windows' ~15.6 ms timer granularity starved the 10 ms frame, so 100 Hz was measured as 64 Hz | The same rate comparison |
| The default 100 msg/s flood threshold sat below the simulator's own 285 msg/s normal load, so clean traffic raised alerts | The first end-to-end run |
| A per-identifier flood threshold above the global one is unreachable configuration, since one identifier cannot out-rate the whole bus | A test fixture that tried to set it |

---

## Adding a detector test

```python
@pytest.fixture
def detector(config_service):
    return MyDetector(config_service)


class TestMyDetector:
    def test_clean_traffic_is_normal(self, detector):
        result = detector.inspect(make_message(can_id=0x100, timestamp=1000.0))
        assert result.threat_level is ThreatLevel.NORMAL
        assert result.detected is False

    def test_the_boundary(self, detector):
        # State the exact threshold in a comment: the number in the assertion
        # should never be a mystery to the next reader.
        assert detector.inspect(at_threshold).threat_level is ThreatLevel.SUSPICIOUS
        assert detector.inspect(just_over).threat_level is ThreatLevel.ATTACK

    def test_evidence_explains_the_verdict(self, detector):
        evidence = detector.inspect(attack_frame).evidence
        assert evidence["rule"] == "the_rule_that_fired"
        assert evidence["observed_value"] > evidence["threshold"]

    def test_state_is_bounded(self, detector):
        for second in range(200):
            feed_one_second(detector, start=1000.0 + second)
        assert detector.snapshot()["state"]["tracked_ids"] < 100

    def test_it_recovers(self, detector):
        drive_attack(detector)
        assert quiet_period_then_normal(detector).threat_level is ThreatLevel.NORMAL
```

Every detector should have all five: a clean case, both sides of the boundary,
evidence that justifies the verdict, a bound on memory, and a recovery.
