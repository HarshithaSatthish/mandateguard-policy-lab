#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export MANDATEGUARD_OFFLINE="${MANDATEGUARD_OFFLINE:-1}"

for script in scripts/test.sh scripts/demo.sh scripts/evaluate.sh scripts/release_check.sh scripts/make_frontier.py scripts/make_sensitivity_chart.py scripts/make_findings.py; do
  test -x "$script"
done

test -f RECOVERYTRUTH.md
test -f SUBMISSION_READINESS.md
test -f SHA256SUMS.txt

if grep -RInE '^(<<<<<<<|=======|>>>>>>>)( |$)' \
  --exclude-dir=.git --exclude-dir=outputs/generated \
  --exclude-dir=.venv --exclude-dir=venv \
  --exclude-dir=__pycache__ --exclude-dir=.pytest_cache --exclude-dir=.hypothesis \
  --exclude-dir=build --exclude-dir=dist --exclude-dir='*.egg-info' \
  --exclude-dir=node_modules .; then
  echo "release check failed: merge conflict markers found" >&2
  exit 1
fi
if grep -RInE '\{\{[^}]+\}\}' README.md RECOVERYTRUTH.md SUBMISSION_READINESS.md docs outputs FINDINGS.md; then
  echo "release check failed: unresolved placeholders found" >&2
  exit 1
fi

# Credentials and raw operator receipts are local evidence. Sanitized,
# explicitly named docs/testmode_evidence/testmode_*.json artifacts are allowed
# because the claims registry validates their shape without containing keys.
_secret_file="$(find . -type f \( \( -name '.env*' ! -name '.env.example' \) -o -iname '*recoverytruth*receipt*.json' -o -iname '*recoverytruth*proof*.json' -o -iname '*.recoverytruth-receipt.json' -o -iname '*.recoverytruth-proof.json' \) -not -path './.git/*' -print -quit)"
if [[ -n "$_secret_file" ]]; then
  echo "release check failed: local credential/provider-evidence file would be shipped: $_secret_file" >&2
  exit 1
fi

# The manifest is a shipped-content contract, not a historical decoration.
# Re-derive the exact candidate and require byte-for-byte agreement.
_manifest_candidate="$(mktemp)"
python3 scripts/make_checksum_manifest.py > "$_manifest_candidate"
if ! cmp -s SHA256SUMS.txt "$_manifest_candidate"; then
  echo "release check failed: SHA256SUMS.txt is stale; regenerate from scripts/make_checksum_manifest.py" >&2
  rm -f "$_manifest_candidate"
  exit 1
fi
rm -f "$_manifest_candidate"
sha256sum -c SHA256SUMS.txt >/dev/null

python3 -m compileall -q bailiff tests scripts
python3 -m pytest -q

# RecoveryTruth, security regression and the hardening gate deliberately sit
# outside the frozen benchmark suite count. The historical offline proof
# therefore stays stable while protected-surface, provider/concurrency and
# claim invariants are still mandatory in every local release check.
python3 scripts/recoverytruth_check.py
python3 scripts/security_regression_check.py

python3 -m bailiff.demo
rm -rf outputs/demo
python3 -m bailiff.runner --seeds 5 --n 12 --output-dir outputs/demo >/dev/null
if [[ ! -f outputs/evidence_manifest.json || ! -f outputs/breakeven.json || ! -f outputs/frontier.png || ! -f outputs/sensitivity.png || ! -f outputs/sensitivity.json || ! -f outputs/generated/evidence_ledger_full.json || ! -f FINDINGS.md ]]; then
  _preserved_charts="$(mktemp -d)"
  for _chart in outputs/architecture.png outputs/frontier.png outputs/sensitivity.png; do
    [[ -f "$_chart" ]] && cp -p "$_chart" "$_preserved_charts/$(basename "$_chart")"
  done

  ./scripts/evaluate.sh >/dev/null

  for _chart in outputs/architecture.png outputs/frontier.png outputs/sensitivity.png; do
    _saved="$_preserved_charts/$(basename "$_chart")"
    [[ -f "$_saved" ]] && cp -p "$_saved" "$_chart"
  done
  rm -rf "$_preserved_charts"
fi
python3 scripts/check_release.py
python3 scripts/hardening_check.py
