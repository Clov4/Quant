#!/usr/bin/env bash
# One-shot setup for the csequant CSE trading-research system.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> csequant setup"
PY="${PYTHON:-python3}"

# 1) (optional) virtual environment
if [ "${NO_VENV:-0}" != "1" ]; then
  echo "==> creating virtualenv .venv"
  "$PY" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  PY=python
fi

# 2) dependencies (editable install also provides the `csequant` CLI)
echo "==> installing dependencies"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -e . || "$PY" -m pip install -r requirements.txt

# 3) build a real local data cache (≈3 years EOD for the liquid demo universe)
echo "==> building data cache (real CSE data; needs network)"
if "$PY" -m csequant build-cache; then
  echo "    cache built."
else
  echo "    !! cache build failed (offline?). If a demo cache is bundled, the GUI still works."
fi

# 4) tests
echo "==> running tests"
"$PY" -m pytest -q || echo "    (some tests failed — see output above)"

# 5) backtest report
"$PY" -m csequant report || true

cat <<'EOF'

==> Done.

Launch the dashboard:
    streamlit run csequant/gui/app.py      (or:  python -m csequant gui)

Useful CLI:
    python -m csequant backtest
    python -m csequant signals --ticker IAM
    python -m csequant recommend --capital 100000 --risk Balanced

Reminder: research / decision-support only — NOT licensed investment advice.
EOF
