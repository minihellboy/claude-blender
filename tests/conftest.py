# SPDX-License-Identifier: MIT
"""
Shared fixtures: a fake Blender JSON-RPC server for protocol-level tests.

The fake compiles every `execute` payload it receives, so any quoting or
injection bug in generated code fails the suite instead of failing only
against a live Blender.
"""

import asyncio
import base64
import json
import os
import socket
import sys
import tempfile
from unittest.mock import MagicMock

import pytest

# Tiny valid 1x1 PNG used for every fake image the server "produces".
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
    "h6FO1AAAAABJRU5ErkJggg=="
)


def _install_stub_modules():
    """Stub the modules generated code imports inside Blender.

    This lets the fake server EXECUTE every payload instead of merely
    compiling it - compile() cannot catch a wrong import path (that is how
    five broken ai_* tools once shipped green).
    """
    for mod in ("bpy", "mathutils",
                "claude_blender",
                "claude_blender.ai_services",
                "claude_blender.ai_services.local_text_to_3d",
                "claude_blender.ai_services.local_image_to_3d",
                "claude_blender.ai_services.comfyui_bridge"):
        sys.modules.setdefault(mod, MagicMock(name=mod))

    ltt = sys.modules["claude_blender.ai_services.local_text_to_3d"]
    ltt.ProceduralGenerator.return_value.generate.return_value = {
        "success": True, "object_name": "Generated_Rock",
    }


_install_stub_modules()


def _jsonable(value):
    """Mirror the executor's serialization: JSON types pass, the rest str()."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return str(value)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeBlender:
    """In-process stand-in for the Blender addon's TCP server."""

    def __init__(self, port: int):
        self.port = port
        self.server: asyncio.AbstractServer | None = None
        self.received_code: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        self.screenshot_path = os.path.join(
            tempfile.gettempdir(), f"fake_blender_shot_{port}.png"
        )
        with open(self.screenshot_path, "wb") as f:
            f.write(PNG_BYTES)

    async def start(self):
        self.server = await asyncio.start_server(self._on_conn, "127.0.0.1", self.port)

    async def stop(self):
        self.server.close()
        await asyncio.wait_for(self.server.wait_closed(), timeout=10)

    async def _on_conn(self, reader, writer):
        while True:
            line = await reader.readline()
            if not line:
                break
            req = json.loads(line)
            result = await self._dispatch(req["method"], req.get("params", {}))
            writer.write(
                (json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}) + "\n").encode()
            )
            await writer.drain()

    async def _dispatch(self, method: str, params: dict):
        self.calls.append((method, params))
        handler = getattr(self, f"_h_{method}", None)
        if handler is None:
            return {"success": False, "error": f"unknown method {method}"}
        result = handler(params)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    # --- basic -------------------------------------------------------------

    def _h_ping(self, params):
        return "pong"

    def _h_version(self, params):
        return {"blender_version": "4.3.2", "addon_version": "0.3.0"}

    async def _h_slow_op(self, params):
        await asyncio.sleep(5)
        return "too-late"

    def _h_execute(self, params):
        code = params["code"]
        self.received_code.append(code)
        try:
            compiled = compile(code, "<generated>", "exec")  # injection check
        except SyntaxError as e:
            return {"success": False, "error": f"SyntaxError: {e}"}
        # Execute like the real executor does - a payload that only compiles
        # can still crash at runtime (wrong imports, bad attribute paths).
        namespace = {"__result__": None}
        try:
            exec(compiled, namespace)
        except Exception as e:
            return {"success": False, "result": None, "output": "",
                    "error": f"{type(e).__name__}: {e}"}
        return {"success": True, "result": _jsonable(namespace.get("__result__")),
                "output": ""}

    # --- scene -------------------------------------------------------------

    def _h_get_scene(self, params):
        return {
            "name": "Scene", "object_count": 2, "active_object": "Cube",
            "objects": [{"name": "Cube", "type": "MESH"}, "Light"],
        }

    def _h_get_object(self, params):
        return {
            "name": params["name"], "type": "MESH",
            "location": [0, 0, 0], "rotation_euler": [0.0, 0.0, 0.7854],
            "scale": [1, 1, 1],
            "visible": True, "dimensions": [2, 2, 2], "materials": ["Mat"],
            "mesh": {"vertex_count": 8, "polygon_count": 6, "has_uv": True},
            "modifiers": [{"name": "Subsurf", "type": "SUBSURF", "show_viewport": True}],
            "collections": ["Collection"],
        }

    def _h_add_object(self, params):
        return {"success": True, "object_name": params.get("name", "Cube")}

    def _h_modify_object(self, params):
        return {"success": True, "object_name": params["name"]}

    def _h_delete_object(self, params):
        if params["name"] == "Ghost":
            return {"success": False, "error": "Object 'Ghost' not found"}
        return {"success": True}

    # --- render ------------------------------------------------------------

    def _h_screenshot(self, params):
        return {"success": True, "filepath": self.screenshot_path}

    def _h_render(self, params):
        path = params.get("filepath") or os.path.join(
            tempfile.gettempdir(), f"fake_blender_render_{self.port}.png"
        )
        with open(path, "wb") as f:
            f.write(PNG_BYTES)
        return {"success": True, "filepath": path}

    def _h_save_file(self, params):
        path = params.get("filepath") or os.path.join(
            tempfile.gettempdir(), f"fake_blender_{self.port}.blend"
        )
        with open(path, "wb") as f:
            f.write(b"BLENDER-fake")
        return {"success": True, "filepath": path,
                "copy": bool(params.get("copy", False)),
                "file_size": os.path.getsize(path)}

    def _h_render_animation(self, params):
        start = int(params.get("frame_start", 1))
        end = int(params.get("frame_end", 24))
        path = params.get("filepath") or os.path.join(
            tempfile.gettempdir(), f"fake_blender_anim_{self.port}.mp4"
        )
        with open(path, "wb") as f:
            f.write(b"\x00" * 128)  # stub video
        return {
            "success": True, "filepath": path, "container": "MP4",
            "frame_start": start, "frame_end": end, "frame_count": end - start + 1,
            "fps": int(params.get("fps", 24)), "engine": params.get("engine", "CYCLES"),
            "resolution": [params.get("resolution_x", 1280), params.get("resolution_y", 720)],
            "render_time_seconds": 1.0,
        }

    # --- v0.3.0 capabilities -----------------------------------------------

    def _h_import_model(self, params):
        if not os.path.isfile(params["filepath"]):
            return {"success": False, "error": f"File not found: {params['filepath']}"}
        return {
            "success": True, "filepath": params["filepath"],
            "format": os.path.splitext(params["filepath"])[1].lstrip("."),
            "objects_added": ["Imported_0"],
        }

    def _h_export_model(self, params):
        with open(params["filepath"], "wb") as f:
            f.write(b"solid fake\nendsolid fake\n")
        return {
            "success": True, "filepath": params["filepath"],
            "format": os.path.splitext(params["filepath"])[1].lstrip("."),
            "object_count": len(params.get("objects", [])) or 3,
            "file_size": os.path.getsize(params["filepath"]),
        }

    def _h_frame_camera(self, params):
        return {
            "success": True, "camera": params.get("camera", "Camera"),
            "location": [4, 4, 3], "rotation_euler": [1.1, 0, 2.4],
            "distance": 7.5, "target_center": [0, 0, 1], "target_radius": 2.0,
            "targets": params.get("targets", ["Cube"]),
        }

    def _h_add_modifier(self, params):
        result = {
            "success": True, "object": params["object_name"],
            "modifier": params["modifier_type"].title(), "type": params["modifier_type"],
            "params_set": list(params.get("params", {})),
        }
        if "bad_param" in params.get("params", {}):
            result["params_set"] = [k for k in result["params_set"] if k != "bad_param"]
            result["params_failed"] = {"bad_param": "no such attribute"}
        return result

    def _h_apply_modifier(self, params):
        return {"success": True, "object": params["object_name"],
                "applied": params["modifier_name"]}

    def _h_remove_modifier(self, params):
        return {"success": True, "object": params["object_name"],
                "removed": params["modifier_name"]}

    def _h_duplicate_object(self, params):
        count = int(params.get("count", 1))
        return {
            "success": True, "source": params["name"],
            "created": [f"{params['name']}.{i:03d}" for i in range(1, count + 1)],
        }

    def _h_set_parent(self, params):
        return {"success": True, "parent": params.get("parent_name"),
                "changed": params["child_names"]}

    def _h_move_to_collection(self, params):
        return {"success": True, "collection": params["collection_name"],
                "moved": params["names"]}

    def _h_checkpoint(self, params):
        return {"success": True, "label": params.get("label", "")}

    def _h_undo(self, params):
        steps = int(params.get("steps", 1))
        return {"success": True, "direction": "undo",
                "steps_requested": steps, "steps_performed": steps}

    def _h_redo(self, params):
        steps = int(params.get("steps", 1))
        return {"success": True, "direction": "redo",
                "steps_requested": steps, "steps_performed": steps}


