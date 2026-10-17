# SPDX-License-Identifier: MIT
"""In-memory MCP client tests against the fake Blender server."""

import json
import os
import tempfile

import pytest

from claude_blender_mcp import blender_client
from claude_blender_mcp import server as srv


EXPECTED_TOOL_COUNT = 34


def _image_contents(result):
    return [c for c in result.content if "Image" in type(c).__name__]


# =============================================================================
# Listing, annotations, caching
# =============================================================================


async def test_tool_listing(client):
    result = await client.list_tools()
    tools = {t.name: t for t in result.tools}
    assert len(tools) == EXPECTED_TOOL_COUNT, sorted(tools)

    assert tools["blender_ping"].annotations.read_only_hint is True
    assert tools["blender_delete_object"].annotations.destructive_hint is True
    assert tools["blender_undo"].annotations.destructive_hint is True
    assert tools["blender_checkpoint"].annotations.destructive_hint is False
    assert tools["blender_frame_camera"].annotations.idempotent_hint is True
    assert tools["blender_get_scene"].output_schema is not None
    assert tools["blender_import_model"].output_schema is not None

    # tools/list is declared cacheable for an hour
    assert result.ttl_ms == 3_600_000


async def test_prompt_listing(client):
    prompts = await client.list_prompts()
    assert {p.name for p in prompts.prompts} == {"studio_lighting", "turntable_animation"}
    p = await client.get_prompt("turntable_animation", {"object_name": "Cube", "seconds": "2"})
    assert "1-48" in p.messages[0].content.text


# =============================================================================
# Scene inspection
# =============================================================================


async def test_ping(client):
    r = await client.call_tool("blender_ping", {})
    assert not r.is_error
    assert "connected" in r.content[0].text


async def test_get_scene_structured(client):
    r = await client.call_tool("blender_get_scene", {"detail_level": "basic"})
    sc = r.structured_content
    assert sc["object_count"] == 2
    # Plain-string entries from the addon are normalized to objects
    assert sc["objects"][1] == {"name": "Light", "type": "UNKNOWN"}


async def test_get_object_structured(client):
    r = await client.call_tool("blender_get_object", {"name": "Cube"})
    sc = r.structured_content
    assert sc["dimensions"] == [2.0, 2.0, 2.0]
    # Regression: the addon sends 'rotation_euler'; a plain 'rotation' read
    # silently reported [0,0,0] for every rotated object.
    assert sc["rotation"] == [0.0, 0.0, 0.7854]
    assert sc["modifiers"] == [{"name": "Subsurf", "type": "SUBSURF"}]
    assert sc["vertex_count"] == 8
    assert sc["polygon_count"] == 6
    assert sc["collections"] == ["Collection"]


# =============================================================================
# Injection resistance: hostile inputs must still produce valid Python
# =============================================================================


async def test_material_name_injection(client, fake_blender):
    evil = 'Red"Mat\'{}\n# comment\'\'\' broken'
    r = await client.call_tool("blender_create_material", {
        "name": evil, "color": [1, 0, 0], "apply_to": 'Cu"be\'',
    })
    assert not r.is_error, r.content
    # The name reaches Blender as its repr() form - quoting is the defense.
    assert repr(evil) in fake_blender.received_code[-1]


async def test_keyframe_name_injection(client):
    r = await client.call_tool("blender_set_keyframe", {
        "object_name": 'O\'Brien "the" cube', "frame": 10,
        "location": [1, 2, 3], "rotation": [0, 0, 1.57],
    })
    assert not r.is_error, r.content


async def test_procedural_prompt_injection(client):
    r = await client.call_tool("ai_local_text_to_3d", {
        "prompt": 'a rock"""; import os; os.system("boom") # {p}',
        "provider": "procedural",
    })
    assert not r.is_error, r.content


# =============================================================================
# Images
# =============================================================================


async def test_screenshot_returns_image(client):
    r = await client.call_tool("blender_screenshot", {})
    images = _image_contents(r)
    assert images, [type(c).__name__ for c in r.content]
    assert images[0].mime_type == "image/png"


async def test_render_animation_returns_previews(client, fake_blender):
    r = await client.call_tool("blender_render_animation", {
        "frame_start": 1, "frame_end": 48, "preview_frames": 3, "samples": 8,
    })
    assert not r.is_error, r.content
    assert "48 frames" in r.content[0].text
    assert len(_image_contents(r)) == 3
    # Preview stills must have positioned the playhead first
    frame_sets = [c for c in fake_blender.received_code if "frame_set" in c]
    assert len(frame_sets) == 3


# =============================================================================
# v0.3.0 capability tools
# =============================================================================


async def test_import_model(client, tmp_path):
    stub = tmp_path / "part.stl"
    stub.write_bytes(b"solid x\nendsolid x\n")
    r = await client.call_tool("blender_import_model", {"filepath": str(stub)})
    assert not r.is_error, r.content
    assert r.structured_content["objects_added"] == ["Imported_0"]


