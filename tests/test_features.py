# SPDX-License-Identifier: MIT
"""
v0.5.0 features against the fake Blender: scene diffs, multi-view sheets,
background render jobs, and elicitation-confirmed overwrites.
"""

import asyncio
import copy
import json
import os

import pytest
from mcp.client import Client

from claude_blender_mcp import server as srv
from claude_blender_mcp import snapshots
from claude_blender_mcp.render_jobs import pick_evenly


def _texts(result):
    return "\n".join(c.text for c in result.content if hasattr(c, "text"))


def _images(result):
    return [c for c in result.content if "Image" in type(c).__name__]


# =============================================================================
# Snapshot diff logic (pure)
# =============================================================================


def test_diff_states_reports_every_section():
    before = {
        "scene": {"engine": "CYCLES", "fps": 24},
        "objects": {
            "Cube": {"type": "MESH", "location": [0, 0, 0], "materials": []},
            "Gone": {"type": "EMPTY"},
        },
    }
    after = {
        "scene": {"engine": "CYCLES", "fps": 30},
        "objects": {
            "Cube": {"type": "MESH", "location": [1, 0, 0], "materials": ["Red"]},
            "New": {"type": "LIGHT"},
        },
    }
    diff = snapshots.diff_states(before, after)
    assert diff["added"] == ["New"]
    assert diff["removed"] == ["Gone"]
    assert diff["changed"] == {
        "Cube": {"location": [[0, 0, 0], [1, 0, 0]], "materials": [[], ["Red"]]}
    }
    assert diff["scene"] == {"fps": [24, 30]}

    text = snapshots.summarize(diff, after)
    assert "+ added (1): New (LIGHT)" in text
    assert "- removed (1): Gone" in text
    assert "Cube: location [0, 0, 0] -> [1, 0, 0]" in text
    assert "fps 24 -> 30" in text


def test_diff_identical_is_empty():
    state = {"scene": {"fps": 24}, "objects": {"A": {"type": "MESH"}}}
    diff = snapshots.diff_states(state, copy.deepcopy(state))
    assert snapshots.is_empty(diff)
    assert snapshots.summarize(diff) == "No changes."


def test_snapshot_store_is_bounded_lru():
    store = snapshots.SnapshotStore(capacity=2)
    a = store.add({"objects": {}})
    b = store.add({"objects": {}})
    store.get(a)  # touch: a becomes most recent
    c = store.add({"objects": {}})
    assert store.ids() == [a, c] and store.get(b) is None


def test_pick_evenly_keeps_both_ends():
    assert pick_evenly(list(range(10)), 3) == [0, 4, 9]
    assert pick_evenly([1, 2], 8) == [1, 2]
    assert pick_evenly([], 4) == []


# =============================================================================
# Snapshot / diff / execute change reports
# =============================================================================


async def test_snapshot_then_diff_live(client, fake_blender):
    r = await client.call_tool("blender_snapshot", {"label": "before lighting"})
    snap = r.structured_content
    assert snap["object_count"] == 2 and snap["snapshot_id"].startswith("snap-")

    fake_blender.state["objects"]["Cube"]["location"] = [0, 0, 2]
    fake_blender.state["objects"]["Key"] = {"type": "LIGHT"}
    del fake_blender.state["objects"]["Light"]

    r = await client.call_tool("blender_diff", {"snapshot_id": snap["snapshot_id"]})
    d = r.structured_content
    assert d["against"] == "live"
    assert d["added"] == ["Key"] and d["removed"] == ["Light"]
    assert d["changed"]["Cube"]["location"] == [[0, 0, 0], [0, 0, 2]]
    assert "Key (LIGHT)" in d["summary"]


async def test_diff_between_two_snapshots(client, fake_blender):
    a = (await client.call_tool("blender_snapshot", {})).structured_content["snapshot_id"]
    fake_blender.state["scene"]["fps"] = 60
    b = (await client.call_tool("blender_snapshot", {})).structured_content["snapshot_id"]
    fake_blender.state["scene"]["fps"] = 12  # live state must NOT be consulted

    d = (await client.call_tool("blender_diff", {"snapshot_id": a, "against": b})).structured_content
    assert d["scene"] == {"fps": [24, 60]}


async def test_diff_unknown_snapshot_lists_known(client):
    r = await client.call_tool("blender_diff", {"snapshot_id": "snap-nope"})
    assert r.is_error and "Unknown snapshot" in _texts(r)


