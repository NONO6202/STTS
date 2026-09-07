#!/bin/bash
# Project-local workaround for mismatched private/public CLT manifest interfaces.
# The installed toolchain is never modified.
set -euo pipefail
STTS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STTS_MANIFEST_API="$(dirname "$(xcrun --find swift)")/../lib/swift/pm/ManifestAPI"
mkdir -p "$STTS_ROOT/.build/swiftpm-libs"
cp -R "$STTS_MANIFEST_API" "$STTS_ROOT/.build/swiftpm-libs/"
python3 - "$STTS_ROOT/.build/swiftpm-libs" <<'PY'
from pathlib import Path
import sys
for path in Path(sys.argv[1]).rglob('*.private.swiftinterface'):
    path.unlink()
PY
export SWIFTPM_CUSTOM_LIBS_DIR="$STTS_ROOT/.build/swiftpm-libs"
export SWIFTPM_MODULECACHE_OVERRIDE="$STTS_ROOT/.build/fixed-module-cache"
