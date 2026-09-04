#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m compileall -q bailiff tests
python3 -m pytest -q
python3 -m bailiff.checker
