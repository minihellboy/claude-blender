# SPDX-License-Identifier: MIT
"""
Claude Blender MCP Server

Model Context Protocol server for Claude Code integration with Blender.
Provides tools for scene manipulation, object creation, rendering, and LOCAL AI generation.

All AI runs locally - no external API calls.

Requires mcp>=2.0.0 (MCP protocol revision 2026-07-28).
"""

import json
import os
import tempfile
from typing import Optional

from typing_extensions import TypedDict

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.server.mcpserver.server import CacheHint
from mcp.types import ToolAnnotations

from .blender_client import get_client, BlenderClient


# The tool/prompt surface is static, so clients may cache list results for an hour.
_LIST_CACHE = CacheHint(ttl_ms=3_600_000, scope="private")

mcp = MCPServer(
    "blender",
    description=(
        "Control Blender 3D through natural language. Create, modify, and render "
        "3D scenes. AI generation runs locally."
    ),
    instructions=(
        "Tools for driving a live Blender instance over a local socket.\n"
        "\n"
        "Recommended working loop:\n"
        "1. INSPECT before acting: blender_get_scene / blender_get_object (or the "
        "blender://scene resource). Never assume object names or positions.\n"
        "2. CHECKPOINT before risky changes: call blender_checkpoint before "
        "destructive edits or blender_execute, then blender_undo if the result "
        "is wrong. This makes aggressive experimentation cheap.\n"
        "3. ACT with dedicated tools first (add/modify/delete, materials, "
        "modifiers, duplicate, organize, import/export, frame_camera). Reserve "
        "blender_execute for what no dedicated tool covers.\n"
        "4. VERIFY visually: blender_screenshot is fast (GUI only); "
        "blender_render shows the truth. Look at the returned image and "
        "critique framing, lighting, and materials before declaring success.\n"
        "5. ITERATE cheap, FINISH expensive: draft renders at 640x360 with "
        "BLENDER_EEVEE_NEXT or CYCLES at <=32 samples; only the final render "
        "deserves full resolution and high samples.\n"
        "\n"
        "Tips:\n"
        "- blender_save persists the .blend file; nothing else does. Save "
        "after substantial scene work.\n"
        "- blender_frame_camera aims the camera at any object(s) with correct "
        "fit math; use it instead of hand-computing camera transforms.\n"
        "- blender_render_animation returns preview stills from the video so "
        "you can judge motion without watching the file.\n"
        "- If a tool reports a connection problem, call blender_ping and tell "
        "the user to start the server from Blender's Claude sidebar tab."
    ),
    version="0.4.0",
    cache_hints={
        "tools/list": _LIST_CACHE,
        "prompts/list": _LIST_CACHE,
        "resources/list": _LIST_CACHE,
    },
)

# Blender is a closed local domain: nothing here touches the open internet.
_READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
_ADDITIVE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)
_CAPTURE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)
_IDEMPOTENT_WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

# Images above this size are referenced by path instead of inlined into the result.
_MAX_INLINE_IMAGE_BYTES = 4 * 1024 * 1024

# Path of the most recent render/screenshot, served by blender://render/latest.
_LAST_RENDER = {"path": None}


def get_blender() -> BlenderClient:
    """Get the Blender client instance."""
    host = os.environ.get("BLENDER_HOST", "127.0.0.1")
    port = int(os.environ.get("BLENDER_PORT", "9876"))
    return get_client(host, port)


def _unwrap(response: dict) -> dict:
    """Return the JSON-RPC result payload, raising ToolError on protocol errors."""
    if "error" in response:
        raise ToolError(response["error"].get("message", "Unknown error"))
    result = response.get("result", {})
    return result if isinstance(result, dict) else {"value": result}


def _require_success(result: dict, action: str) -> None:
    """Raise ToolError if a Blender-side operation reported failure."""
    if not result.get("success"):
        raise ToolError(f"{action} failed: {result.get('error', 'Unknown error')}")


def _ai_payload(result: dict, action: str) -> dict:
    """Return the __result__ dict from an ai_* execute call, or raise.

    Guards the silent-failure path: when the generated code itself crashes,
    execute reports success=False with result=None - that must surface as a
    ToolError, never as a success-shaped string.
    """
    if result.get("error"):
        raise ToolError(f"{action} failed: {result['error']}")
    payload = result.get("result")
    if not isinstance(payload, dict):
        raise ToolError(f"{action} returned an unexpected result: {payload!r}")
    if not payload.get("success"):
        raise ToolError(f"{action} failed: {payload.get('error', 'Unknown error')}")
    return payload


def _preview(message: str, path: str) -> list:
    """Pair a status message with the image content when it is small enough to inline."""
    try:
        if os.path.getsize(path) <= _MAX_INLINE_IMAGE_BYTES:
            return [message, Image(path=path)]
    except OSError:
        return [f"{message} (file could not be read for preview)"]
    return [f"{message} (too large to preview inline)"]


# =============================================================================
# Structured output types
# =============================================================================


class SceneObjectInfo(TypedDict):
    name: str
    type: str


class SceneInfo(TypedDict):
    name: str
    object_count: int
    active_object: Optional[str]
    objects: list[SceneObjectInfo]


class ModifierInfo(TypedDict):
    name: str
    type: str


class ObjectInfo(TypedDict):
    # All keys are always emitted: the SDK serializes omitted NotRequired
    # keys as null, which would then violate this very schema.
    name: str
    type: str
    location: list[float]
    rotation: list[float]
    scale: list[float]
    visible: bool
    dimensions: list[float]
    materials: list[str]
    modifiers: list[ModifierInfo]
    collections: list[str]
    vertex_count: Optional[int]
    polygon_count: Optional[int]


class ImportResult(TypedDict):
    filepath: str
    format: str
    objects_added: list[str]


class DuplicateResult(TypedDict):
    source: str
    created: list[str]


# =============================================================================
# Connection Tools
# =============================================================================


@mcp.tool(annotations=_READ_ONLY)
async def blender_ping() -> str:
    """
    Check if Blender is running and reachable.

    Returns:
        Connection status message
    """
    client = get_blender()
    if await client.ping():
        return "Blender is connected and responding"
    return (
        "Cannot connect to Blender. Make sure Blender is running with the "
        "Claude addon enabled and server started."
    )


@mcp.tool(annotations=_READ_ONLY)
async def blender_version() -> str:
    """
    Get Blender and addon version information.

    Returns:
        Version information as formatted string
    """
    client = get_blender()
    result = _unwrap(await client.call("version"))
    return (
        f"Blender {result.get('blender_version', 'unknown')}, "
        f"Addon v{result.get('addon_version', 'unknown')}"
    )


