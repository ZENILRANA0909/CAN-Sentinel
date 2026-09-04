# Detection engine

What each detector looks for, the exact rules it applies, and what it cannot
see.

> [!WARNING]
> **Every threshold on this page is a demonstration value.** They were chosen
> so that attacks are visible within seconds against the built-in simulator.
> None of them is derived from an automotive safety standard, and none should
> be treated as a safety limit. Thresholds for a real vehicle would have to be
> established empirically from that vehicle's measured baseline.

- [The contract](#the-contract)
- [Severity](#severity)
- [Fake Speed detector](#fake-speed-detector)
- [CAN Flood detector](#can-flood-detector)
- [Identifier anomaly detector](#identifier-anomaly-detector)
- [Frequency anomaly detector](#frequency-anomaly-detector)
- [The engine and event throttling](#the-engine-and-event-throttling)
- [Evidence](#evidence)
- [Tuning](#tuning)
- [What this cannot detect](#what-this-cannot-detect)

---

## The contract

Every detector implements the same interface and returns an **explicit**
verdict for every frame. There is no "return `None` and let the caller guess":

```python
class AttackDetector(abc.ABC):
    name: str
    attack_type: AttackType

    def inspect(self, message: CanMessage) -> DetectionResult: ...
    def reset(self) -> None: ...
    def throttle_key(self, result: DetectionResult) -> str: ...
```

`DetectionResult` always carries a `threat_level` of `NORMAL`, `SUSPICIOUS` or
`ATTACK`, a severity, a confidence, a human-readable description, and a
structured `evidence` dictionary.

Detectors are stateful — they observe traffic over time — but that state is
**bounded**. A detector whose memory grew without limit would be a denial of
service against the monitor it is meant to protect, so every window is expired
by time and every table is capped and swept. The test-suite asserts this
directly rather than assuming it.

Thresholds are read through `self.config` on every frame, so a change made via
`PUT /api/config` applies to the very next frame with no rebuild.

## Severity

| Threat level | Severity | When |
| --- | --- | --- |
| `NORMAL` | `INFO` | Nothing to report |
| `SUSPICIOUS` | `LOW` / `MEDIUM` | Worth attention, not yet conclusive |
| `ATTACK` | `HIGH` | Confirmed by the detector's rule |
| `ATTACK` | `CRITICAL` | Extreme magnitude — a detector escalates when the observation is far past the threshold |

Escalation to `CRITICAL` is per-detector and documented in each section below.

---

## Fake Speed detector

**Catches:** forged vehicle-speed frames — the classic CAN spoofing attack,
where an attacker transmits `0x300` and receivers cannot tell it from the real
ABS module.

**Signal:** bytes 0–1 of the frame configured in `SPEED_CAN_ID` (default
`0x300`), a 16-bit big-endian value at 0.01 km/h per bit.

### Rules, in order

**1. Malformed frame.** A speed frame shorter than two bytes cannot carry a
speed at all. A genuine ECU always emits the full frame, so this is itself a
spoofing indicator.
→ `SUSPICIOUS` / `MEDIUM`.

**2. Magnitude.** The reported speed against the configured range.

| Observed speed | Verdict |
| --- | --- |
| `< FAKE_SPEED_SUSPICIOUS_THRESHOLD` (120 km/h) | `NORMAL` |
| `>= 120` and `<= FAKE_SPEED_THRESHOLD` (200 km/h) | `SUSPICIOUS` / `MEDIUM` |
| `> 200 km/h` | `ATTACK` / `HIGH` |
| `>= 300 km/h` (1.5 × threshold) | `ATTACK` / `CRITICAL` |

Note the boundary: the rule is *above* the threshold, so exactly 200 km/h is
the top of the suspicious band, not yet an attack. The test-suite pins this.

**3. Kinematics.** Magnitude alone misses a spoof that stays inside the normal
range. So the detector also computes the rate of change between samples:

```
acceleration = Δspeed / Δt        (km/h per second)
```

If `|acceleration| > FAKE_SPEED_MAX_ACCELERATION` (15 km/h/s), no real vehicle
could have produced it. A jump from 20 to 119 km/h in one second is 99 km/h/s —
both values are below the suspicious threshold, and only this rule catches it.
→ `SUSPICIOUS`, escalating to `ATTACK` at 3× the limit.

The rule is suppressed across gaps longer than 2 seconds: a long gap means we
were not observing, not that the vehicle teleported.

### Why a forged sample never becomes the baseline

Only a sample the detector classified `NORMAL` updates the kinematic baseline.

Without that rule, when a spoof *stops* — say 255 km/h back to a real 62 km/h —
the detector would compare the real value against the forged one, compute an
enormous deceleration, and report the recovery as a second attack. Since the
forged sample never became the baseline, and the gap since the last trusted
sample exceeds the kinematic window, a clean recovery reports `NORMAL`.

### Configuration

```bash
SPEED_CAN_ID=0x300
FAKE_SPEED_THRESHOLD=200              # km/h
FAKE_SPEED_SUSPICIOUS_THRESHOLD=120   # km/h; must be <= the attack threshold
FAKE_SPEED_MAX_ACCELERATION=15        # km/h per second
```

The simulator's vehicle model accelerates at 3.2 km/h/s and brakes at
5.5 km/h/s — comfortably inside the 15 km/h/s limit, which is why normal
driving never trips this rule. A test asserts that bound over 5 000 simulated
steps.

---

## CAN Flood detector

**Catches:** bus saturation. CAN arbitration gives the lowest identifier
priority, so flooding with `0x000` starves every other ECU of bus access.

**Method:** message rate over a **rolling time window** — never a cumulative
counter. A counter that only goes up would eventually trip on any long-running
session and could never recover.

### Rules

Rate is measured as `frames in window ÷ window`, globally and per identifier.

| Observed bus rate | Verdict |
| --- | --- |
| `< threshold × suspicious_ratio` (420 msg/s) | `NORMAL` |
| `>= 420` and `<= FLOOD_THRESHOLD` (600 msg/s) | `SUSPICIOUS` / `MEDIUM` |
| `> 600 msg/s` | `ATTACK` / `HIGH` |
| `> threshold × critical_multiplier` (1200 msg/s) | `ATTACK` / `CRITICAL` |

Again, *above* the threshold: exactly 600 msg/s is the top of the suspicious
band.

**Targeted flood.** A single identifier exceeding `PER_ID_FLOOD_THRESHOLD`
(200 msg/s) is reported as an attack **even when the aggregate bus rate is
still normal** — that is the signature of an injection aimed at one ECU. Since
a single identifier's rate can never exceed the aggregate rate, the
configuration validator rejects a per-identifier threshold above the global one
as unreachable.

### Bounded memory

This is the part that makes it survivable:

- Global and per-identifier windows expire samples by timestamp on every frame.
- Stale per-identifier buckets are swept **once per window** — an identifier
  that stops transmitting would otherwise keep its bucket, and its stale
  timestamps, until the table hit its capacity limit. That also keeps
  `top_talkers` from reporting rates for identifiers that are no longer active.
- Hard caps (200 000 samples, 4 096 identifiers) guard against pathological
  bursts.

A test drives 200 seconds of traffic and asserts fewer than 40 retained
samples; another feeds 300 identifiers and asserts the table shrinks to one
after the window passes.

### Configuration

```bash
FLOOD_THRESHOLD=600              # msg/s
FLOOD_WINDOW_SECONDS=1
FLOOD_SUSPICIOUS_RATIO=0.7       # 0.7 × 600 = 420 msg/s
FLOOD_CRITICAL_MULTIPLIER=2.0    # 2 × 600 = 1200 msg/s
PER_ID_FLOOD_THRESHOLD=200       # msg/s; must be <= FLOOD_THRESHOLD
```

The simulated bus runs at ~285 msg/s, leaving ~47% headroom before the
suspicious line. On a real vehicle, measure the baseline on the Analytics page
first and set the threshold well above it.

---

## Identifier anomaly detector

**Catches:** anything transmitting that should not be — an aftermarket dongle,
a compromised ECU, an attacker's tool.

**Rationale:** a production vehicle bus is a closed system. The set of
arbitration IDs that can legitimately appear is fixed by the vehicle's network
design, so an identifier outside that set is by definition unexpected.

### Rules

| Condition | Verdict |
| --- | --- |
| Identifier in `ALLOWED_CAN_IDS` | `NORMAL` |
| Allowlist empty | `NORMAL`, explicitly reported as *"detector inactive"* |
| Unknown identifier, fewer than `ID_ANOMALY_ESCALATION_COUNT` sightings in the window | `SUSPICIOUS` / `MEDIUM` |
| Unknown identifier, `>= 5` sightings within `ID_ANOMALY_WINDOW_SECONDS` | `ATTACK` / `HIGH` |
| `>= 5×` the escalation count | `ATTACK` / `CRITICAL` |

A single unexpected frame is suspicious — it could be bus noise. An identifier
that keeps reappearing indicates an active injector, which is why sustained
transmission escalates.

An empty allowlist reports `NORMAL` **with an explanation**, rather than
silently reporting everything as clean. That distinction matters: an operator
must be able to tell "nothing wrong" from "not checking".

Sightings expire, so the detector de-escalates on its own once an injector
stops.

### Configuration

```bash
ALLOWED_CAN_IDS=0x100,0x200,0x300,0x400,0x500,0x600,0x700,0x7DF,0x7E0,0x7E8
ID_ANOMALY_ESCALATION_COUNT=5
ID_ANOMALY_WINDOW_SECONDS=5
```

On a real vehicle this list **must** be replaced with that vehicle's actual
identifier set, or every genuine frame is reported as an anomaly.

---

## Frequency anomaly detector

**Catches:** frame injection that has not yet changed a value enough to trip a
range check, and ECU suppression.

**Rationale:** most safety-relevant CAN frames are strictly periodic. The ABS
module sends vehicle speed every 20 ms; the ECM sends engine RPM every 10 ms.
Deviation from that period is itself a signal.

### Rules

The observed period is the **median** of recent inter-arrival times — median
rather than mean, so a single scheduling hiccup does not move it.

| Condition | Verdict |
| --- | --- |
| Fewer than `FREQUENCY_MIN_SAMPLES` intervals | `NORMAL` — *"collecting baseline"* |
| `expected / observed >= FREQUENCY_FAST_RATIO` (2.5×) | `SUSPICIOUS` / `MEDIUM` |
| `>= FREQUENCY_ATTACK_RATIO` (5×) | `ATTACK` / `HIGH` |
| `>= 3 × attack ratio` (15×) | `ATTACK` / `CRITICAL` |
| `observed / expected >= FREQUENCY_SLOW_RATIO` (2.5×) | `SUSPICIOUS` / `MEDIUM` |

**Too fast** means the genuine ECU is still transmitting *and* something else
is injecting the same identifier — which is exactly why a Fake Speed attack
also trips this detector. Two independent detectors corroborating one attack is
a much stronger signal than either alone.

**Too slow** means frames are missing: an ECU silenced, knocked into bus-off,
or losing arbitration to a flood. Slow is only ever `SUSPICIOUS`, because
lateness has many innocent causes.

### Baselines

- **Catalogued identifiers** use the period from the signal catalog.
- **Any other identifier** has its baseline *learned* from the first
  `FREQUENCY_MIN_SAMPLES` intervals — and then **frozen**.

Freezing is the important part. A detector that kept re-learning would quietly
adapt to the attack it exists to catch: inject steadily for a minute and the
"baseline" becomes the attack rate. A test asserts the frozen baseline survives
a later 25× injection.

Intervals longer than 5 seconds are excluded from the median, so pausing the
monitor does not corrupt the baseline.

### Configuration

```bash
FREQUENCY_MIN_SAMPLES=12
FREQUENCY_FAST_RATIO=2.5
FREQUENCY_ATTACK_RATIO=5.0
FREQUENCY_SLOW_RATIO=2.5
```

---

## The engine and event throttling

`DetectionEngine` runs all four detectors over every frame, aggregates the
worst threat level and severity, and decides which verdicts become persisted,
broadcast security events.

That last step is what keeps the monitor from becoming the problem. Under a
2000 msg/s flood the flood detector produces a verdict 2000 times a second.
Writing 2000 rows and pushing 2000 WebSocket frames per second would turn the
monitor into the denial of service it exists to observe.

`EventThrottler` collapses a continuing condition into one event per
`DETECTION_EVENT_COOLDOWN_SECONDS`, and:

- **carries the suppressed count** in the evidence as
  `suppressed_since_last_event`, so nothing is hidden;
- **emits immediately when severity escalates**, so an attack that is getting
  worse is never masked by a cooldown;
- does *not* bypass the cooldown when severity falls.

What counts as "the same condition" is the detector's `throttle_key`. Most
detectors scope it per identifier. The flood detector overrides it: bus
saturation is *one* condition (`can_flood:bus`) regardless of which identifier
the frame carried, while a targeted flood is one per identifier
(`can_flood:id:<n>`). Without that override a bus-wide flood would emit an
event per identifier.

Measured effect at 2286 msg/s: **15 events emitted, 29,133 suppressed.**

A detector that raises an exception is logged and skipped; the others still
run, and the pipeline continues. That is asserted by a test with a deliberately
broken detector.

## Evidence

Every event carries structured evidence, so an alert can be justified rather
than merely asserted:

```json
{
  "attack_type": "FAKE_SPEED",
  "can_id": "0x300",
  "observed_speed_kmh": 255.0,
  "previous_speed_kmh": 62.4,
  "acceleration_kmh_per_s": 192.6,
  "suspicious_threshold_kmh": 120.0,
  "attack_threshold_kmh": 200.0,
  "threshold_kmh": 200.0,
  "exceeded_by_kmh": 55.0,
  "payload": "63A50000010004B1",
  "rule": "speed_above_attack_threshold",
  "suppressed_since_last_event": 41
}
```

The `rule` field names exactly which branch fired, which is what makes an event
diagnosable months later — and is what the dashboard's expandable evidence
panel renders.

## Tuning

Three ways, in increasing permanence:

1. **The Settings page** — live, validated, effective on the next frame.
2. **`PUT /api/config`** — the same thing programmatically.
3. **Environment variables** — the defaults every restart returns to.

```bash
curl -X PUT localhost:8000/api/config \
     -H 'Content-Type: application/json' \
     -d '{"detection": {"flood_threshold": 400, "fake_speed_threshold": 180}}'
```

Invalid combinations are rejected atomically — `fake_speed_suspicious_threshold`
above `fake_speed_threshold`, or a per-identifier flood threshold above the
global one — and nothing is left half-applied.

Ready-made profiles are in [`../config/profiles/`](../config/profiles/).

**A tuning method that works:** run normal traffic for a few minutes, read the
peak bus load and per-identifier rates off the Analytics page, then set
`FLOOD_THRESHOLD` roughly 2× the observed peak and `PER_ID_FLOOD_THRESHOLD`
roughly 2× the busiest identifier. Then run each attack mode and confirm it is
caught with margin.

## What this cannot detect

Stated plainly, because a security tool that oversells itself is worse than
none:

- **A well-executed spoof.** An attacker who silences the genuine ECU and
  injects at exactly its rate, with values inside the plausible range and a
  physically plausible rate of change, trips none of these detectors. That is
  inherent to anomaly detection; the real fix is message authentication
  (AUTOSAR SecOC or similar).
- **A frame that stops entirely.** No frames means nothing to inspect, so the
  frequency detector reports lateness only in frames that *do* arrive. Catching
  a fully silenced ECU needs a per-identifier liveness timer — a known gap,
  listed as a future improvement.
- **An identifier first seen during an attack.** Its learned baseline becomes
  the attack rate. Catalogued identifiers are unaffected.
- **Payload semantics beyond the catalogued signals.** Only vehicle speed is
  range-checked. A forged coolant temperature or steering angle would pass
  every detector.
- **Physical-layer attacks** — bus-off induction, voltage-based ECU
  impersonation, transceiver-level manipulation. These need hardware
  instrumentation the platform does not have.
- **Counter and checksum manipulation.** The catalog decodes the rolling
  counter and additive checksum many production ECUs carry, and the UI shows
  them, but **no detector relies on them** — the simulator's spoofing modes
  compute a valid checksum, exactly as a competent attacker would. Treating a
  valid checksum as evidence of authenticity would be a false assurance.
