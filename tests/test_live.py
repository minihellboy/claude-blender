# SPDX-License-Identifier: MIT
"""
Live tests against a real Blender instance.

Run with:  BLENDER_LIVE=1 uv run pytest -m live
Requires Blender with the Claude addon serving on BLENDER_PORT (default 9876).
"""

import json
import os

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("BLENDER_LIVE") != "1",
        reason="live Blender tests need BLENDER_LIVE=1",
    ),
]


@pytest.fixture(autouse=True)
async def _fresh_connection():
    """Drop the singleton client's socket after each test.

    pytest-asyncio gives every test a fresh event loop; a connection opened
    in a previous test's loop would fail with 'Event loop is closed'.
    """
    yield
    from claude_blender_mcp.server import get_blender

    await get_blender().disconnect()


def _images(result):
    return [c for c in result.content if "Image" in type(c).__name__]


async def _cleanup(client, names):
    for name in names:
        try:
            await client.call_tool("blender_delete_object", {"name": name})
        except Exception:
            pass


async def test_live_core():
    from mcp.client import Client
    from claude_blender_mcp.server import mcp

    async with Client(mcp) as client:
        try:
            r = await client.call_tool("blender_ping", {})
            assert "connected" in r.content[0].text, r.content[0].text

            r = await client.call_tool("blender_add_object", {
                "object_type": "sphere", "name": "LiveTest_Sphere", "location": [2, 0, 1],
            })
            assert not r.is_error, r.content

            evil = 'Evil"Mat\'{} injection'
            r = await client.call_tool("blender_create_material", {
                "name": evil, "color": [0.9, 0.2, 0.1, 1.0], "metallic": 0.8,
                "apply_to": "LiveTest_Sphere",
            })
            assert not r.is_error, r.content

            r = await client.call_tool("blender_get_object", {"name": "LiveTest_Sphere"})
            assert r.structured_content.get("materials"), r.structured_content

            res = await client.read_resource("blender://object/LiveTest_Sphere")
            body = json.loads(res.contents[0].text)
            assert body["name"] == "LiveTest_Sphere"

            r = await client.call_tool("blender_render", {
                "engine": "CYCLES", "samples": 8,
                "resolution_x": 320, "resolution_y": 180,
            })
            assert not r.is_error and _images(r), r.content
        finally:
            await _cleanup(client, ["LiveTest_Sphere"])


async def test_live_v030_features(tmp_path):
    from mcp.client import Client
    from claude_blender_mcp.server import mcp

    async with Client(mcp) as client:
        created = ["LiveTest_Cube"]
        try:
            # Checkpoint / undo around a destructive edit
            r = await client.call_tool("blender_checkpoint", {"label": "live-test"})
            assert not r.is_error, r.content

            r = await client.call_tool("blender_add_object", {
                "object_type": "cube", "name": "LiveTest_Cube", "location": [0, 3, 1],
            })
            assert not r.is_error, r.content

            # Modifier raises the evaluated polygon count
            r = await client.call_tool("blender_get_object", {"name": "LiveTest_Cube"})
            base_polys = r.structured_content["polygon_count"]
            r = await client.call_tool("blender_modifier", {
                "action": "add", "object_name": "LiveTest_Cube",
                "modifier_type": "SUBSURF", "params": {"levels": 2},
            })
            assert not r.is_error, r.content
            r = await client.call_tool("blender_modifier", {
                "action": "apply", "object_name": "LiveTest_Cube",
                "modifier_name": "Subsurf",
            })
            assert not r.is_error, r.content
            r = await client.call_tool("blender_get_object", {"name": "LiveTest_Cube"})
            assert r.structured_content["polygon_count"] > base_polys

            # Duplication as a linear array
            r = await client.call_tool("blender_duplicate", {
                "name": "LiveTest_Cube", "count": 3, "offset": [2.5, 0, 0],
            })
            assert not r.is_error, r.content
            dups = r.structured_content["created"]
            assert len(dups) == 3
            created += dups

            # Collections
            r = await client.call_tool("blender_organize", {
                "action": "move_to_collection", "objects": dups,
                "collection": "LiveTest_Props",
            })
            assert not r.is_error, r.content

            # Export -> reimport roundtrip through STL
            stl = str(tmp_path / "livetest.stl")
            r = await client.call_tool("blender_export", {
                "filepath": stl, "objects": ["LiveTest_Cube"],
            })
            assert not r.is_error, r.content
            assert os.path.getsize(stl) > 0

            r = await client.call_tool("blender_import_model", {"filepath": stl})
            assert not r.is_error, r.content
            imported = r.structured_content["objects_added"]
            assert imported
            created += imported

            # Camera framing puts the subject in front of the lens
            r = await client.call_tool("blender_frame_camera", {
                "targets": ["LiveTest_Cube"], "azimuth_deg": 35, "elevation_deg": 25,
            })
            assert not r.is_error, r.content

            # Short animation with preview stills
            r = await client.call_tool("blender_set_keyframe", {
                "object_name": "LiveTest_Cube", "frame": 1, "location": [0, 3, 1],
            })
            assert not r.is_error, r.content
            r = await client.call_tool("blender_set_keyframe", {
                "object_name": "LiveTest_Cube", "frame": 12, "location": [0, 3, 3],
            })
            assert not r.is_error, r.content
            r = await client.call_tool("blender_render_animation", {
                "frame_start": 1, "frame_end": 12, "engine": "BLENDER_EEVEE_NEXT",
                "samples": 8, "resolution_x": 320, "resolution_y": 180,
                "preview_frames": 2, "timeout_seconds": 600,
            })
            assert not r.is_error, r.content
            assert "12 frames" in r.content[0].text
            mp4 = r.content[0].text.split("Animation rendered to: ")[1].split("\n")[0]
            assert os.path.getsize(mp4) > 0
        finally:
            await _cleanup(client, created)