# =============================================================================
# Scene Tools
# =============================================================================


@mcp.tool(annotations=_READ_ONLY)
async def blender_get_scene(detail_level: str = "basic") -> SceneInfo:
    """
    Get information about the current Blender scene.

    Args:
        detail_level: Level of detail - 'minimal', 'basic', 'detailed', or 'full'

    Returns:
        Scene name, object count, active object, and the objects in the scene
    """
    client = get_blender()
    result = _unwrap(await client.get_scene(detail_level))

    objects: list[SceneObjectInfo] = []
    for obj in result.get("objects", []):
        if isinstance(obj, dict):
            objects.append(
                {"name": obj.get("name", "Unknown"), "type": obj.get("type", "UNKNOWN")}
            )
        else:
            objects.append({"name": str(obj), "type": "UNKNOWN"})

    return {
        "name": result.get("name", "Unknown"),
        "object_count": result.get("object_count", 0),
        "active_object": result.get("active_object"),
        "objects": objects,
    }


@mcp.tool(annotations=_READ_ONLY)
async def blender_get_object(name: str) -> ObjectInfo:
    """
    Get detailed information about a specific object.

    Args:
        name: Name of the object to inspect

    Returns:
        Object transform, visibility, dimensions, and materials
    """
    client = get_blender()
    result = _unwrap(await client.get_object(name))

    if "error" in result:
        raise ToolError(str(result["error"]))

    mesh = result.get("mesh") if isinstance(result.get("mesh"), dict) else {}
    info: ObjectInfo = {
        "name": result.get("name", name),
        "type": result.get("type", "UNKNOWN"),
        "location": [float(v) for v in result.get("location", [0, 0, 0])],
        # The addon emits 'rotation_euler' here (object detail) but plain
        # 'rotation' in scene listings; accept either.
        "rotation": [
            float(v)
            for v in result.get("rotation_euler") or result.get("rotation") or [0, 0, 0]
        ],
        "scale": [float(v) for v in result.get("scale", [1, 1, 1])],
        "visible": bool(result.get("visible", True)),
        "dimensions": [float(v) for v in result.get("dimensions", [0, 0, 0])],
        "materials": [str(m) for m in result.get("materials") or []],
        "modifiers": [
            {"name": str(m.get("name")), "type": str(m.get("type"))}
            for m in result.get("modifiers") or []
            if isinstance(m, dict)
        ],
        "collections": [str(c) for c in result.get("collections") or []],
        "vertex_count": int(mesh["vertex_count"]) if "vertex_count" in mesh else None,
        "polygon_count": int(mesh["polygon_count"]) if "polygon_count" in mesh else None,
    }
    return info


# =============================================================================
# Object Creation Tools
# =============================================================================


@mcp.tool(annotations=_ADDITIVE)
async def blender_add_object(
    object_type: str,
    name: Optional[str] = None,
    location: Optional[list] = None,
    rotation: Optional[list] = None,
    scale: Optional[list] = None,
    energy: Optional[float] = None,
    color: Optional[list] = None,
    size: Optional[float] = None,
) -> str:
    """
    Add a primitive object to the scene.

    Args:
        object_type: Type of object - 'cube', 'sphere', 'cylinder', 'cone', 'torus',
                     'plane', 'circle', 'monkey', 'empty', 'camera', 'light',
                     'point_light', 'sun', 'spot', 'area'
        name: Optional custom name for the object
        location: Position as [x, y, z] (default: [0, 0, 0])
        rotation: Rotation in radians as [x, y, z] (default: [0, 0, 0])
        scale: Scale as [x, y, z] (default: [1, 1, 1])
        energy: Light power in watts, lights only (e.g. 800 for a key light)
        color: Light color as [r, g, b] 0-1, lights only
        size: Light size in meters (bigger = softer shadows), lights only

    Returns:
        Result message with created object name
    """
    client = get_blender()

    kwargs = {"object_type": object_type}
    if name:
        kwargs["name"] = name
    if location:
        kwargs["location"] = location
    if rotation:
        kwargs["rotation"] = rotation
    if scale:
        kwargs["scale"] = scale
    if energy is not None:
        kwargs["energy"] = float(energy)
    if color is not None:
        kwargs["color"] = [float(c) for c in color[:3]]
    if size is not None:
        kwargs["size"] = float(size)

    result = _unwrap(await client.call("add_object", **kwargs))
    _require_success(result, "Object creation")
    return f"Created {object_type}: '{result.get('object_name', name or object_type)}'"


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True,
                                      idempotent_hint=True, open_world_hint=False))
async def blender_modify_object(
    name: str,
    location: Optional[list] = None,
    rotation: Optional[list] = None,
    scale: Optional[list] = None,
    visible: Optional[bool] = None,
    shade_smooth: Optional[bool] = None,
) -> str:
    """
    Modify an existing object's transform, visibility, or shading.

    Args:
        name: Name of the object to modify
        location: New position as [x, y, z]
        rotation: New rotation in radians as [x, y, z]
        scale: New scale as [x, y, z]
        visible: Set visibility (True/False)
        shade_smooth: Smooth (True) or flat (False) shading - meshes only,
                      the usual companion to a SUBSURF modifier

    Returns:
        Result message
    """
    client = get_blender()

    kwargs = {"name": name}
    if location is not None:
        kwargs["location"] = location
    if rotation is not None:
        kwargs["rotation"] = rotation
    if scale is not None:
        kwargs["scale"] = scale
    if visible is not None:
        kwargs["visible"] = visible
    if shade_smooth is not None:
        kwargs["shade_smooth"] = shade_smooth

    result = _unwrap(await client.modify_object(**kwargs))
    _require_success(result, "Object modification")
    return f"Modified object '{name}'"


@mcp.tool(annotations=_DESTRUCTIVE)
async def blender_delete_object(name: str) -> str:
    """
    Delete an object from the scene.

    Args:
        name: Name of the object to delete

    Returns:
        Result message
    """
    client = get_blender()
    result = _unwrap(await client.delete_object(name))
    _require_success(result, "Object deletion")
    return f"Deleted object '{name}'"


# =============================================================================
# Code Execution Tools
# =============================================================================


