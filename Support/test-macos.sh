#!/bin/bash
set -euo pipefail
source "$(dirname "$0")/swift-env.sh"
cd "$STTS_ROOT"
STTS_DEVELOPER="$(xcode-select -p)/Library/Developer"
export DYLD_LIBRARY_PATH="$STTS_DEVELOPER/usr/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
swift test -c release --disable-xctest --filter 'SegmentationTests|DefaultAudioDevicesTests' -j 3 \
    -Xswiftc -F -Xswiftc "$STTS_DEVELOPER/Frameworks" \
    -Xlinker "-F$STTS_DEVELOPER/Frameworks" \
    -Xlinker -rpath -Xlinker "$STTS_DEVELOPER/Frameworks" \
    -Xlinker -rpath -Xlinker "$STTS_DEVELOPER/usr/lib"
.venv/bin/python -m unittest discover -s Tests -p 'test_mlx_protocol.py'
