#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export MANDATEGUARD_OFFLINE="${MANDATEGUARD_OFFLINE:-1}"
python3 -m bailiff.runner --final --n 100
python3 -m bailiff.report
python3 scripts/make_frontier.py
python3 scripts/make_sensitivity_chart.py
python3 scripts/make_architecture.py
python3 scripts/make_findings.py