@mcp.tool(annotations=_DESTRUCTIVE)
async def blender_execute(code: str, timeout_seconds: int = 120) -> str:
    """
    Execute Python code in Blender's environment.

    This gives you full access to Blender's Python API (bpy).
    Use __result__ variable to return a value.

    Args:
        code: Python code to execute. Has access to bpy and all Blender modules.
        timeout_seconds: How long to wait for completion (1-3600, default 120)

    Returns:
        Execution result including any output and the __result__ value if set

    Example:
        code: '''
        import bpy
        # Create a red material
        mat = bpy.data.materials.new("RedMaterial")
        mat.diffuse_color = (1, 0, 0, 1)
        bpy.context.active_object.data.materials.append(mat)
        __result__ = "Material applied"
        '''
    """
    client = get_blender()
    timeout = float(min(max(timeout_seconds, 1), 3600))
    result = _unwrap(await client.execute(code, timeout=timeout))

    lines = []
    if result.get("output"):
        lines.append(f"Output:\n{result['output']}")

    if result.get("result") is not None:
        lines.append(f"Result: {result['result']}")

    if result.get("error"):
        detail = "\n".join(lines)
        raise ToolError(
            f"Execution error: {result['error']}" + (f"\n{detail}" if detail else "")
        )

    if not lines:
        if result.get("success"):
            return "Code executed successfully"
        return "Execution completed with no output"

    return "\n".join(lines)


# =============================================================================
# Render & Screenshot Tools
# =============================================================================


@mcp.tool(annotations=_CAPTURE, structured_output=False)
async def blender_screenshot(
    filepath: Optional[str] = None,
    width: int = 1280,
    height: int = 720,
):
    """
    Capture a screenshot of the 3D viewport and return the image.

    Args:
        filepath: Where to save the image (default: temp file)
        width: Image width in pixels
        height: Image height in pixels

    Returns:
        The captured image plus the path it was saved to
    """
    client = get_blender()
    result = _unwrap(
        await client.screenshot(filepath=filepath, width=width, height=height, timeout=120.0)
    )
    _require_success(result, "Screenshot")

    path = result.get("filepath")
    if not path or not os.path.exists(path):
        raise ToolError(f"Screenshot reported success but file not found: {path}")

    _LAST_RENDER["path"] = path
    return _preview(f"Screenshot saved to: {path}", path)


@mcp.tool(annotations=_CAPTURE, structured_output=False)
async def blender_render(
    filepath: Optional[str] = None,
    engine: str = "BLENDER_EEVEE_NEXT",
    samples: int = 32,
    resolution_x: int = 960,
    resolution_y: int = 540,
):
    """
    Render the current scene and return the image.

    The defaults are a FAST DRAFT (EEVEE, 960x540, 32 samples) for the
    iterate-cheap loop. For a final image pass engine='CYCLES',
    samples=128+, and full resolution - and expect it to take minutes.
    Render settings are per-call; the user's scene configuration is restored
    afterwards.

    Args:
        filepath: Where to save the render (default: temp file)
        engine: Render engine - 'BLENDER_EEVEE_NEXT' (fast) or 'CYCLES' (quality)
        samples: Number of render samples (higher = better quality, slower)
        resolution_x: Output width in pixels
        resolution_y: Output height in pixels

    Returns:
        The rendered image plus the path it was saved to
    """
    client = get_blender()
    result = _unwrap(
        await client.render(
            filepath=filepath,
            engine=engine,
            samples=samples,
            resolution_x=resolution_x,
            resolution_y=resolution_y,
            timeout=1800.0,
        )
    )
    _require_success(result, "Render")

    path = result.get("filepath")
    if not path or not os.path.exists(path):
        raise ToolError(f"Render reported success but file not found: {path}")

    _LAST_RENDER["path"] = path
    return _preview(f"Render saved to: {path}", path)


