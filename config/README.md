# Configuration profiles

Ready-made environment fragments for common situations. Each one changes only
the values it needs; everything else falls back to the defaults documented in
[`.env.example`](../.env.example).

Apply one by appending it to your `.env`:

```bash
cat config/profiles/high-sensitivity.env >> .env
```

Or export it before running the backend:

```bash
set -a; source config/profiles/hardware-socketcan.env; set +a
uvicorn app.main:app --app-dir backend
```

| Profile                     | Use it when                                                                 |
| --------------------------- | --------------------------------------------------------------------------- |
| `high-sensitivity.env`      | Demonstrating detection: fires early and often, at the cost of false alarms. |
| `low-noise.env`             | Long unattended runs: only clear-cut attacks are reported.                   |
| `hardware-socketcan.env`    | Monitoring a real bus through a SocketCAN adapter instead of the simulator.  |

> Detection thresholds in every profile are **demonstration values**. They are
> not derived from a vehicle safety standard. See [`../docs/detection.md`](../docs/detection.md).
