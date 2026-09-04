#!/usr/bin/env python3
"""Scripted attack demonstration against a running CAN-Sentinel instance.

Drives the documented end-to-end scenario through the public REST API and
prints what the detection engine concluded at each step. Useful for a live
presentation, and as a smoke test after a deployment.

    python scripts/demo.py                      # against http://localhost:8000
    python scripts/demo.py --url http://localhost:8080   # through the nginx proxy
    python scripts/demo.py --step               # pause between phases

Nothing here is special-cased: every call is one an operator could make from
the dashboard or with curl.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "http://localhost:8000"
TIMEOUT = 20.0

BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"


class DemoError(RuntimeError):
    """The demonstration could not continue."""


def _request(base: str, path: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    url = f"{base.rstrip('/')}/api{path}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise DemoError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise DemoError(
            f"cannot reach CAN-Sentinel at {base} ({exc.reason}). Is the backend running?"
        ) from exc
    return json.loads(payload) if payload else None


def heading(step: int, title: str) -> None:
    print(f"\n{BOLD}{CYAN}[{step}] {title}{RESET}")
    print(f"{DIM}{'-' * (len(title) + 5)}{RESET}")


def wait_for(base: str, predicate, *, timeout: float, description: str) -> bool:
    """Poll until ``predicate`` is satisfied, printing progress."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.5)
    print(f"  {YELLOW}! timed out waiting for {description}{RESET}")
    return False


def severity_colour(severity: str) -> str:
    return {"CRITICAL": RED, "HIGH": RED, "MEDIUM": YELLOW}.get(severity, DIM)


def show_events(base: str, *, attack_type: str | None = None, limit: int = 4) -> int:
    events = _request(base, f"/attacks/recent?limit={max(limit * 4, 20)}")
    if attack_type:
        events = [event for event in events if event["attack_type"] == attack_type]
    if not events:
        print(f"  {DIM}(no matching events yet){RESET}")
        return 0
    for event in events[:limit]:
        colour = severity_colour(event["severity"])
        print(
            f"  {colour}{event['severity']:<8}{RESET} {event['attack_type']:<18} "
            f"{event['can_id_hex'] or '-':<10} conf={event['confidence']:.0%}"
        )
        print(f"           {DIM}{event['description']}{RESET}")
    return len(events)


def show_status(base: str) -> dict[str, Any]:
    status = _request(base, "/status")
    traffic, security = status["traffic"], status["security"]
    threat = security["threat_level"]
    colour = {"ATTACK": RED, "SUSPICIOUS": YELLOW}.get(threat, GREEN)
    print(
        f"  bus {traffic['current_rate_msg_per_s']:>7.0f} msg/s   "
        f"threat {colour}{threat:<10}{RESET} "
        f"alerts {security['active_alerts']:<4} "
        f"events {status['detection']['events_emitted']:<5} "
        f"suppressed {status['detection']['events_suppressed']}"
    )
    return status