@mcp.tool(annotations=_CAPTURE, structured_output=False)
async def blender_render_animation(
    filepath: Optional[str] = None,
    frame_start: Optional[int] = None,
    frame_end: Optional[int] = None,
    fps: Optional[int] = None,
    engine: str = "BLENDER_EEVEE_NEXT",
    samples: int = 64,
    resolution_x: int = 1280,
    resolution_y: int = 720,
    container: str = "MP4",
    preview_frames: int = 3,
    timeout_seconds: int = 1800,
):
    """
    Render the animation to an MP4 video (or PNG sequence) and return preview
    stills so you can judge the motion without opening the file.

    Rendering blocks until every frame is done; budget roughly
    (seconds per frame) x (frame count). Draft with EEVEE at low resolution
    before committing to a long Cycles animation.

    Args:
        filepath: Output .mp4 path (MP4) or directory (PNG); default temp file
        frame_start: First frame (default: scene frame range)
        frame_end: Last frame (default: scene frame range)
        fps: Frames per second (default: scene fps)
        engine: Render engine - 'BLENDER_EEVEE_NEXT' (fast) or 'CYCLES' (quality)
        samples: Render samples per frame
        resolution_x: Output width in pixels
        resolution_y: Output height in pixels
        container: 'MP4' for H.264 video, 'PNG' for an image sequence
        preview_frames: How many evenly spaced preview stills to return (0-5)
        timeout_seconds: How long to wait for the full render (60-7200)

    Returns:
        Video/sequence path, render stats, and inline preview images
    """
    client = get_blender()
    timeout = float(min(max(timeout_seconds, 60), 7200))

    kwargs = {
        "engine": engine,
        "samples": int(samples),
        "resolution_x": int(resolution_x),
        "resolution_y": int(resolution_y),
        "container": container,
    }
    if filepath:
        kwargs["filepath"] = filepath
    if frame_start is not None:
        kwargs["frame_start"] = int(frame_start)
    if frame_end is not None:
        kwargs["frame_end"] = int(frame_end)
    if fps is not None:
        kwargs["fps"] = int(fps)

    result = _unwrap(await client.call("render_animation", timeout=timeout, **kwargs))
    _require_success(result, "Animation render")

    out_path = result.get("filepath")
    start = int(result.get("frame_start", 1))
    end = int(result.get("frame_end", start))
    content: list = [
        f"Animation rendered to: {out_path}\n"
        f"{result.get('frame_count')} frames @ {result.get('fps')} fps, "
        f"{'x'.join(str(v) for v in result.get('resolution', []))}, "
        f"{result.get('engine')}, {result.get('render_time_seconds')}s"
    ]

    n_previews = min(max(int(preview_frames), 0), 5, end - start + 1)
    if n_previews:
        if n_previews == 1:
            frames = [(start + end) // 2]
        else:
            span = end - start
            frames = sorted({start + round(span * i / (n_previews - 1)) for i in range(n_previews)})

        # Preview stills move the playhead; remember where the user had it.
        orig_frame = None
        try:
            r = await client.execute("import bpy\n__result__ = bpy.context.scene.frame_current")
            orig_frame = int(_unwrap(r).get("result"))
        except Exception:
            pass

        for frame in frames:
            try:
                if result.get("container") == "PNG":
                    # Frames are already on disk as frame_0001.png etc.
                    still = os.path.join(out_path, f"frame_{frame:04d}.png")
                else:
                    still = os.path.join(
                        tempfile.gettempdir(), f"claude_anim_preview_{frame:04d}.png"
                    )
                    await client.execute(f"import bpy\nbpy.context.scene.frame_set({int(frame)})")
                    preview = _unwrap(await client.render(
                        filepath=still,
                        engine=engine,
                        samples=min(int(samples), 16),
                        resolution_x=int(resolution_x),
                        resolution_y=int(resolution_y),
                        timeout=300.0,
                    ))
                    if not preview.get("success"):
                        continue
                if os.path.exists(still) and os.path.getsize(still) <= _MAX_INLINE_IMAGE_BYTES:
                    content.append(f"Frame {frame}:")
                    content.append(Image(path=still))
                    _LAST_RENDER["path"] = still
            except Exception:
                continue  # Previews are best-effort; the video itself succeeded.

        if orig_frame is not None:
            try:
                await client.execute(
                    f"import bpy\nbpy.context.scene.frame_set({orig_frame})"
                )
            except Exception:
                pass

        if len(content) == 1:
            content[0] += "\n(preview stills could not be generated)"

    return content


@mcp.tool(annotations=_CAPTURE)
async def blender_save(filepath: Optional[str] = None, copy: bool = False) -> str:
    """
    Save the current .blend file. Do this after substantial scene work -
    nothing else persists the session.

    Args:
        filepath: Where to save (a .blend path). Omit to save in place
                  (fails with guidance if the session was never saved).
        copy: Save a snapshot copy without retargeting the open session

    Returns:
        Confirmation with the saved path and size
    """
    client = get_blender()
    kwargs = {"copy": bool(copy)}
    if filepath:
        kwargs["filepath"] = filepath

    result = _unwrap(await client.call("save_file", **kwargs))
    _require_success(result, "Save")

    size_kb = result.get("file_size", 0) / 1024
    label = "Saved a copy to" if copy else "Saved to"
    return f"{label}: {result.get('filepath')} ({size_kb:.1f} KB)"


# =============================================================================
# Camera Tools
# =============================================================================


@mcp.tool(annotations=_IDEMPOTENT_WRITE)
async def blender_frame_camera(
    targets: Optional[list] = None,
    camera: Optional[str] = None,
    azimuth_deg: float = 45.0,
    elevation_deg: float = 20.0,
    margin: float = 1.15,
    distance: Optional[float] = None,
    lens: Optional[float] = None,
) -> str:
    """
    Position and aim a camera so the target objects fill the frame.

    Handles all the vector math: bounding-sphere fit, orbit angles, look-at
    rotation, and clip range. Creates a camera if the scene has none, and
    makes it the active scene camera.

    Args:
        targets: Object names to frame (default: all visible geometry)
        camera: Camera object name (default: scene camera)
        azimuth_deg: Horizontal orbit angle in degrees (0 = looking from +X)
        elevation_deg: Vertical angle in degrees above the subject
        margin: Framing margin; 1.0 = subject touches the frame edges
        distance: Explicit camera distance, overriding the automatic fit
        lens: Focal length in mm to set before fitting (e.g. 85 for portraits)

    Returns:
        Camera name, distance, and framed targets
    """
    client = get_blender()

    kwargs = {
        "azimuth_deg": float(azimuth_deg),
        "elevation_deg": float(elevation_deg),
        "margin": float(margin),
    }
    if targets:
        kwargs["targets"] = [str(t) for t in targets]
    if camera:
        kwargs["camera"] = camera
    if distance is not None:
        kwargs["distance"] = float(distance)
    if lens is not None:
        kwargs["lens"] = float(lens)

    result = _unwrap(await client.call("frame_camera", **kwargs))
    _require_success(result, "Camera framing")

    framed = ", ".join(result.get("targets", []))
    dist = float(result.get("distance") or 0.0)
    return (
        f"Camera '{result.get('camera')}' framed [{framed}] from "
        f"{dist:.2f}m (azimuth {azimuth_deg} deg, elevation {elevation_deg} deg). "
        "Take a blender_screenshot or a draft blender_render to verify the framing."
    )


# =============================================================================
# Import / Export Tools
# =============================================================================


@mcp.tool(annotations=_ADDITIVE)
async def blender_import_model(filepath: str, format: Optional[str] = None) -> ImportResult:
    """
    Import a 3D model file into the scene.

    Supported formats: obj, stl, ply, fbx, gltf, glb, usd/usda/usdc/usdz,
    dae (Collada), abc (Alembic). Format is inferred from the extension.

    Args:
        filepath: Path to the model file on this machine
        format: Optional explicit format when the extension is misleading

    Returns:
        The names of the objects added to the scene
    """
    expanded = os.path.abspath(os.path.expanduser(filepath))
    if not os.path.isfile(expanded):
        raise ToolError(f"File not found: {expanded}")

    client = get_blender()
    kwargs = {"filepath": expanded}
    if format:
        kwargs["format"] = format

    result = _unwrap(await client.call("import_model", timeout=300.0, **kwargs))
    _require_success(result, "Import")

    return {
        "filepath": result.get("filepath", expanded),
        "format": str(result.get("format", "")),
        "objects_added": [str(n) for n in result.get("objects_added", [])],
    }


@mcp.tool(annotations=_CAPTURE)
async def blender_export(
    filepath: str,
    format: Optional[str] = None,
    objects: Optional[list] = None,
) -> str:
    """
    Export the scene (or specific objects) to a 3D model file.

    Supported formats: obj, stl (3D printing), ply, fbx, gltf, glb (web/AR),
    usd/usda/usdc, dae, abc. Format comes from the file extension.

    Args:
        filepath: Output path; the extension selects the format (e.g. part.stl)
        format: Optional explicit format overriding the extension
        objects: Object names to export (whole scene when omitted)

    Returns:
        Export confirmation with path, object count and file size
    """
    client = get_blender()
    kwargs = {"filepath": os.path.abspath(os.path.expanduser(filepath))}
    if format:
        kwargs["format"] = format
    if objects:
        kwargs["objects"] = [str(o) for o in objects]

    result = _unwrap(await client.call("export_model", timeout=300.0, **kwargs))
    _require_success(result, "Export")

    size_kb = result.get("file_size", 0) / 1024
    return (
        f"Exported {result.get('object_count')} object(s) to "
        f"{result.get('filepath')} ({result.get('format')}, {size_kb:.1f} KB)"
    )


# =============================================================================
# Material Tools
# =============================================================================


@mcp.tool(annotations=_ADDITIVE)
async def blender_create_material(
    name: str,
    color: Optional[list] = None,
    metallic: float = 0.0,
    roughness: float = 0.5,
    apply_to: Optional[str] = None,
) -> str:
    """
    Create a PBR material and optionally apply it to an object.

    Args:
        name: Name for the new material
        color: RGBA color as [r, g, b, a] with values 0-1 (default: [0.8, 0.8, 0.8, 1])
        metallic: Metallic value 0-1 (0 = dielectric, 1 = metal)
        roughness: Roughness value 0-1 (0 = smooth/glossy, 1 = rough/matte)
        apply_to: Optional object name to apply the material to

    Returns:
        Result message
    """
    color = [float(c) for c in (color or [0.8, 0.8, 0.8, 1.0])]
    if len(color) == 3:
        color.append(1.0)
    if len(color) != 4:
        raise ToolError("color must be [r, g, b] or [r, g, b, a] with values 0-1")

    code = f'''
import bpy

mat = bpy.data.materials.new({name!r})
mat.use_nodes = True
nodes = mat.node_tree.nodes
bsdf = nodes.get("Principled BSDF")
if bsdf:
    bsdf.inputs["Base Color"].default_value = {color!r}
    bsdf.inputs["Metallic"].default_value = {float(metallic)!r}
    bsdf.inputs["Roughness"].default_value = {float(roughness)!r}

__result__ = "Material " + repr(mat.name) + " created"
'''

    if apply_to:
        code += f'''
obj = bpy.data.objects.get({apply_to!r})
if obj and hasattr(obj.data, 'materials'):
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    __result__ = "Material " + repr(mat.name) + " created and applied to " + {apply_to!r}
'''

    client = get_blender()
    result = _unwrap(await client.execute(code))

    if result.get("error"):
        raise ToolError(f"Material creation failed: {result['error']}")
    return result.get("result", "Material operation completed")


# =============================================================================
# Animation Tools
# =============================================================================


_INTERPOLATION_MODES = (
    "CONSTANT", "LINEAR", "BEZIER", "SINE", "QUAD", "CUBIC", "QUART",
    "QUINT", "EXPO", "CIRC", "BACK", "BOUNCE", "ELASTIC",
)


@mcp.tool(annotations=_ADDITIVE)
async def blender_set_keyframe(
    object_name: str,
    frame: int,
    location: Optional[list] = None,
    rotation: Optional[list] = None,
    scale: Optional[list] = None,
    interpolation: str = "BEZIER",
) -> str:
    """
    Set a keyframe for an object at a specific frame.

    Args:
        object_name: Name of the object to animate
        frame: Frame number to set the keyframe at
        location: Position as [x, y, z] (optional)
        rotation: Rotation in radians as [x, y, z] (optional)
        scale: Scale as [x, y, z] (optional)
        interpolation: Easing for this keyframe - 'BEZIER' (default ease),
                       'LINEAR' (constant speed - use for loops/turntables),
                       'CONSTANT', or other Blender modes

    Returns:
        Result message
    """
    frame = int(frame)
    interpolation = interpolation.upper()
    if interpolation not in _INTERPOLATION_MODES:
        raise ToolError(f"interpolation must be one of {_INTERPOLATION_MODES}")

    code = f'''
import bpy

obj = bpy.data.objects.get({object_name!r})
if not obj:
    __result__ = {{"ok": False, "error": "Object " + {object_name!r} + " not found"}}
else:
    # keyframe_insert(frame=...) records at the target frame directly;
    # moving the user's playhead with frame_set is neither needed nor polite.
    keyframes_set = []
'''

    if location:
        code += f'''
    obj.location = {[float(v) for v in location]!r}
    obj.keyframe_insert(data_path="location", frame={frame})
    keyframes_set.append("location")
'''

    if rotation:
        code += f'''
    obj.rotation_euler = {[float(v) for v in rotation]!r}
    obj.keyframe_insert(data_path="rotation_euler", frame={frame})
    keyframes_set.append("rotation")
'''

    if scale:
        code += f'''
    obj.scale = {[float(v) for v in scale]!r}
    obj.keyframe_insert(data_path="scale", frame={frame})
    keyframes_set.append("scale")
'''

    code += f'''
    if keyframes_set and {interpolation!r} != "BEZIER":
        anim = obj.animation_data
        if anim and anim.action:
            for fc in anim.action.fcurves:
                for kp in fc.keyframe_points:
                    if int(round(kp.co.x)) == {frame}:
                        kp.interpolation = {interpolation!r}
    if keyframes_set:
        __result__ = {{"ok": True, "channels": keyframes_set}}
    else:
        __result__ = {{"ok": False, "error": "No properties specified for keyframe"}}
'''

    client = get_blender()
    result = _unwrap(await client.execute(code))

    if result.get("error"):
        raise ToolError(f"Keyframe failed: {result['error']}")
    payload = result.get("result")
    if not isinstance(payload, dict):
        raise ToolError(f"Keyframe returned unexpected result: {payload!r}")
    if not payload.get("ok"):
        raise ToolError(f"Keyframe failed: {payload.get('error', 'unknown error')}")
    channels = ", ".join(str(c) for c in payload.get("channels", []))
    return f"Keyframes set for {channels} at frame {frame} ({interpolation})"


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                      idempotent_hint=True, open_world_hint=False))
async def blender_set_frame_range(start: int, end: int) -> str:
    """
    Set the animation frame range.

    Args:
        start: Start frame
        end: End frame

    Returns:
        Result message
    """
    start, end = int(start), int(end)
    code = f'''
import bpy
bpy.context.scene.frame_start = {start}
bpy.context.scene.frame_end = {end}
__result__ = "Frame range set to {start} - {end}"
'''

    client = get_blender()
    result = _unwrap(await client.execute(code))

    if result.get("error"):
        raise ToolError(f"Setting frame range failed: {result['error']}")
    return result.get("result", "Frame range set")


