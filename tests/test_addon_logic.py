# SPDX-License-Identifier: MIT
"""
Addon-logic tests against the structured fake bpy.

These target the bug class the protocol-level fake can't see: scene state
that must survive a tool call (render settings, frame range, mode).
"""

import os

import pytest

from fake_bpy import Bag, load_module, make_bpy


def _render_snapshot(scene):
    r = scene.render
    return (
        r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage,
        r.image_settings.file_format, r.filepath, r.fps,
        scene.cycles.samples, scene.eevee.taa_render_samples,
        scene.frame_current,
    )


@pytest.fixture
def scene_env(tmp_path):
    bpy = make_bpy()
    mod = load_module("scene_utils.py", bpy)
    return Bag(bpy=bpy, mod=mod, ser=mod.SceneSerializer(), tmp=tmp_path)


@pytest.fixture
def executor_env():
    bpy = make_bpy()
    mod = load_module("executor.py", bpy)
    return Bag(bpy=bpy, mod=mod, ex=mod.CommandExecutor())


# =============================================================================
# render_image: per-call overrides never leak into the scene
# =============================================================================


def test_render_image_restores_settings(scene_env):
    scene = scene_env.bpy.context.scene
    before = _render_snapshot(scene)

    result = scene_env.ser.render_image(
        filepath=str(scene_env.tmp / "draft.png"),
        engine="CYCLES", samples=8, resolution_x=640, resolution_y=360,
    )

    assert result["success"], result
    assert result["engine"] == "CYCLES"
    assert result["resolution"] == [640, 360]
    assert _render_snapshot(scene) == before, "render settings leaked into the scene"

    # The render itself ran with the overrides and a still-image format
    op, kwargs = scene_env.bpy.ops.calls[-1]
    assert op == "render.render" and kwargs == {"write_still": True}


def test_render_image_restores_settings_on_failure(scene_env):
    scene = scene_env.bpy.context.scene
    before = _render_snapshot(scene)

    def boom(**kwargs):
        raise RuntimeError("render exploded")

    scene_env.bpy.ops.handlers["render.render"] = boom
    result = scene_env.ser.render_image(engine="CYCLES", samples=8)

    assert not result["success"]
    assert "exploded" in result["error"]
    assert _render_snapshot(scene) == before, "failure path leaked settings"


# =============================================================================
# capture_viewport: PNG pinned, no write_still clobber, restore on all paths
# =============================================================================


def _add_viewport(bpy):
    area = Bag(type="VIEW_3D",
               regions=[Bag(type="HEADER"), Bag(type="WINDOW")])
    bpy.context.screen.areas.append(area)


def test_capture_viewport_pins_png_and_restores(scene_env):
    bpy = scene_env.bpy
    _add_viewport(bpy)
    scene = bpy.context.scene
    before = _render_snapshot(scene)
    seen = {}

    def opengl(**kwargs):
        seen["format"] = scene.render.image_settings.file_format
        seen["pct"] = scene.render.resolution_percentage
        seen["kwargs"] = kwargs

    bpy.ops.handlers["render.opengl"] = opengl
    result = scene_env.ser.capture_viewport(str(scene_env.tmp / "shot.png"), 320, 180)

    assert result["success"], result
    # An FFMPEG leftover from an animation render must not reach save_render
    assert seen["format"] == "PNG"
    assert seen["pct"] == 100
    # write_still would overwrite whatever render.filepath points at
    assert "write_still" not in seen["kwargs"]
    assert bpy.data.images["Render Result"].saved_to == [str(scene_env.tmp / "shot.png")]
    assert _render_snapshot(scene) == before


def test_capture_viewport_restores_on_failure(scene_env):
    bpy = scene_env.bpy
    _add_viewport(bpy)
    scene = bpy.context.scene
    before = _render_snapshot(scene)

    def boom(**kwargs):
        raise RuntimeError("no GPU for you")

    bpy.ops.handlers["render.opengl"] = boom
    result = scene_env.ser.capture_viewport(str(scene_env.tmp / "shot.png"))

    assert not result["success"]
    # The confirmed live bug: the old code left capture resolution behind here
    assert _render_snapshot(scene) == before


def test_capture_viewport_headless_is_graceful(scene_env):
    scene_env.bpy.context.screen = None
    result = scene_env.ser.capture_viewport()
    assert not result["success"]
    assert "headless" in result["error"] or "viewport" in result["error"]


# =============================================================================
# render_animation: frame range + settings restore, MP4 rename
# =============================================================================


