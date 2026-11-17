#!/usr/bin/env bash
# 统一入口，自动使用本目录 venv
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONWARNINGS=ignore
exec .venv/bin/python "${1:-cx_play.py}" "${@:2}"
