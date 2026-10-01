#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/swift-env.sh"
cd "$STTS_ROOT"
if [[ ! -x .venv/bin/python ]]; then
    uv venv .venv --python /opt/homebrew/bin/python3
fi
uv pip install --python .venv/bin/python -r Support/requirements-build.txt
swift build -c release --product STTS -j 3
.venv/bin/python Support/package-macos.py
