#!/usr/bin/env python3
"""Standalone CAN traffic generator.

The backend's built-in simulator drives its own in-process virtual bus, which
is all you need for a laptop demonstration.  This CLI covers the other case:
putting the *same* generated traffic onto a real bus - a Linux ``vcan0``
interface, or a physical adapter - so the backend can be run in
``CAN_INTERFACE=python-can`` mode against genuine bus traffic.

Examples
--------
Print frames without touching any hardware::

    python simulator/can_sentinel_sim.py --mode NORMAL --dry-run --duration 5

Drive a Linux virtual CAN interface::

    sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0
    python simulator/can_sentinel_sim.py --backend python-can --channel vcan0

Run a flood against a real adapter::

    python simulator/can_sentinel_sim.py --backend python-can --channel can0 \
        --mode CAN_FLOOD --flood-rate 1500 --duration 20
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from pathlib import Path

# Allow running straight from a checkout without installing the package.
BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.can.interface import BaseCanInterface  # noqa: E402
from app.can.message import CanMessage  # noqa: E402
from app.can.python_can import PythonCanInterface  # noqa: E402
from app.can.virtual import VirtualCanInterface  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.simulation.modes import CustomFrame, SimulationMode, SimulationProfile  # noqa: E402
from app.simulation.simulator import CanTrafficSimulator  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="can-sentinel-sim",
        description="Generate realistic vehicle CAN traffic, and attacks against it.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--backend",
        choices=["virtual", "python-can"],
        default="virtual",
        help="'virtual' keeps traffic in-process (use with --dry-run); "
        "'python-can' transmits onto a real or virtual CAN interface.",
    )
    parser.add_argument("--channel", default="vcan0", help="CAN channel name.")
    parser.add_argument("--bustype", default="socketcan", help="python-can interface type.")
    parser.add_argument("--bitrate", type=int, default=500_000, help="Bus bitrate.")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in SimulationMode],
        default=SimulationMode.NORMAL.value,
        help="Traffic profile to generate.",
    )
    parser.add_argument("--flood-rate", type=float, default=1200.0, help="Flood frames per second.")
    parser.add_argument(
        "--flood-can-id",
        default="0x000",
        help="Identifier used by the flood (highest priority by default).",
    )
    parser.add_argument("--fake-speed", type=float, default=255.0, help="Spoofed speed in km/h.")
    parser.add_argument(
        "--fake-speed-rate", type=float, default=100.0, help="Spoofed speed frames per second."
    )
    parser.add_argument(
        "--custom",
        action="append",
        metavar="CAN_ID:HEX:INTERVAL_MS",
        help="Custom frame for CUSTOM mode, e.g. 0x123:DEADBEEF:100. Repeatable.",
    )
    parser.add_argument(
        "--duration", type=float, default=0.0, help="Seconds to run; 0 means until interrupted."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated frames instead of requiring a bus to consume them.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress per-frame output.")
    parser.add_argument("--seed", type=int, default=None, help="Seed for reproducible traffic.")
    return parser


def parse_can_id(raw: str) -> int:
    text = raw.strip().lower()
    return int(text, 16) if text.startswith("0x") else int(text, 10)


def parse_custom(entries: list[str] | None) -> list[CustomFrame]:
    frames: list[CustomFrame] = []
    for entry in entries or []:
        parts = entry.split(":")
        if len(parts) != 3:
            raise SystemExit(f"invalid --custom value {entry!r}; expected CAN_ID:HEX:INTERVAL_MS")
        can_id, payload, interval = parts
        frames.append(
            CustomFrame(
                can_id=parse_can_id(can_id), data=payload, interval_ms=int(interval)
            )
        )
    return frames


def build_interface(args: argparse.Namespace) -> BaseCanInterface:
    if args.backend == "python-can":
        return PythonCanInterface(
            channel=args.channel, bitrate=args.bitrate, bustype=args.bustype
        )
    return VirtualCanInterface(channel=args.channel, bitrate=args.bitrate)


async def drain(interface: BaseCanInterface, stop: asyncio.Event, quiet: bool) -> int:
    """Consume the virtual bus so it does not simply fill up, printing frames."""
    seen = 0
    while not stop.is_set():
        message: CanMessage | None = await interface.receive(timeout=0.2)
        if message is None:
            continue
        seen += 1
        if not quiet:
            print(message, flush=True)
    return seen


async def report(simulator: CanTrafficSimulator, stop: asyncio.Event) -> None:
    while not stop.is_set():
        with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=2.0)
        if stop.is_set():
            break
        status = simulator.status()
        print(
            f"[{status['mode']}] {status['generated_rate_msg_per_s']:.0f} msg/s | "
            f"generated={status['messages_generated']} "
            f"(attack={status['attack_messages']}) | "
            f"speed={status['vehicle']['speed_kmh']} km/h "
            f"rpm={status['vehicle']['engine_rpm']}",
            file=sys.stderr,
            flush=True,
        )


async def main_async(args: argparse.Namespace) -> int:
    configure_logging(level="INFO", to_file=False, force=True)

    profile = SimulationProfile(
        mode=SimulationMode(args.mode),
        flood_rate=args.flood_rate,
        flood_can_id=parse_can_id(args.flood_can_id),
        fake_speed_value=args.fake_speed,
        fake_speed_rate=args.fake_speed_rate,
        custom_frames=parse_custom(args.custom),
    )

    interface = build_interface(args)
    await interface.open()
    simulator = CanTrafficSimulator(interface, profile=profile, seed=args.seed)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, AttributeError):
            loop.add_signal_handler(sig, stop.set)

    tasks: list[asyncio.Task[object]] = []
    try:
        await simulator.start()
        print(
            f"Generating {profile.mode.value} traffic on {args.backend}:{args.channel}"
            f"{' (dry run)' if args.dry_run else ''}. Ctrl-C to stop.",
            file=sys.stderr,
            flush=True,
        )
        if args.backend == "virtual":
            # Nothing else is reading the in-process bus, so drain it here.
            tasks.append(asyncio.create_task(drain(interface, stop, args.quiet or not args.dry_run)))
        tasks.append(asyncio.create_task(report(simulator, stop)))

        if args.duration > 0:
            with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=args.duration)
            stop.set()
        else:
            await stop.wait()
    except KeyboardInterrupt:  # pragma: no cover - interactive
        stop.set()
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await simulator.stop()
        await interface.close()

    status = simulator.status()
    print(
        f"Generated {status['messages_generated']} frames "
        f"({status['attack_messages']} attack, {status['errors']} errors).",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