# =============================================================================
# Modifier & Object Organization Tools
# =============================================================================

_MODIFIER_ACTIONS = ("add", "apply", "remove")


@mcp.tool(annotations=_DESTRUCTIVE)
async def blender_modifier(
    action: str,
    object_name: str,
    modifier_type: Optional[str] = None,
    modifier_name: Optional[str] = None,
    params: Optional[dict] = None,
) -> str:
    """
    Add, apply, or remove a modifier on an object.

    Modifiers are Blender's non-destructive editing stack: SUBSURF (smooth),
    BOOLEAN (cut/join), ARRAY (repeat), MIRROR, SOLIDIFY, BEVEL, DECIMATE,
    DISPLACE, WIREFRAME, and more.

    Args:
        action: 'add' (needs modifier_type), 'apply' or 'remove' (need modifier_name).
                'apply' bakes the modifier into the mesh permanently.
        object_name: Object to operate on
        modifier_type: Blender modifier type for 'add', e.g. 'SUBSURF', 'BOOLEAN'
        modifier_name: Modifier name for 'apply'/'remove' (see blender_get_object)
        params: Attribute values for 'add', e.g. {"levels": 2} for SUBSURF or
                {"operation": "DIFFERENCE", "object": "Cutter"} for BOOLEAN
                (object names are resolved automatically)

    Returns:
        Result message; for 'add', includes any parameters that failed to apply
    """
    if action not in _MODIFIER_ACTIONS:
        raise ToolError(f"action must be one of {_MODIFIER_ACTIONS}")

    client = get_blender()

    if action == "add":
        if not modifier_type:
            raise ToolError("action 'add' requires modifier_type")
        result = _unwrap(await client.call(
            "add_modifier",
            object_name=object_name,
            modifier_type=modifier_type,
            params=params or {},
        ))
        _require_success(result, "Adding modifier")
        message = (
            f"Added {result.get('type')} modifier '{result.get('modifier')}' "
            f"to '{result.get('object')}'"
        )
        if result.get("params_failed"):
            message += f"\nWARNING - parameters not applied: {result['params_failed']}"
        return message

    if not modifier_name:
        raise ToolError(f"action '{action}' requires modifier_name")
    method = "apply_modifier" if action == "apply" else "remove_modifier"
    result = _unwrap(await client.call(
        method, object_name=object_name, modifier_name=modifier_name
    ))
    _require_success(result, f"Modifier {action}")
    verb = "Applied (baked)" if action == "apply" else "Removed"
    return f"{verb} modifier '{modifier_name}' on '{object_name}'"


