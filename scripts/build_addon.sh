#!/usr/bin/env bash
# Build claude_blender.zip for Blender's "Install from Disk".
#
# The folder inside the zip MUST be named claude_blender: Blender extracts
# it verbatim into scripts/addons/, and that folder name becomes the addon's
# Python module name - which scripts/headless_blender.py and the generated
# ai_* tool code both rely on.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO_ROOT/claude_blender/blender_addon"
OUT="$REPO_ROOT/claude_blender.zip"
STAGE="$(mktemp -d)"

trap 'rm -rf "$STAGE"' EXIT

cp -R "$SRC" "$STAGE/claude_blender"
find "$STAGE" -name '__pycache__' -type d -exec rm -rf {} +
rm -f "$OUT"
(cd "$STAGE" && zip -qr "$OUT" claude_blender)

echo "Built: $OUT"
echo "Install in Blender: Edit > Preferences > Add-ons > v (dropdown) > Install from Disk..."