async def test_live_review_and_jobs(tmp_path):
    """v0.5.0: change reports, snapshots, multi-view sheets, render jobs."""
    from mcp.client import Client
    from claude_blender_mcp.server import mcp

    async with Client(mcp) as client:
        try:
            snap = (await client.call_tool("blender_snapshot", {})).structured_content

            r = await client.call_tool("blender_execute", {"code": (
                "import bpy, math\n"
                "bpy.ops.mesh.primitive_monkey_add(location=(0, 0, 1))\n"
                "o = bpy.context.active_object\n"
                "o.name = 'LiveTest_Monkey'\n"
                "o.rotation_euler = (0, 0, 0)\n"
                "o.keyframe_insert('rotation_euler', frame=1)\n"
                "o.rotation_euler = (0, 0, math.pi)\n"
                "o.keyframe_insert('rotation_euler', frame=8)\n"
            )})
            assert not r.is_error, r.content
            text = r.content[0].text
            assert "LiveTest_Monkey (MESH)" in text, text

            d = (await client.call_tool(
                "blender_diff", {"snapshot_id": snap["snapshot_id"]}
            )).structured_content
            assert "LiveTest_Monkey" in d["added"], d

            r = await client.call_tool("blender_render_views", {
                "targets": ["LiveTest_Monkey"], "views": ["front", "right", "top"],
                "resolution_x": 160, "resolution_y": 120, "samples": 4,
            })
            assert not r.is_error and _images(r), r.content
            # The temporary camera must not linger or replace the scene camera
            d = (await client.call_tool(
                "blender_diff", {"snapshot_id": snap["snapshot_id"]}
            )).structured_content
            assert not any("_claude" in n for n in d["added"]), d
            assert "camera" not in d["scene"], d

            out = str(tmp_path / "job.mp4")
            st = (await client.call_tool("blender_render_job_start", {
                "frame_start": 1, "frame_end": 8, "frame_step": 2,
                "resolution_x": 160, "resolution_y": 120, "samples": 4,
                "filepath": out,
            })).structured_content
            r = await client.call_tool("blender_render_job_status", {
                "job_id": st["job_id"], "wait_seconds": 300,
            })
            status = json.loads(r.content[0].text)
            assert status["status"] == "completed", status
            assert os.path.getsize(out) > 0
            assert _images(r), "expected a contact sheet of the finished frames"

            # Rendering frames must leave the playhead where it was
            d = (await client.call_tool(
                "blender_diff", {"snapshot_id": snap["snapshot_id"]}
            )).structured_content
            assert "frame_current" not in d["scene"], d
        finally:
            await _cleanup(client, ["LiveTest_Monkey"])