async def test_import_missing_file(client):
    r = await client.call_tool("blender_import_model", {"filepath": "/nope/missing.stl"})
    assert r.is_error


async def test_export(client, tmp_path):
    out = tmp_path / "scene.stl"
    r = await client.call_tool("blender_export", {
        "filepath": str(out), "objects": ["Cube", "Sphere"],
    })
    assert not r.is_error, r.content
    assert "2 object(s)" in r.content[0].text
    assert "KB" in r.content[0].text


async def test_frame_camera(client, fake_blender):
    r = await client.call_tool("blender_frame_camera", {
        "targets": ["Cube"], "azimuth_deg": 30, "elevation_deg": 15, "lens": 85,
    })
    assert not r.is_error, r.content
    assert "Camera" in r.content[0].text
    assert "screenshot" in r.content[0].text
    method, params = fake_blender.calls[-1]
    assert method == "frame_camera"
    assert params["lens"] == 85.0


async def test_modifier_add_with_failed_param(client):
    r = await client.call_tool("blender_modifier", {
        "action": "add", "object_name": "Cube", "modifier_type": "SUBSURF",
        "params": {"levels": 2, "bad_param": True},
    })
    assert not r.is_error, r.content
    assert "SUBSURF" in r.content[0].text
    assert "bad_param" in r.content[0].text  # surfaced as a warning


async def test_modifier_apply_and_remove(client):
    r = await client.call_tool("blender_modifier", {
        "action": "apply", "object_name": "Cube", "modifier_name": "Subsurf",
    })
    assert not r.is_error and "baked" in r.content[0].text
    r = await client.call_tool("blender_modifier", {
        "action": "remove", "object_name": "Cube", "modifier_name": "Subsurf",
    })
    assert not r.is_error and "Removed" in r.content[0].text


async def test_modifier_validation(client):
    r = await client.call_tool("blender_modifier", {"action": "add", "object_name": "Cube"})
    assert r.is_error  # missing modifier_type
    r = await client.call_tool("blender_modifier", {
        "action": "smash", "object_name": "Cube", "modifier_type": "SUBSURF",
    })
    assert r.is_error  # bad action


async def test_duplicate(client):
    r = await client.call_tool("blender_duplicate", {
        "name": "Domino", "count": 5, "offset": [0.5, 0, 0],
    })
    assert not r.is_error, r.content
    assert len(r.structured_content["created"]) == 5


async def test_organize(client):
    r = await client.call_tool("blender_organize", {
        "action": "parent", "objects": ["A", "B"], "parent": "Rig",
    })
    assert not r.is_error and "Parented 2" in r.content[0].text

    r = await client.call_tool("blender_organize", {
        "action": "move_to_collection", "objects": ["A"], "collection": "Props",
    })
    assert not r.is_error and "Props" in r.content[0].text

    r = await client.call_tool("blender_organize", {"action": "parent", "objects": ["A"]})
    assert r.is_error  # parent action without parent


async def test_checkpoint_and_undo(client):
    r = await client.call_tool("blender_checkpoint", {"label": "before experiment"})
    assert not r.is_error and "before experiment" in r.content[0].text

    r = await client.call_tool("blender_undo", {"steps": 2})
    assert not r.is_error and "Undid 2" in r.content[0].text

    r = await client.call_tool("blender_undo", {"steps": 1, "redo": True})
    assert not r.is_error and "Redid 1" in r.content[0].text


# =============================================================================
# Error paths
# =============================================================================


async def test_failed_delete_is_error(client):
    r = await client.call_tool("blender_delete_object", {"name": "Ghost"})
    assert r.is_error
    assert "not found" in r.content[0].text


async def test_bad_procedural_type_is_error(client):
    r = await client.call_tool("ai_generate_procedural", {"object_type": "spaceship"})
    assert r.is_error


# =============================================================================
# Resources
# =============================================================================


async def test_scene_resource(client):
    res = await client.read_resource("blender://scene")
    assert json.loads(res.contents[0].text)["name"] == "Scene"


async def test_object_resource_template(client):
    res = await client.read_resource("blender://object/Cube")
    body = json.loads(res.contents[0].text)
    assert body["name"] == "Cube"
    assert body["mesh"]["polygon_count"] == 6


async def test_latest_render_resource(client):
    srv._LAST_RENDER["path"] = None
    with pytest.raises(Exception):
        await client.read_resource("blender://render/latest")

    await client.call_tool("blender_screenshot", {})
    res = await client.read_resource("blender://render/latest")
    blob = res.contents[0]
    assert getattr(blob, "blob", None), "expected binary contents"


# =============================================================================
# Transport behaviour
# =============================================================================


async def test_timeout_resets_connection(fake_blender):
    bc = blender_client.BlenderClient("127.0.0.1", fake_blender.port)
    resp = await bc.call("slow_op", timeout=1.0)
    assert "timed out" in resp["error"]["message"]
    assert bc._writer is None  # connection dropped so no desync
    await bc.disconnect()
