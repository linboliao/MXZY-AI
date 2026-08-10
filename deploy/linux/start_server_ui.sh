#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_EXE="${MXZY_PYTHON:-python}"
ENV_FILE="${MXZY_SERVER_UI_ENV:-${PROJECT_ROOT}/.env.campus-server-ui.local}"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "[FAIL] deployment environment file not found: ${ENV_FILE}" >&2
    exit 2
fi

if [[ "${PYTHON_EXE}" == */* ]]; then
    if [[ ! -x "${PYTHON_EXE}" ]]; then
        echo "[FAIL] Python interpreter is not executable: ${PYTHON_EXE}" >&2
        exit 2
    fi
elif ! command -v "${PYTHON_EXE}" >/dev/null 2>&1; then
    echo "[FAIL] Python interpreter was not found on PATH: ${PYTHON_EXE}" >&2
    exit 2
fi

cd "${PROJECT_ROOT}"
exec "${PYTHON_EXE}" run_webviewer.py --env-file "${ENV_FILE}" "$@"
