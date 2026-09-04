#!/usr/bin/env bash
# Run every quality gate: backend lint and tests, frontend typecheck, lint,
# tests and production build.
#
#   scripts/verify.sh
#
# Exits non-zero on the first failure, so it is usable as a pre-push hook or a
# CI entry point.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

# Prefer the project virtualenv if it exists, otherwise whatever python is on PATH.
if [[ -x "backend/.venv/bin/python" ]]; then
    PY="backend/.venv/bin/python"
elif [[ -x "backend/.venv/Scripts/python.exe" ]]; then
    PY="backend/.venv/Scripts/python.exe"
else
    PY="python"
fi

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }

step "Backend lint (ruff)"
(cd backend && "../${PY}" -m ruff check .)

step "Backend tests (pytest)"
(cd backend && "../${PY}" -m pytest -q)

step "Frontend typecheck"
(cd frontend && npx tsc -b --noEmit)

step "Frontend lint (eslint)"
(cd frontend && npx eslint .)

step "Frontend tests (vitest)"
(cd frontend && npx vitest run)

step "Frontend production build"
(cd frontend && npm run build)

printf '\n\033[1;32mAll quality gates passed.\033[0m\n'
