#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_EXE="${MXZY_PYTHON:-python}"
ENV_FILE="${MXZY_WORKER_ENV:-${PROJECT_ROOT}/.env.campus-worker.local}"

cd "${PROJECT_ROOT}"
exec "${PYTHON_EXE}" run_remote_worker.py --env-file "${ENV_FILE}" "$@"
