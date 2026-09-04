#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export MANDATEGUARD_OFFLINE="${MANDATEGUARD_OFFLINE:-1}"
if [[ "${MANDATEGUARD_REAL_INTERPRETER:-0}" == "1" ]]; then
  python3 -m bailiff.demo --real-interpreter
else
  python3 -m bailiff.demo
fi
rm -rf outputs/demo
python3 -m bailiff.runner --seeds 5 --n 100 --output-dir outputs/demo