async def test_execute_reports_scene_changes(client, fake_blender):
    after = copy.deepcopy(fake_blender.state)
    after["objects"]["Suzanne"] = {"type": "MESH", "location": [0, 0, 1]}
    after["objects"]["Cube"]["materials"] = ["Mat", "Gold"]
    fake_blender.state_after_execute = after

    r = await client.call_tool("blender_execute", {"code": "x = 1"})
    text = _texts(r)
    assert not r.is_error
    assert "Scene changes:" in text
    assert "Suzanne (MESH)" in text
    assert "materials ['Mat'] -> ['Mat', 'Gold']" in text


async def test_execute_change_report_on_error(client, fake_blender):
    """A script that fails halfway still shows what it already changed."""
    after = copy.deepcopy(fake_blender.state)
    after["objects"]["Half"] = {"type": "MESH"}
    fake_blender.state_after_execute = after

    r = await client.call_tool("blender_execute", {"code": "raise ValueError('boom')"})
    text = _texts(r)
    assert r.is_error
    assert "boom" in text and "Half (MESH)" in text


async def test_execute_without_change_report(client, fake_blender):
    r = await client.call_tool("blender_execute", {"code": "x = 1", "report_changes": False})
    assert "Scene changes" not in _texts(r)
    assert not any(m == "scene_state" for m, _ in fake_blender.calls)


async def test_execute_tolerates_addon_without_scene_state(client, fake_blender, monkeypatch):
    # e.g. a scene over max_objects, or an addon predating scene_state
    monkeypatch.setattr(fake_blender, "_h_scene_state", lambda params: {"success": False})
    r = await client.call_tool("blender_execute", {"code": "__result__ = 2"})
    assert not r.is_error and "Result: 2" in _texts(r)
    assert "Scene changes" not in _texts(r)


# =============================================================================
# Multi-view contact sheet
# =============================================================================


async def test_render_views_returns_sheet(client, fake_blender):
    r = await client.call_tool("blender_render_views", {
        "targets": ["Cube"],
        "views": ["front", "top", {"name": "low", "azimuth": 30, "elevation": -10}],
        "ortho": True,
    })
    assert not r.is_error
    assert len(_images(r)) == 1
    text = _texts(r)
    assert "ORTHO" in text and "front | top" in text and "low" in text

    method, params = [c for c in fake_blender.calls if c[0] == "render_views"][-1]
    assert params["ortho"] is True
    assert params["views"][2] == {"name": "low", "azimuth": 30, "elevation": -10}


# =============================================================================
# Background render jobs
# =============================================================================


@pytest.fixture(autouse=True)
def _fresh_jobs(monkeypatch):
    monkeypatch.setattr(srv, "_JOBS", srv.JobManager())


async def test_render_job_runs_to_completion(client, fake_blender, tmp_path):
    out = str(tmp_path / "turntable.mp4")
    r = await client.call_tool("blender_render_job_start", {
        "frame_start": 1, "frame_end": 8, "frame_step": 2,
        "resolution_x": 320, "resolution_y": 240, "filepath": out,
    })
    st = r.structured_content
    assert st["frames_total"] == 4 and st["frame_range"] == [1, 7]

    r = await client.call_tool("blender_render_job_status", {
        "job_id": st["job_id"], "wait_seconds": 10,
    })
    status = json.loads(r.content[0].text)
    assert status["status"] == "completed", status
    assert status["output"] == out and os.path.exists(out)
    assert len(_images(r)) == 1  # auto preview -> contact sheet once done

    renders = [p for m, p in fake_blender.calls if m == "render"]
    assert [p["frame"] for p in renders] == [1, 3, 5, 7]
    assert all(p["resolution_x"] == 320 for p in renders)
    encode = [p for m, p in fake_blender.calls if m == "encode_video"][-1]
    assert encode["fps"] == 12  # scene fps 24 / frame_step 2
    assert len(encode["frame_paths"]) == 4


async def test_render_job_defaults_to_scene_range(client, fake_blender):
    st = (await client.call_tool("blender_render_job_start", {
        "container": "PNG", "frame_step": 8,
    })).structured_content
    assert st["frame_range"] == [1, 41] and st["frames_total"] == 6


