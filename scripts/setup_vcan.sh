#!/usr/bin/env bash
# Create a Linux virtual CAN interface so CAN-Sentinel can be run in
# `python-can` mode without physical hardware.
#
#   sudo scripts/setup_vcan.sh          # create vcan0
#   sudo scripts/setup_vcan.sh vcan1    # create a different interface
#   sudo scripts/setup_vcan.sh vcan0 down   # tear it down
#
# Linux only: vcan is a kernel module and has no Windows or macOS equivalent.
# On those platforms use the default CAN_INTERFACE=virtual, which needs no
# kernel support at all.
set -euo pipefail

IFACE="${1:-vcan0}"
ACTION="${2:-up}"

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "vcan is a Linux kernel feature; on this platform use CAN_INTERFACE=virtual." >&2
    exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
    echo "This script configures a network interface and must be run with sudo." >&2
    exit 1
fi

if [[ "${ACTION}" == "down" ]]; then
    ip link set "${IFACE}" down 2>/dev/null || true
    ip link delete "${IFACE}" 2>/dev/null || true
    echo "Removed ${IFACE}."
    exit 0
fi

modprobe vcan

if ip link show "${IFACE}" >/dev/null 2>&1; then
    echo "${IFACE} already exists."
else
    ip link add dev "${IFACE}" type vcan
    echo "Created ${IFACE}."
fi

ip link set up "${IFACE}"
ip -details -brief link show "${IFACE}"

cat <<HINT

${IFACE} is up. To use it:

  1. Point CAN-Sentinel at it:
         CAN_INTERFACE=python-can CAN_BUSTYPE=socketcan CAN_CHANNEL=${IFACE} \
           uvicorn app.main:app --app-dir backend

  2. Generate traffic onto it from another terminal:
         python simulator/can_sentinel_sim.py --backend python-can --channel ${IFACE}

  3. Watch it with the standard tools if you have can-utils installed:
         candump ${IFACE}
HINT
