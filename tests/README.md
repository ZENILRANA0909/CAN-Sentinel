# Deployment tests

Black-box tests that drive a **running** CAN-Sentinel over HTTP, as opposed to
the in-process suite under [`../backend/tests`](../backend/tests).

They catch the class of problem that only appears once the system is deployed:
a broken reverse-proxy rule, a service that starts but cannot write its
database, a proxy that mangles the WebSocket upgrade, or real API latency under
a saturated bus.

Nothing runs unless you point them at a target, so they are safe to leave in a
default `pytest` invocation.

```bash
# against a local development server
CAN_SENTINEL_URL=http://localhost:8000 pytest tests/ -v

# against a production-style deployment behind a reverse proxy
CAN_SENTINEL_URL=https://can-sentinel.example.com pytest tests/ -v
```

> These tests start and stop the simulator on the target instance and inject
> frames onto its bus. Point them at a demonstration instance, never at
> anything you care about.