def pause(step_mode: bool, seconds: float) -> None:
    if step_mode:
        input(f"  {DIM}press Enter to continue{RESET}")
    else:
        time.sleep(seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_URL, help="Base URL of a running instance.")
    parser.add_argument("--step", action="store_true", help="Pause between phases.")
    parser.add_argument("--flood-rate", type=float, default=1500.0, help="Flood frames per second.")
    parser.add_argument("--speed", type=float, default=255.0, help="Spoofed speed in km/h.")
    parser.add_argument("--dwell", type=float, default=8.0, help="Seconds to run each phase.")
    args = parser.parse_args()
    base = args.url

    try:
        # ---- 0. Health -----------------------------------------------------
        heading(0, "Connect")
        health = _request(base, "/health")
        print(f"  {GREEN}{health['service']} {health['version']}{RESET} "
              f"({health['environment']}) - {health['status']}")
        config = _request(base, "/config")["detection"]
        print(f"  {DIM}flood threshold {config['flood_threshold']:.0f} msg/s | "
              f"fake-speed threshold {config['fake_speed_threshold']:.0f} km/h{RESET}")

        if _request(base, "/simulation/status")["running"]:
            _request(base, "/simulation/stop", "POST")

        # ---- 1. Normal traffic ---------------------------------------------
        heading(1, "Normal vehicle traffic")
        started = _request(base, "/simulation/start", "POST", {"mode": "NORMAL"})
        if started.get("monitor_started"):
            print(f"  {DIM}monitor started automatically{RESET}")
        pause(args.step, args.dwell)
        show_status(base)
        print(f"  {GREEN}Expected: no alerts. A clean bus must not trip a detector.{RESET}")

        # ---- 2. Fake speed --------------------------------------------------
        heading(2, f"Fake Speed attack ({args.speed:.0f} km/h injected on 0x300)")
        _request(base, "/simulation/mode", "POST",
                 {"mode": "FAKE_SPEED", "fake_speed_value": args.speed, "fake_speed_rate": 100.0})
        wait_for(
            base,
            lambda: any(e["attack_type"] == "FAKE_SPEED"
                        for e in _request(base, "/attacks/recent?limit=20")),
            timeout=args.dwell + 10,
            description="a FAKE_SPEED detection",
        )
        show_events(base, attack_type="FAKE_SPEED", limit=1)
        show_events(base, attack_type="FREQUENCY_ANOMALY", limit=1)
        show_status(base)
        print(f"  {DIM}The spoof is injected alongside the genuine ECU, so 0x300's rate")
        print(f"  rises too - which is why the frequency detector also fires.{RESET}")
        pause(args.step, 2)

        # ---- 3. Flood -------------------------------------------------------
        heading(3, f"CAN Flood attack ({args.flood_rate:.0f} frames/s on 0x000)")
        _request(base, "/simulation/mode", "POST",
                 {"mode": "CAN_FLOOD", "flood_rate": args.flood_rate})
        wait_for(
            base,
            lambda: any(e["attack_type"] == "CAN_FLOOD"
                        for e in _request(base, "/attacks/recent?limit=30")),
            timeout=args.dwell + 10,
            description="a CAN_FLOOD detection",
        )
        time.sleep(min(args.dwell, 6))
        show_events(base, attack_type="CAN_FLOOD", limit=1)
        show_events(base, attack_type="ID_ANOMALY", limit=1)
        status = show_status(base)
        interface = status["monitor"]["interface"]["statistics"]
        print(f"  {DIM}frames dropped by the interface: {interface['dropped']} | "
              f"by the writer: {status['storage']['writer']['messages_dropped']}{RESET}")
        pause(args.step, 2)

        # ---- 4. Identifier anomaly ------------------------------------------
        heading(4, "Identifier anomaly (injecting 0x123, outside the allowlist)")
        for _ in range(6):
            _request(base, "/simulation/inject", "POST", {"can_id": 0x123, "data": "DEADBEEF"})
            time.sleep(0.05)
        wait_for(
            base,
            lambda: any(e["attack_type"] == "ID_ANOMALY" and e["can_id"] == 0x123
                        for e in _request(base, "/attacks/recent?limit=30")),
            timeout=10,
            description="an ID_ANOMALY detection for 0x123",
        )
        events = _request(base, "/attacks?attack_type=ID_ANOMALY&can_id=0x123&limit=1")
        print(f"  events recorded for 0x123: {events['total']}")
        pause(args.step, 2)

        # ---- 5. Recovery ----------------------------------------------------
        heading(5, "Recovery")
        _request(base, "/simulation/mode", "POST", {"mode": "NORMAL"})
        time.sleep(args.dwell)
        status = show_status(base)
        flood = next(d for d in status["detection"]["detectors"] if d["name"] == "can_flood")
        rate = flood["state"]["current_rate_msg_per_s"]
        threshold = config["flood_threshold"]
        verdict = GREEN + "NORMAL" + RESET if rate <= threshold else RED + "STILL ELEVATED" + RESET
        print(f"  flood detector sees {rate:.0f} msg/s against a {threshold:.0f} msg/s "
              f"threshold -> {verdict}")
        print(f"  {DIM}The dashboard's threat badge clears once the active-alert window")
        print(f"  ({status['security']['active_alert_window_seconds']:.0f}s) has passed.{RESET}")

        # ---- 6. Summary -----------------------------------------------------
        heading(6, "Summary")
        stats = _request(base, "/attacks/statistics")
        print(f"  total events stored : {stats['total_events']}")
        print(f"  by attack type      : {stats['by_attack_type']}")
        print(f"  by severity         : {stats['by_severity']}")

        _request(base, "/simulation/stop", "POST")
        print(f"\n{GREEN}{BOLD}Demonstration complete.{RESET} Simulation stopped.\n")
        return 0

    except DemoError as exc:
        print(f"\n{RED}Demonstration failed:{RESET} {exc}\n", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted.{RESET}", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