@pytest.fixture
async def fake_blender(monkeypatch):
    """Fake Blender server; points the MCP server's client at it via env."""
    fake = FakeBlender(_free_port())
    await fake.start()
    monkeypatch.setenv("BLENDER_HOST", "127.0.0.1")
    monkeypatch.setenv("BLENDER_PORT", str(fake.port))

    yield fake

    # The MCP server's singleton client keeps its socket open; close it first,
    # otherwise wait_closed() (which awaits live connections on Python 3.13+)
    # hangs forever.
    from claude_blender_mcp.server import get_blender

    await get_blender().disconnect()
    await fake.stop()


@pytest.fixture
async def client(fake_blender):
    """
    In-memory MCP client bound to the real server instance.

    The Client's anyio cancel scope must be entered and exited in the SAME
    task, but pytest-asyncio runs fixture setup and teardown in different
    tasks - so the whole client lifecycle lives in one background task.
    """
    from mcp.client import Client
    from claude_blender_mcp.server import mcp

    holder: dict = {}
    ready = asyncio.Event()
    stop = asyncio.Event()

    async def runner():
        try:
            async with Client(mcp) as c:
                holder["client"] = c
                ready.set()
                await stop.wait()
        finally:
            ready.set()  # unblock setup even if the client failed to start

    task = asyncio.create_task(runner())
    await asyncio.wait_for(ready.wait(), timeout=15)
    if "client" not in holder:
        await task  # propagate the startup error
        raise RuntimeError("in-memory MCP client failed to start")

    yield holder["client"]

    stop.set()
    await asyncio.wait_for(task, timeout=15)