@mcp.tool(annotations=_ADDITIVE)
async def blender_duplicate(
    name: str,
    count: int = 1,
    offset: Optional[list] = None,
    linked: bool = False,
) -> DuplicateResult:
    """
    Duplicate an object N times with a cumulative offset - a one-call linear
    array (fences, dominoes, columns, stairs).

    Args:
        name: Source object name
        count: Number of copies (1-100)
        offset: Per-copy offset [x, y, z]; copy i sits at source + offset * i
        linked: Share mesh data with the source (lighter, edits affect all)

    Returns:
        Names of the created objects
    """
    client = get_blender()
    result = _unwrap(await client.call(
        "duplicate_object",
        name=name,
        count=int(count),
        offset=[float(v) for v in (offset or [0, 0, 0])],
        linked=bool(linked),
    ))
    _require_success(result, "Duplication")
    return {
        "source": str(result.get("source", name)),
        "created": [str(n) for n in result.get("created", [])],
    }


_ORGANIZE_ACTIONS = ("parent", "unparent", "move_to_collection")


@mcp.tool(annotations=_IDEMPOTENT_WRITE)
async def blender_organize(
    action: str,
    objects: list,
    parent: Optional[str] = None,
    collection: Optional[str] = None,
    keep_transform: bool = True,
    create: bool = True,
) -> str:
    """
    Organize objects: parenting and collection membership.

    Args:
        action: 'parent' (needs parent), 'unparent', or 'move_to_collection'
                (needs collection)
        objects: Names of the objects to organize
        parent: Parent object name for action 'parent'
        collection: Target collection for action 'move_to_collection'
        keep_transform: Preserve world positions when (un)parenting
        create: Create the collection if it does not exist

    Returns:
        Result message
    """
    if action not in _ORGANIZE_ACTIONS:
        raise ToolError(f"action must be one of {_ORGANIZE_ACTIONS}")
    if not objects:
        raise ToolError("objects must be a non-empty list of object names")

    client = get_blender()
    names = [str(o) for o in objects]

    if action == "move_to_collection":
        if not collection:
            raise ToolError("action 'move_to_collection' requires collection")
        result = _unwrap(await client.call(
            "move_to_collection", names=names, collection_name=collection, create=create
        ))
        _require_success(result, "Collection move")
        return f"Moved {len(result.get('moved', []))} object(s) into collection '{result.get('collection')}'"

    if action == "parent" and not parent:
        raise ToolError("action 'parent' requires parent")
    result = _unwrap(await client.call(
        "set_parent",
        child_names=names,
        parent_name=parent if action == "parent" else None,
        keep_transform=keep_transform,
    ))
    _require_success(result, "Parenting")
    if action == "parent":
        return f"Parented {len(result.get('changed', []))} object(s) to '{parent}'"
    return f"Cleared parent on {len(result.get('changed', []))} object(s)"


# =============================================================================
# Undo / Checkpoint Tools
# =============================================================================


@mcp.tool(annotations=_ADDITIVE)
async def blender_checkpoint(label: str = "Claude checkpoint") -> str:
    """
    Push an undo checkpoint. Call this BEFORE destructive edits or
    blender_execute so a bad result can be rolled back with blender_undo.

    Args:
        label: Name shown in Blender's undo history

    Returns:
        Confirmation message
    """
    client = get_blender()
    result = _unwrap(await client.call("checkpoint", label=label))
    _require_success(result, "Checkpoint")
    return f"Checkpoint '{label}' pushed. Roll back with blender_undo if needed."


@mcp.tool(annotations=_DESTRUCTIVE)
async def blender_undo(steps: int = 1, redo: bool = False) -> str:
    """
    Undo (or redo) recent changes in Blender.

    Args:
        steps: How many undo steps to take (1-50)
        redo: Redo instead of undo

    Returns:
        How many steps were actually performed
    """
    client = get_blender()
    method = "redo" if redo else "undo"
    result = _unwrap(await client.call(method, steps=int(steps)))
    _require_success(result, "Undo" if not redo else "Redo")
    performed = result.get("steps_performed", 0)
    return (
        f"{'Redid' if redo else 'Undid'} {performed} step(s). "
        "Verify the scene state with blender_get_scene."
    )


# =============================================================================
# LOCAL AI Generation Tools (No External APIs)
# =============================================================================

_PROCEDURAL_TYPES = ("rock", "tree", "terrain", "building")


