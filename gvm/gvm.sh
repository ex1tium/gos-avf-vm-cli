#!/usr/bin/env bash
# GVM executable wrapper script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

exec python3 -m gvm "$@"