async def test_render_job_cancel_stops_between_frames(client, fake_blender):
    fake_blender.render_delay = 0.2
    st = (await client.call_tool("blender_render_job_start", {
        "frame_start": 1, "frame_end": 100,
    })).structured_content

    # Other tools keep working while the job renders.
    await asyncio.sleep(0.3)
    assert not (await client.call_tool("blender_get_object", {"name": "Cube"})).is_error

    await client.call_tool("blender_render_job_cancel", {"job_id": st["job_id"]})
    r = await client.call_tool("blender_render_job_status", {
        "job_id": st["job_id"], "wait_seconds": 5, "preview": "latest",
    })
    status = json.loads(r.content[0].text)
    assert status["status"] == "cancelled"
    assert 0 < status["frames_done"] < 100
    assert len(_images(r)) == 1
    assert not any(m == "encode_video" for m, _ in fake_blender.calls)


async def test_render_job_refuses_second_concurrent_job(client, fake_blender):
    fake_blender.render_delay = 0.2
    st = (await client.call_tool("blender_render_job_start", {
        "frame_start": 1, "frame_end": 50,
    })).structured_content
    r = await client.call_tool("blender_render_job_start", {"frame_start": 1, "frame_end": 2})
    assert r.is_error and st["job_id"] in _texts(r)
    await client.call_tool("blender_render_job_cancel", {"job_id": st["job_id"]})
    await client.call_tool("blender_render_job_status", {"job_id": st["job_id"], "wait_seconds": 5})


async def test_render_job_failure_is_recorded(client, fake_blender, monkeypatch):
    monkeypatch.setattr(fake_blender, "_h_render",
                        lambda params: {"success": False, "error": "GPU on fire"})
    st = (await client.call_tool("blender_render_job_start", {
        "frame_start": 1, "frame_end": 3,
    })).structured_content
    r = await client.call_tool("blender_render_job_status", {
        "job_id": st["job_id"], "wait_seconds": 5,
    })
    status = json.loads(r.content[0].text)
    assert status["status"] == "failed"
    assert "frame 1 failed: GPU on fire" in status["error"]


async def test_render_job_rejects_odd_mp4_resolution(client):
    r = await client.call_tool("blender_render_job_start", {"resolution_x": 641})
    assert r.is_error and "even" in _texts(r)


async def test_render_job_status_lists_jobs(client):
    r = await client.call_tool("blender_render_job_status", {})
    assert "No render jobs" in _texts(r)


# =============================================================================
# Elicitation: confirm before overwriting files (multi-round-trip requests)
# =============================================================================


def _elicit_answer(answer: bool | None, seen: list):
    from mcp_types import ElicitResult

    async def callback(context, params):
        seen.append(params.message)
        if answer is None:
            return ElicitResult(action="decline")
        return ElicitResult(action="accept", content={"overwrite": answer})

    return callback


async def _with_client(callback, tool, args):
    async with Client(srv.mcp, elicitation_callback=callback) as c:
        return await c.call_tool(tool, args)


@pytest.mark.parametrize("answer, ok", [(True, True), (False, False), (None, False)])
async def test_export_overwrite_asks_user(fake_blender, tmp_path, answer, ok):
    target = tmp_path / "part.stl"
    target.write_bytes(b"old")
    seen: list = []

    r = await _with_client(_elicit_answer(answer, seen), "blender_export",
                           {"filepath": str(target)})

    assert len(seen) == 1 and "already exists" in seen[0]
    exported = any(m == "export_model" for m, _ in fake_blender.calls)
    assert exported is ok
    assert r.is_error is (not ok)
    if not ok:
        assert "declined to overwrite" in _texts(r)
        assert target.read_bytes() == b"old"


async def test_export_new_file_does_not_ask(fake_blender, tmp_path):
    seen: list = []
    r = await _with_client(_elicit_answer(True, seen), "blender_export",
                           {"filepath": str(tmp_path / "fresh.glb")})
    assert not r.is_error and seen == []


async def test_save_over_other_blend_asks(fake_blender, tmp_path):
    other = tmp_path / "other.blend"
    other.write_bytes(b"BLENDER")
    seen: list = []
    r = await _with_client(_elicit_answer(False, seen), "blender_save",
                           {"filepath": str(tmp_path / "other")})  # .blend appended
    assert r.is_error and len(seen) == 1
    assert not any(m == "save_file" for m, _ in fake_blender.calls)


async def test_overwrite_without_elicitation_support_proceeds(client, fake_blender, tmp_path):
    """Clients that can't elicit keep the pre-0.5 behavior."""
    target = tmp_path / "part.stl"
    target.write_bytes(b"old")
    r = await client.call_tool("blender_export", {"filepath": str(target)})
    assert not r.is_error
    assert any(m == "export_model" for m, _ in fake_blender.calls)