@mcp.tool(annotations=_ADDITIVE)
async def ai_generate_procedural(
    object_type: str,
    size: float = 1.0,
    seed: Optional[int] = None,
) -> str:
    """
    Generate procedural 3D objects using Blender's built-in tools.
    No AI models or external APIs needed - works offline.

    Args:
        object_type: Type of procedural generation:
            - 'rock': Procedural rock/boulder with noise displacement
            - 'tree': Simple L-system style tree
            - 'terrain': Noise-based terrain/landscape
            - 'building': Simple procedural building
        size: Base size of the object
        seed: Random seed for reproducibility

    Returns:
        Result with created object name
    """
    if object_type not in _PROCEDURAL_TYPES:
        raise ToolError(f"object_type must be one of {_PROCEDURAL_TYPES}")
    seed = None if seed is None else int(seed)

    code = f'''
try:
    from claude_blender.ai_services.local_text_to_3d import ProceduralGenerator
    gen = ProceduralGenerator()
    result = gen.generate({object_type!r}, size={float(size)!r}, seed={seed!r})
    __result__ = result
except Exception as e:
    __result__ = {{"success": False, "error": str(e)}}
'''

    client = get_blender()
    result = _ai_payload(
        _unwrap(await client.execute(code, timeout=300.0)), "Procedural generation"
    )
    return f"Generated procedural {object_type}: '{result.get('object_name')}'"


@mcp.tool(annotations=_ADDITIVE)
async def ai_comfyui_generate(
    prompt: str,
    negative_prompt: str = "ugly, blurry, low quality",
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    checkpoint: Optional[str] = None,
) -> str:
    """
    Generate an image using local ComfyUI instance.
    Requires ComfyUI running locally at http://127.0.0.1:8188

    Args:
        prompt: Text description of the image
        negative_prompt: What to avoid in the image
        width: Image width
        height: Image height
        steps: Number of sampling steps
        checkpoint: Model checkpoint name (uses ComfyUI's default if not specified)

    Returns:
        Path to generated image

    Note:
        ComfyUI must be running locally. Start it with: python main.py
        Download models to ComfyUI/models/checkpoints/
    """
    code = f'''
try:
    from claude_blender.ai_services.comfyui_bridge import get_comfyui

    comfy = get_comfyui()

    if not comfy.is_available():
        __result__ = {{
            "success": False,
            "error": "ComfyUI not running. Start ComfyUI at http://127.0.0.1:8188"
        }}
    else:
        result = comfy.generate(
            prompt={prompt!r},
            negative_prompt={negative_prompt!r},
            width={int(width)},
            height={int(height)},
            steps={int(steps)},
            checkpoint={checkpoint!r}
        )
        __result__ = result

except Exception as e:
    __result__ = {{"success": False, "error": str(e)}}
'''

    client = get_blender()
    result = _ai_payload(
        _unwrap(await client.execute(code, timeout=900.0)), "ComfyUI generation"
    )
    images = result.get("images", [])
    return f"Generated image with ComfyUI\nSaved to: {', '.join(images)}"


@mcp.tool(annotations=_ADDITIVE)
async def ai_local_text_to_3d(
    prompt: str,
    provider: str = "shap_e",
) -> str:
    """
    Generate a 3D model from text using local AI models.
    Runs entirely on your machine - no API calls.

    Args:
        prompt: Description of the 3D model to generate
        provider: Local model to use:
            - 'shap_e': OpenAI's Shap-E model (requires torch, diffusers)
            - 'procedural': Procedural generation (no dependencies)

    Returns:
        Result with model path or created object

    Requirements:
        For shap_e: pip install torch diffusers transformers trimesh
        For procedural: No extra dependencies
    """
    if provider not in ("shap_e", "procedural"):
        raise ToolError("provider must be 'shap_e' or 'procedural'")

    if provider == "procedural":
        # Map prompt to procedural type
        code = f'''
try:
    prompt_lower = {prompt!r}.lower()
    if any(w in prompt_lower for w in ["rock", "stone", "boulder"]):
        obj_type = "rock"
    elif any(w in prompt_lower for w in ["tree", "plant", "forest"]):
        obj_type = "tree"
    elif any(w in prompt_lower for w in ["terrain", "land", "ground", "mountain"]):
        obj_type = "terrain"
    elif any(w in prompt_lower for w in ["building", "house", "tower"]):
        obj_type = "building"
    else:
        obj_type = "rock"  # Default

    from claude_blender.ai_services.local_text_to_3d import ProceduralGenerator
    gen = ProceduralGenerator()
    result = gen.generate(obj_type)
    __result__ = result
except Exception as e:
    __result__ = {{"success": False, "error": str(e)}}
'''
    else:
        code = f'''
try:
    from claude_blender.ai_services.local_text_to_3d import get_local_text_to_3d

    service = get_local_text_to_3d({provider!r})

    if not service.is_available():
        deps = service.check_dependencies()
        missing = [k for k, v in deps.items() if not v]
        __result__ = {{
            "success": False,
            "error": f"Missing dependencies: {{missing}}. Install with: pip install torch diffusers transformers trimesh"
        }}
    else:
        result = service.generate(prompt={prompt!r})

        if result.get("success") and result.get("filepath"):
            # Import to Blender
            import_result = service.import_to_blender(result["filepath"])
            result["imported"] = import_result.get("success", False)
            result["objects"] = import_result.get("imported_objects", [])

        __result__ = result

except Exception as e:
    __result__ = {{"success": False, "error": str(e)}}
'''

    client = get_blender()
    result = _ai_payload(
        _unwrap(await client.execute(code, timeout=1800.0)), "Text-to-3D generation"
    )
    if result.get("object_name"):
        return f"Generated procedural object: '{result.get('object_name')}'"
    objects = result.get("objects", [])
    return (
        f"Generated 3D model from: '{prompt}'\n"
        f"File: {result.get('filepath')}\n"
        f"Imported: {', '.join(objects) if objects else 'No'}"
    )


@mcp.tool(annotations=_ADDITIVE)
async def ai_local_image_to_3d(
    image_path: str,
    provider: str = "depth2mesh",
) -> str:
    """
    Convert an image to 3D using local AI models.
    Runs entirely on your machine - no API calls.

    Args:
        image_path: Path to the input image
        provider: Local model to use:
            - 'triposr': TripoSR model (requires torch, transformers)
            - 'depth2mesh': Depth estimation to mesh (lighter weight)

    Returns:
        Result with model path

    Requirements:
        For triposr: pip install torch transformers trimesh rembg
        For depth2mesh: pip install torch transformers
    """
    if provider not in ("triposr", "depth2mesh"):
        raise ToolError("provider must be 'triposr' or 'depth2mesh'")
    if not os.path.exists(image_path):
        raise ToolError(f"Image not found: {image_path}")

    code = f'''
try:
    from claude_blender.ai_services.local_image_to_3d import get_local_image_to_3d

    service = get_local_image_to_3d({provider!r})

    if not service.is_available():
        deps = service.check_dependencies()
        missing = [k for k, v in deps.items() if not v]
        __result__ = {{
            "success": False,
            "error": f"Missing dependencies: {{missing}}. Install with: pip install torch transformers trimesh"
        }}
    else:
        result = service.generate(image_path={image_path!r})

        if result.get("success") and result.get("filepath"):
            import_result = service.import_to_blender(result["filepath"])
            result["imported"] = import_result.get("success", False)
            result["objects"] = import_result.get("imported_objects", [])

        __result__ = result

except Exception as e:
    __result__ = {{"success": False, "error": str(e)}}
'''

    client = get_blender()
    result = _ai_payload(
        _unwrap(await client.execute(code, timeout=1800.0)), "Image-to-3D conversion"
    )
    objects = result.get("objects", [])
    return (
        f"Converted image to 3D\nSource: {image_path}\n"
        f"File: {result.get('filepath')}\n"
        f"Imported: {', '.join(objects) if objects else 'No'}"
    )


