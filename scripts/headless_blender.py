# SPDX-License-Identifier: MIT
"""
Run the Claude Blender addon server in a headless (--background) Blender.

Usage:
    blender --background --python scripts/headless_blender.py -- --port 9876

Why this exists: in --background mode Blender has no event loop, so
bpy.app.timers callbacks never fire and the addon's timer-polled TCP server
would sit idle. This script enables the addon, then pumps the server's poll
function manually in a plain loop.

Note: viewport screenshots and the undo stack are unavailable headless;
renders (Cycles/EEVEE), imports/exports, and all object tools work normally.
"""

import argparse
import sys
import time

import bpy


def _parse_args():
    # Blender consumes everything before '--'; our args come after it.
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Headless Claude Blender server")
    parser.add_argument("--port", type=int, default=9876, help="TCP port (default 9876)")
    return parser.parse_args(argv)


def main():
    args = _parse_args()

    bpy.ops.preferences.addon_refresh()
    bpy.ops.preferences.addon_enable(module="claude_blender")

    import claude_blender as addon

    addon._setup_handler()

    from claude_blender.core.server import get_server

    server = get_server()
    server.port = args.port
    if not server.start():
        raise SystemExit(f"[headless] failed to start server on port {args.port}")

    print(f"[headless] Claude Blender server listening on 127.0.0.1:{args.port}", flush=True)
    print("[headless] Ctrl+C to stop", flush=True)

    try:
        while True:
            server._poll()
            time.sleep(0.01)
    except KeyboardInterrupt:
        server.stop()
        print("[headless] stopped", flush=True)


main()
