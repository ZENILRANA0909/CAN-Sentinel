# Simulation and attack demonstrations

The simulator is what makes CAN-Sentinel demonstrable on a laptop with no
hardware. This page covers how it works and exactly how to run each
demonstration.

- [Why simulate](#why-simulate)
- [The vehicle model](#the-vehicle-model)
- [The signal catalog](#the-signal-catalog)
- [Modes](#modes)
- [Running the demonstrations](#running-the-demonstrations)
- [The scripted walkthrough](#the-scripted-walkthrough)
- [The standalone CLI](#the-standalone-cli)
- [Presenting this to an audience](#presenting-this-to-an-audience)

---

## Why simulate

Attacking a real vehicle bus needs a vehicle, an adapter, and permission —
and it is genuinely dangerous. The simulator removes all three obstacles
without weakening the demonstration, because **the generated frames travel the
same path as real ones**: the same interface abstraction, the same receiver,
the same pipeline, the same detectors, the same storage.

Nothing downstream of `BaseCanInterface` can tell the difference. That is the
property that makes the demonstration honest — the detection you watch happen
is the detection that would happen on a real bus.

---

## The vehicle model

Random bytes would be trivially detectable and would prove nothing. The
simulator instead runs a small vehicle model so the values on the bus are
**coherent**: engine RPM follows road speed through a gear ratio, the brake
light comes on while the car is slowing, coolant temperature warms and holds,
the odometer accumulates.

It cycles through a drive pattern:

```
IDLE ──▶ ACCELERATING ──▶ CRUISING ──┬──▶ BRAKING ──▶ IDLE
                              ▲      │
                              └──────┘
```

| Property | Value |
| --- | --- |
| Speed range | 0 – 118 km/h |
| Acceleration | 3.2 km/h/s |
| Braking | 5.5 km/h/s |
| Engine | 780 rpm idle – 6500 rpm, first-order lag so RPM never steps |
| Gears | 6 forward, selected by road speed |

The rates matter. Both are comfortably inside the Fake Speed detector's
15 km/h/s plausibility limit, which is **why normal driving never raises a
kinematic alert** — a property asserted over 5 000 simulated steps in the
test-suite rather than assumed.

---

## The signal catalog

Seven periodic frames, at realistic periods for a powertrain bus:

| CAN ID | Signal | ECU | DLC | Period | Rate |
| --- | --- | --- | --- | --- | --- |
| `0x100` | Engine RPM, load, throttle | ECM | 8 | 10 ms | 100 Hz |
| `0x200` | Coolant/oil temperature, fuel, ambient | ECM | 8 | 100 ms | 10 Hz |
| `0x300` | **Vehicle speed**, wheel pulses, direction | ABS | 8 | 20 ms | 50 Hz |
| `0x400` | Brake pressed, ABS active, pedal, pressure | ABS | 4 | 20 ms | 50 Hz |
| `0x500` | Steering angle, rate, torque | EPS | 6 | 20 ms | 50 Hz |
| `0x600` | Gear, drive mode, output shaft RPM | TCM | 6 | 50 ms | 20 Hz |
| `0x700` | Doors, lights, hazard | BCM | 4 | 200 ms | 5 Hz |

**Total: 285 msg/s.** That leaves ~47% headroom below the 420 msg/s suspicious
line, which is why a clean bus produces zero alerts.

Each frame is encoded the way a real ECU would: `0x300` carries speed as a
16-bit big-endian value at 0.01 km/h per bit, plus a rolling 4-bit counter and
an additive checksum. The catalog fills the role a DBC file plays for a real
vehicle, and it is what lets the dashboard show `speed = 96.4 km/h` instead of
raw bytes.

> The counter and checksum are decoded and displayed but are **not** a security
> control. The spoofing modes compute a valid checksum, exactly as a competent
> attacker would. See [detection.md](detection.md#what-this-cannot-detect).

### Timing

A fixed 5 ms tick with per-frame due times. On Windows the event loop's timer
granularity is ~15.6 ms — coarser than the 10 ms engine frame — so the
scheduler emits **catch-up frames stamped at their scheduled times** rather
than silently capping at one frame per tick. Without that, `0x100` would run at
64 Hz instead of 100 Hz and the frequency detector would see an anomaly that
was really just scheduler lag.

Attack traffic uses a rate accumulator with a burst cap scaled to actual
elapsed time, so the requested frames-per-second is met accurately without
spinning the loop.

---

## Modes

| Mode | Generates | Detectors expected to fire |
| --- | --- | --- |
| `NORMAL` | The seven frames at their true periods | *none* |
| `FAKE_SPEED` | Normal traffic **+** forged `0x300` frames | `FAKE_SPEED`, `FREQUENCY_ANOMALY` |
| `CAN_FLOOD` | Normal traffic **+** high-rate `0x000` frames | `CAN_FLOOD`, `ID_ANOMALY` |
| `MIXED` | Both attacks at once | all four |
| `CUSTOM` | Normal traffic **+** your own frames | depends on the frames |

Two details make the attacks realistic rather than caricatures:

**Fake Speed injects *alongside* the genuine ECU.** The real ABS module keeps
transmitting at 50 Hz while forged frames arrive at 100 Hz. That is what a real
injection looks like — and it is why the frequency detector fires too, since
`0x300`'s total rate is now three times its baseline. Two independent detectors
corroborating one attack is a far stronger signal than either alone.

**The flood uses `0x000`.** CAN arbitration gives the lowest identifier
priority, so `0x000` is precisely what a real denial-of-service injector would
choose. It is also outside the allowlist, so the identifier detector fires as
well.

Attack frames are tagged `source: INJECTED`, so the dashboard can distinguish
them from genuine ECU traffic in the live trace.

---

## Running the demonstrations

Everything below can be done from the **Simulator** page instead; the API calls
are shown so the demonstration is reproducible and scriptable.

Set a shell variable first:

```bash
API=http://localhost:8000/api
```

### 1. Normal traffic — the baseline

```bash
curl -X POST $API/simulation/start -H 'Content-Type: application/json' -d '{"mode":"NORMAL"}'
```

Wait ~10 seconds, then:

```bash
curl -s $API/status | jq '{
  rate: .traffic.current_rate_msg_per_s,
  ids:  .traffic.unique_can_ids,
  threat: .security.threat_level,
  attacks: .security.attacks_total
}'
```

**Expect:** `rate ≈ 285`, `ids: 7`, `threat: "NORMAL"`, **`attacks: 0`**.

This is the most important case in the whole demonstration. A monitor that
raises alerts on clean traffic is worthless, so show this first and let it run
long enough to be convincing.

### 2. Fake Speed attack

```bash
curl -X POST $API/simulation/mode -H 'Content-Type: application/json' \
     -d '{"mode":"FAKE_SPEED","fake_speed_value":255,"fake_speed_rate":100}'
sleep 5
curl -s "$API/attacks/recent?limit=4" | jq '.[] | {severity, attack_type, can_id_hex, description}'
```

**Expect:**

```
HIGH     FAKE_SPEED         0x300   Forged vehicle speed: 255.0 km/h reported on 0x300,
                                    above the 200 km/h attack threshold
MEDIUM   FREQUENCY_ANOMALY  0x300   0x300 arriving 3.0x faster than its 20 ms baseline -
                                    consistent with frame injection
```

Open the evidence panel on the Security page: it shows the observed speed, the
threshold crossed, the exact rule that fired, and how many repeat detections
the cooldown suppressed.

### 3. CAN Flood attack

```bash
curl -X POST $API/simulation/mode -H 'Content-Type: application/json' \
     -d '{"mode":"CAN_FLOOD","flood_rate":1500}'
sleep 8
curl -s $API/status | jq '{
  rate: .traffic.current_rate_msg_per_s,
  threat: .security.threat_level,
  emitted: .detection.events_emitted,
  suppressed: .detection.events_suppressed,
  dropped: .monitor.interface.statistics.dropped
}'
```

**Expect:** rate ~1785 msg/s, `threat: "ATTACK"`, `dropped: 0`, and a
`suppressed` count in the thousands against a handful `emitted` — the throttler
doing its job.

The Analytics page is the best view here: the bus-load plateau crossing both
threshold lines is the single clearest image of the system working.

### 4. Identifier anomaly

```bash
for i in $(seq 6); do
  curl -s -X POST $API/simulation/inject -H 'Content-Type: application/json' \
       -d '{"can_id":291,"data":"DEADBEEF"}' > /dev/null
done
sleep 2
curl -s "$API/attacks?attack_type=ID_ANOMALY&can_id=0x123&limit=3" | jq '.items[] | {severity, description}'
```

**Expect:** `SUSPICIOUS` on the first sighting, escalating to `ATTACK` once
`0x123` persists past the escalation count.

Try an allowlisted identifier the same way and observe that nothing fires —
useful for showing the detector is not simply flagging everything.

### 5. Recovery

```bash
curl -X POST $API/simulation/mode -H 'Content-Type: application/json' -d '{"mode":"NORMAL"}'
sleep 10
curl -s $API/status | jq '{
  rate: .traffic.current_rate_msg_per_s,
  flood_detector: (.detection.detectors[] | select(.name=="can_flood") | .state.current_rate_msg_per_s)
}'
```

**Expect:** both back to ~285 msg/s, well under the 600 msg/s threshold.

Two different recoveries are worth distinguishing out loud:

- The **detector** recovers immediately — its rolling window empties within one
  window period.
- The **dashboard's threat badge** clears after the 30-second active-alert
  window, because a SOC view should not forget an attack the instant it stops.

### 6. Mixed attack

```bash
curl -X POST $API/simulation/mode -H 'Content-Type: application/json' \
     -d '{"mode":"MIXED","flood_rate":1200,"fake_speed_value":255}'
```

All four detectors fire together. Good for showing the Analytics distribution
charts with every category populated.

### 7. Custom frames

```bash
curl -X POST $API/simulation/mode -H 'Content-Type: application/json' -d '{
  "mode": "CUSTOM",
  "custom_frames": [
    {"can_id": 291, "data": "DEADBEEF", "interval_ms": 50},
    {"can_id": 1911, "data": "0102030405060708", "interval_ms": 200}
  ]
}'
```

Normal traffic continues underneath, so the injected frames sit in a realistic
context.

---

## The scripted walkthrough

`scripts/demo.py` drives the whole sequence and narrates each phase — useful
for a live presentation, and as a smoke test after a deployment.

```bash
python scripts/demo.py                              # local dev server
python scripts/demo.py --url http://localhost:8000
python scripts/demo.py --step                       # pause between phases
python scripts/demo.py --flood-rate 2500 --speed 300 --dwell 12
```

It uses only the public API — every call is one you could make from the
dashboard or with curl.

---

## The standalone CLI

`simulator/can_sentinel_sim.py` generates the same traffic **onto a real bus**,
for running the backend in `python-can` mode against genuine bus traffic.

```bash
# Print frames without touching any hardware
python simulator/can_sentinel_sim.py --mode NORMAL --dry-run --duration 5

# Drive a Linux virtual CAN interface
sudo scripts/setup_vcan.sh
python simulator/can_sentinel_sim.py --backend python-can --channel vcan0

# Flood a real adapter for 20 seconds
python simulator/can_sentinel_sim.py --backend python-can --channel can0 \
    --mode CAN_FLOOD --flood-rate 1500 --duration 20

# Custom frames: CAN_ID:HEX:INTERVAL_MS, repeatable
python simulator/can_sentinel_sim.py --mode CUSTOM --custom 0x123:DEADBEEF:100 --dry-run
```

`--seed` makes the traffic reproducible, which is handy when comparing two
detector configurations against identical input.

---

## Presenting this to an audience

A sequence that works in about eight minutes:

1. **Open the Dashboard with nothing running.** "The system is online, the bus
   is quiet." Establishes that the numbers are real and start at zero.
2. **Start `NORMAL` and leave it.** Point at the seven identifiers, the decoded
   values in the live trace, and — most importantly — **zero alerts**. Say
   plainly that a monitor which cries wolf on clean traffic is useless.
3. **Switch to `FAKE_SPEED`.** The alert appears without a refresh. Open the
   evidence panel. Point out that *two* detectors fired for different reasons,
   and explain why: the value is implausible **and** the identifier is now
   transmitting three times too fast.
4. **Switch to `CAN_FLOOD` and move to Analytics.** The plateau crossing both
   threshold lines is the money shot. Mention `0x000` and why an attacker picks
   the lowest identifier.
5. **Show the System page during the flood.** Zero dropped frames, thousands of
   suppressed verdicts against a handful of stored events. This is the
   engineering, and it is the part most demonstrations skip.
6. **Return to `NORMAL`.** Show the detector recovering immediately and explain
   why the dashboard badge takes another 30 seconds.
7. **Open Settings, halve the flood threshold, save.** The next frame is judged
   by the new rule — no restart. Then reset.
8. **Close on the limitations.** Say what it cannot detect. An engineer who
   states the boundaries of their system is more credible than one who claims
   it has none — and [detection.md](detection.md#what-this-cannot-detect) lists
   them.