@mcp.tool(annotations=_READ_ONLY)
async def ai_check_local_services() -> str:
    """
    Check which local AI services are available.
    Shows installed dependencies and running services.

    Returns:
        Status of all local AI services
    """
    client = get_blender()

    code = '''
results = {}

# Check procedural (always available)
results["procedural"] = {"available": True, "note": "No dependencies needed"}

# Check Shap-E
try:
    import torch
    import diffusers
    results["shap_e"] = {"available": True, "note": "Ready to use"}
except ImportError as e:
    results["shap_e"] = {"available": False, "note": f"Install: pip install torch diffusers transformers trimesh"}

# Check TripoSR
try:
    import torch
    import transformers
    results["triposr"] = {"available": True, "note": "Ready to use"}
except ImportError:
    results["triposr"] = {"available": False, "note": "Install: pip install torch transformers trimesh rembg"}

# Check Depth2Mesh
try:
    import torch
    import transformers
    results["depth2mesh"] = {"available": True, "note": "Ready to use"}
except ImportError:
    results["depth2mesh"] = {"available": False, "note": "Install: pip install torch transformers"}

# Check ComfyUI
try:
    from claude_blender.ai_services.comfyui_bridge import get_comfyui
    comfy = get_comfyui()
    if comfy.is_available():
        results["comfyui"] = {"available": True, "note": "Running at localhost:8188"}
    else:
        results["comfyui"] = {"available": False, "note": "Not running. Start ComfyUI first."}
except Exception as e:
    results["comfyui"] = {"available": False, "note": f"Error: {e}"}

__result__ = results
'''

    response = _unwrap(await client.execute(code, timeout=120.0))
    if response.get("error"):
        raise ToolError(f"Service check failed: {response['error']}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise ToolError(f"Service check returned an unexpected result: {result!r}")

    lines = ["Local AI Services Status:", "=" * 40]

    for service, info in result.items():
        status = "AVAILABLE" if info.get("available") else "NOT AVAILABLE"
        lines.append(f"\n{service}:")
        lines.append(f"  Status: {status}")
        lines.append(f"  Note: {info.get('note', '')}")

    lines.append("\n" + "=" * 40)
    lines.append("All AI runs locally - no external API calls.")

    return "\n".join(lines)


# =============================================================================
# Resources
# =============================================================================


@mcp.resource(
    "blender://scene",
    title="Blender Scene",
    description="Live snapshot of the current Blender scene graph (detailed).",
    mime_type="application/json",
)
async def scene_resource() -> str:
    """Detailed scene state as JSON, for cheap inspection without a tool call."""
    client = get_blender()
    response = await client.get_scene("detailed")
    if "error" in response:
        raise ResourceError(response["error"].get("message", "Blender not reachable"))
    return json.dumps(response.get("result", {}), indent=2, default=str)


@mcp.resource(
    "blender://object/{name}",
    title="Blender Object",
    description="Full details of a single object: transform, mesh stats, "
                "materials, modifiers, collections.",
    mime_type="application/json",
)
async def object_resource(name: str) -> str:
    """Single-object state as JSON."""
    client = get_blender()
    response = await client.get_object(name)
    if "error" in response:
        raise ResourceError(response["error"].get("message", "Blender not reachable"))
    result = response.get("result", {})
    if isinstance(result, dict) and result.get("error"):
        raise ResourceError(str(result["error"]))
    return json.dumps(result, indent=2, default=str)


@mcp.resource(
    "blender://render/latest",
    title="Latest Render",
    description="The most recent render or screenshot from this session, as PNG.",
    mime_type="image/png",
)
async def latest_render_resource() -> bytes:
    """Raw PNG bytes of the last image this server produced."""
    path = _LAST_RENDER["path"]
    if not path or not os.path.exists(path):
        raise ResourceError(
            "No render yet in this session. Call blender_render or "
            "blender_screenshot first."
        )
    with open(path, "rb") as f:
        return f.read()


# =============================================================================
# Prompts
# =============================================================================


@mcp.prompt(title="Studio lighting setup")
def studio_lighting(subject: str = "the active object") -> str:
    """Guide a classic three-point lighting setup around a subject."""
    return (
        f"Set up three-point studio lighting in Blender around {subject}:\n"
        "1. Inspect the scene (blender_get_scene) and find the subject's location and size.\n"
        "2. Key: blender_add_object type 'area' at ~45 degrees front-left above the "
        "subject, with energy ~800, a warm color, and size about the subject's "
        "largest dimension (bigger = softer shadows).\n"
        "3. Fill: another 'area' front-right, energy about half the key's, larger size.\n"
        "4. Rim: a light behind and above with a cool color, to separate the subject "
        "from the background.\n"
        "5. blender_frame_camera on the subject, take a blender_screenshot, and adjust "
        "light energy/positions based on what you see."
    )


@mcp.prompt(title="Turntable animation")
def turntable_animation(object_name: str, seconds: int = 4, fps: int = 24) -> str:
    """Guide a 360-degree turntable animation of an object."""
    frames = max(2, int(seconds) * int(fps))
    return (
        f"Create a {seconds}s turntable animation of '{object_name}':\n"
        f"1. Verify the object exists with blender_get_object.\n"
        f"2. Set the frame range to 1-{frames} with blender_set_frame_range.\n"
        f"3. Add an empty at the object's location, aim the camera with "
        "blender_frame_camera, then parent the camera to the empty "
        "(blender_organize action='parent').\n"
        f"4. Keyframe the empty's Z rotation with interpolation='LINEAR': "
        f"0 at frame 1, 2*pi at frame {frames} (blender_set_keyframe).\n"
        "5. Take a screenshot at a mid frame to verify framing, then render "
        "with blender_render_animation."
    )


# =============================================================================
# Entry Point
# =============================================================================


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
