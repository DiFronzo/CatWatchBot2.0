#!/bin/bash
# Usage:
# toolforge-jobs run bootstrap-venv --command "./bootstrap-venv.sh" --image python3.9 --wait
set -euo pipefail

rm -rf ENV
python3 -m venv ENV

. ENV/bin/activate

# upgrade pip inside the venv and add support for the wheel package format
pip install -U pip wheel
pip install -r requirements.txt