# Claude Blender — Development Guide

MCP server + Blender addon pair. Claude Code (or any MCP client) drives a live
Blender instance over a local TCP socket.

## Architecture (three layers)

```
MCP client (Claude Code)
   │  stdio, MCP protocol 2026-07-28 (SDK v2, stateless)
   ▼
claude_blender/claude_blender_mcp/     ← runs OUTSIDE Blender (uv project)
   server.py          27 tools, 3 resources, 2 prompts (MCPServer)
   blender_client.py  async JSON-RPC client, per-call timeouts
   │  newline-delimited JSON-RPC 2.0 over TCP 127.0.0.1:9876
   ▼
claude_blender/blender_addon/          ← runs INSIDE Blender (addon)
   core/server.py       timer-polled TCP server (60 Hz)
   core/protocol.py     JSON-RPC dispatch → registered methods
   core/executor.py     exec/operators/modifiers/duplicate/undo
   core/scene_utils.py  introspection, render, render_animation
   core/io_utils.py     import/export (format from extension)
   core/camera_utils.py frame_camera (pure-math fit, headless-safe)
   __init__.py          _setup_handler() registers every RPC method
```

## Invariants — do not break these

1. **bpy is main-thread-only.** The addon server polls sockets from a
   `bpy.app.timers` callback. Never introduce `threading.Thread` that touches
   `bpy` — it crashes Blender.
2. **Generated Python must be injection-safe.** MCP-side codegen interpolates
   user values with f-string `{value!r}` (Python `repr`). Never switch to
   `json.dumps` (emits `true`/`null`, which are not Python) or plain f-string
   interpolation. The test suite compiles every generated payload.
3. **Framing is newline-delimited JSON-RPC.** One JSON object per line, both
   directions. Responses must stay single-line (no indent in json.dumps).
4. **Timeout ⇒ disconnect.** `BlenderClient.call()` drops the connection on
   timeout so a late reply can never be consumed by the next request. Keep
   that behavior when touching the client.
5. **Render settings are global scene state.** Any handler that renders must
   re-assert every setting it depends on (`file_format`, resolution,
   `resolution_percentage`) — a previous call may have left anything behind.
6. **New RPC methods** go in `_setup_handler()` (addon `__init__.py`) AND get
   a fake handler in `tests/conftest.py` (`_h_<method>`), or protocol tests
   will fail with "unknown method".

## Commands

```bash
uv sync                                  # install (dev group included)
uv run pytest -m "not live"              # fast suite vs fake Blender server
BLENDER_LIVE=1 uv run pytest -m live     # needs real Blender on port 9876
uv run claude-blender                    # run the MCP server (stdio)

# Headless Blender that serves the addon (no GUI needed; renders work):
blender --background --python scripts/headless_blender.py -- --port 9876
```

## Live-development notes

- The addon is usually symlinked into Blender's addons dir; after editing
  addon code, a running Blender still has the OLD modules in memory. Reload:
  restart Blender (auto-start pref reconnects), or execute a deferred
  disable/enable via `blender_execute` (a `bpy.app.timers` callback so the
  response returns before the socket restarts).
- `--background` Blender has no viewport → `screenshot` fails (expected) and
  the undo stack is disabled → `checkpoint`/`undo` return errors. Cycles and
  EEVEE renders work headless.
- Screenshot/render tools return the image inline (≤4 MB) — look at it and
  judge the result visually before declaring success.
- MCP protocol is the 2026-07-28 stateless revision: requests carry a
  `_meta` envelope (`io.modelcontextprotocol/protocolVersion` +
  `clientCapabilities`); there is no initialize handshake.

## Versioning

Bump together: root `pyproject.toml`, `claude_blender_mcp/__init__.py`
(`__version__`), `server.py` (`MCPServer(version=...)`), addon `__init__.py`
(`bl_info["version"]`).