def test_render_animation_restores_and_renames(scene_env):
    bpy = scene_env.bpy
    scene = bpy.context.scene
    before = _render_snapshot(scene)
    out = scene_env.tmp / "anim.mp4"

    def animate(**kwargs):
        assert kwargs == {"animation": True}
        # An animation render walks the playhead to the last frame
        scene.frame_current = 12
        # Blender names video output stem + zero-padded frame range
        produced = f"{scene.render.filepath}0001-0012.mp4"
        with open(produced, "wb") as f:
            f.write(b"\x00" * 64)

    bpy.ops.handlers["render.render"] = animate
    result = scene_env.ser.render_animation(
        filepath=str(out), frame_start=1, frame_end=12, fps=12,
        engine="CYCLES", samples=4, resolution_x=320, resolution_y=180,
    )

    assert result["success"], result
    assert result["filepath"] == str(out) and os.path.isfile(out)
    assert result["frame_count"] == 12 and result["fps"] == 12

    assert (scene.frame_start, scene.frame_end) == (1, 250), "frame range leaked"
    assert _render_snapshot(scene) == before, "animation render leaked settings"


def test_render_animation_rejects_hash_in_name(scene_env):
    result = scene_env.ser.render_animation(
        filepath=str(scene_env.tmp / "anim_##.mp4"), frame_start=1, frame_end=2,
    )
    assert not result["success"]
    assert "#" in result["error"]


# =============================================================================
# Executor: Edit Mode guard
# =============================================================================


def test_add_object_switches_out_of_edit_mode(executor_env):
    bpy = executor_env.bpy
    bpy.context.mode = "EDIT_MESH"

    def mode_set(mode):
        bpy.context.mode = mode
        return {'FINISHED'}

    created = Bag(name="Cube", type="MESH", location=[0, 0, 0], scale=(1, 1, 1))

    def cube_add(**kwargs):
        bpy.context.active_object = created
        return {'FINISHED'}

    bpy.ops.handlers["object.mode_set"] = mode_set
    bpy.ops.handlers["mesh.primitive_cube_add"] = cube_add

    result = executor_env.ex.add_object("cube", name="Crate")
    assert result["success"], result
    assert bpy.context.mode == "OBJECT"
    assert created.name == "Crate"


def test_add_object_refuses_when_stuck_in_edit_mode(executor_env):
    bpy = executor_env.bpy
    bpy.context.mode = "EDIT_MESH"

    def refuse(**kwargs):
        raise RuntimeError("poll failed")

    bpy.ops.handlers["object.mode_set"] = refuse
    result = executor_env.ex.add_object("cube", name="Crate")

    assert not result["success"]
    assert "Object Mode" in result["error"]
    # And crucially: nothing was created or renamed
    assert all(op != "mesh.primitive_cube_add" for op, _ in bpy.ops.calls)


def test_undo_refused_headless(executor_env):
    executor_env.bpy.app.background = True
    result = executor_env.ex.undo()
    assert not result["success"]
    assert "background" in result["error"]


# =============================================================================
# Contract: the protocol fake must stay a subset of the real addon output
# =============================================================================


def _real_scene_and_object(scene_env):
    bpy = scene_env.bpy
    mesh_data = Bag(
        materials=[],
        vertices=[0] * 8, edges=[0] * 12, polygons=[0] * 6, uv_layers=[],
    )
    obj = Bag(
        name="Cube", type="MESH",
        location=[0.0, 0.0, 0.0], rotation_euler=[0.0, 0.0, 0.0],
        scale=[1.0, 1.0, 1.0], dimensions=[2.0, 2.0, 2.0],
        hide_viewport=False, hide_render=False,
        parent=None, children=[],
        modifiers=[Bag(name="Subsurf", type="SUBSURF", show_viewport=True)],
        users_collection=[Bag(name="Collection")],
        data=mesh_data,
    )
    obj.select_get = lambda: False
    bpy.data.objects.add(obj)
    bpy.context.scene.objects.append(obj)
    bpy.context.view_layer.objects.active = obj
    return obj


def test_fake_get_scene_contract(scene_env):
    """Every key the conftest fake serves must exist in the real payload."""
    from conftest import FakeBlender

    _real_scene_and_object(scene_env)
    real = scene_env.ser.get_scene_info("basic")
    fake = FakeBlender.__dict__["_h_get_scene"](None, {})

    missing = set(fake) - set(real)
    assert not missing, f"fake advertises keys the real addon never sends: {missing}"


def test_fake_get_object_contract(scene_env):
    from conftest import FakeBlender

    _real_scene_and_object(scene_env)
    real = scene_env.ser.get_object_info("Cube")
    fake = FakeBlender.__dict__["_h_get_object"](None, {"name": "Cube"})

    missing = set(fake) - set(real)
    assert not missing, f"fake advertises keys the real addon never sends: {missing}"
