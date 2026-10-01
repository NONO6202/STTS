#!/bin/bash
# Uploads the Windows and macOS depots to Steam as one build.
# SteamCMD asks for the password and Steam Guard code itself; nothing is stored here.
#
#   STEAM_APP_ID=... STEAM_DEPOT_WINDOWS=... STEAM_DEPOT_MAC=... STEAM_USER=... bash Support/steam-upload.sh
#
# Optional: STEAM_BRANCH (an existing beta branch; omitted leaves the build unassigned;
#           "default" must be set live in Steamworks by hand),
#           STEAM_PREVIEW=1 (check file mapping without uploading),
#           STEAM_WINDOWS_CONTENT (default Windows/build/steam), STEAM_MAC_APP (default dist/STTS.app).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${STEAM_APP_ID:?Set STEAM_APP_ID}" "${STEAM_DEPOT_WINDOWS:?Set STEAM_DEPOT_WINDOWS}" "${STEAM_DEPOT_MAC:?Set STEAM_DEPOT_MAC}" "${STEAM_USER:?Set STEAM_USER}"
BRANCH="${STEAM_BRANCH:-}"
WINDOWS="${STEAM_WINDOWS_CONTENT:-$ROOT/Windows/build/steam}"
MAC_APP="${STEAM_MAC_APP:-$ROOT/dist/STTS.app}"
OUT="$ROOT/.build/steam"

command -v steamcmd >/dev/null || { echo "SteamCMD is missing: brew install --cask steamcmd" >&2; exit 1; }
[[ -f "$WINDOWS/STTS.exe" && -f "$WINDOWS/STTSRuntime.exe" && -f "$WINDOWS/Engine/STTSWorker.exe" && -f "$WINDOWS/VB-CABLE/VBCABLE_Setup_x64.exe" ]] \
    || { echo "Windows content is incomplete: run 'Windows/build.ps1 -Steam' and copy Windows/build/steam here." >&2; exit 1; }
[[ -x "$MAC_APP/Contents/MacOS/STTS" ]] || { echo "Missing $MAC_APP: run Support/build-macos.sh first." >&2; exit 1; }
[[ -x "$MAC_APP/Contents/Helpers/STTSRuntime.app/Contents/MacOS/STTS" ]] || { echo "Missing macOS background runtime: rebuild Support/package-macos.py." >&2; exit 1; }
codesign --verify --deep --strict "$MAC_APP"
[[ "$BRANCH" != "default" ]] || { echo "Steam cannot set the default branch live from a build script; upload to a beta branch and promote it in Steamworks." >&2; exit 1; }

read -r VERSION BUILD_NUMBER < <(python3 -c 'import json,sys; product=json.load(open(sys.argv[1])); print(product["version"], product["build"])' "$ROOT/Shared/app.json")
REVISION="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo local)"
rm -rf "$OUT/mac"; mkdir -p "$OUT/mac" "$OUT/output"
# ditto keeps the bundle's symlinks and signatures intact.
ditto "$MAC_APP" "$OUT/mac/STTS.app"

cat > "$OUT/app_build.vdf" <<VDF
"AppBuild"
{
	"AppID" "$STEAM_APP_ID"
	"Desc" "STTS $VERSION build $BUILD_NUMBER ($REVISION)"
	"BuildOutput" "$OUT/output"
	"Preview" "${STEAM_PREVIEW:-0}"
	"SetLive" "$BRANCH"
	"Depots"
	{
		"$STEAM_DEPOT_WINDOWS"
		{
			"ContentRoot" "$WINDOWS"
			"FileMapping" { "LocalPath" "*" "DepotPath" "." "Recursive" "1" }
		}
		"$STEAM_DEPOT_MAC"
		{
			"ContentRoot" "$OUT/mac"
			"FileMapping" { "LocalPath" "*" "DepotPath" "." "Recursive" "1" }
		}
	}
}
VDF

echo "Uploading STTS $VERSION build $BUILD_NUMBER to app $STEAM_APP_ID, branch ${BRANCH:-unassigned (select in Steamworks)}"
steamcmd +login "$STEAM_USER" +run_app_build "$OUT/app_build.vdf" +quit
