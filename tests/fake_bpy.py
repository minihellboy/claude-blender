# SPDX-License-Identifier: MIT
"""
A structured bpy stand-in for testing addon logic outside Blender.

Unlike the MagicMock stubs used for exec'ing generated payloads, this fake
models the specific state the addon reads and writes - scene render
settings, operator dispatch, context mode - so tests can assert on
*semantics* (was the format pinned? were settings restored?), which is
exactly the class of bug a protocol-level fake cannot see.
"""

import importlib.util
import os
import sys
import types
from contextlib import contextmanager


class Bag:
    """Attribute bag - close enough to most bpy structs."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ObjectMap:
    """dict-backed stand-in for bpy.data.objects."""

    def __init__(self):
        self._d = {}

    def get(self, name, default=None):
        return self._d.get(name, default)

    def keys(self):
        return self._d.keys()

    def __contains__(self, name):
        return name in self._d

    def __getitem__(self, name):
        return self._d[name]

    def add(self, obj):
        self._d[obj.name] = obj


class _OpCategory:
    def __init__(self, ops, category):
        self._ops = ops
        self._category = category

    def __getattr__(self, name):
        op_id = f"{self._category}.{name}"

        def op(*args, **kwargs):
            self._ops.calls.append((op_id, kwargs))
            handler = self._ops.handlers.get(op_id)
            if handler:
                return handler(**kwargs)
            return {'FINISHED'}

        return op


class FakeOps:
    """bpy.ops replacement: records every call, dispatches to handlers."""

    def __init__(self):
        self.calls = []
        self.handlers = {}

    def __getattr__(self, category):
        if category.startswith('_') or category in ('calls', 'handlers'):
            raise AttributeError(category)
        return _OpCategory(self, category)


def make_scene():
    """A scene whose render settings are deliberately NON-default, so any
    handler that fails to restore them turns the difference into a failure."""
    return Bag(
        name="Scene",
        frame_current=42,
        frame_start=1,
        frame_end=250,
        objects=[],
        world=None,
        camera=None,
        collection=Bag(objects=Bag(link=lambda o: None), children=Bag(link=lambda c: None)),
        render=Bag(
            engine="BLENDER_EEVEE_NEXT",
            resolution_x=3840,
            resolution_y=2160,
            resolution_percentage=50,
            fps=25,
            filepath="/tmp/users_own_output.png",
            film_transparent=False,
            image_settings=Bag(file_format="OPEN_EXR"),
            ffmpeg=Bag(format="", codec="", constant_rate_factor="", audio_codec=""),
        ),
        cycles=Bag(samples=4096),
        eevee=Bag(taa_render_samples=512),
    )


def make_bpy():
    """Build a fresh fake bpy module."""
    bpy = types.ModuleType("bpy")

    scene = make_scene()
    window = Bag(screen=Bag(areas=[]))

    context = Bag(
        scene=scene,
        mode="OBJECT",
        active_object=None,
        selected_objects=[],
        window_manager=Bag(windows=[window]),
        view_layer=Bag(objects=Bag(active=None)),
        screen=window.screen,
    )
    context.copy = lambda: {}

    @contextmanager
    def temp_override(**kwargs):
        yield

    context.temp_override = temp_override

    render_result = Bag(saved_to=[], )
    render_result.save_render = lambda filepath: render_result.saved_to.append(filepath)

    bpy.app = Bag(
        background=False,
        version_string="4.3.2-fake",
        timers=Bag(register=lambda *a, **k: None),
    )
    bpy.path = Bag(abspath=lambda p: p)
    bpy.ops = FakeOps()
    bpy.context = context
    bpy.data = Bag(
        objects=ObjectMap(),
        images={"Render Result": render_result},
        materials=Bag(new=lambda name: Bag(name=name, use_nodes=False)),
        textures=Bag(new=lambda name, kind: Bag(name=name)),
        collections=Bag(get=lambda name: None, new=lambda name: Bag(name=name)),
        filepath="",
    )
    return bpy


_ADDON_CORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "claude_blender", "blender_addon", "core",
)


def load_module(module_file, fake_bpy_module, name=None):
    """Import an addon core module bound to the given fake bpy."""
    name = name or f"_fake_{module_file[:-3]}"
    old = sys.modules.get("bpy")
    sys.modules["bpy"] = fake_bpy_module
    try:
        spec = importlib.util.spec_from_file_location(
            name, os.path.join(_ADDON_CORE, module_file)
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if old is not None:
            sys.modules["bpy"] = old
        else:
            del sys.modules["bpy"]
