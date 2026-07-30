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
from typing import Optional

from typing_extensions import NotRequired, TypedDict

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
        "- Call blender_ping first if a tool reports a connection problem.\n"
        "- Use blender_get_scene / blender_get_object (or the blender://scene "
        "resource) to inspect state before modifying it.\n"
        "- blender_execute runs arbitrary bpy Python for anything not covered by "
        "a dedicated tool.\n"
        "- blender_screenshot and blender_render return the actual image so you "
        "can verify results visually and iterate."
    ),
    version="0.2.0",
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

# Images above this size are referenced by path instead of inlined into the result.
_MAX_INLINE_IMAGE_BYTES = 4 * 1024 * 1024


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


class ObjectInfo(TypedDict):
    name: str
    type: str
    location: list[float]
    rotation: list[float]
    scale: list[float]
    visible: bool
    dimensions: NotRequired[list[float]]
    materials: NotRequired[list[str]]


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

    info: ObjectInfo = {
        "name": result.get("name", name),
        "type": result.get("type", "UNKNOWN"),
        "location": [float(v) for v in result.get("location", [0, 0, 0])],
        "rotation": [float(v) for v in result.get("rotation", [0, 0, 0])],
        "scale": [float(v) for v in result.get("scale", [1, 1, 1])],
        "visible": bool(result.get("visible", True)),
    }
    if "dimensions" in result:
        info["dimensions"] = [float(v) for v in result["dimensions"]]
    if result.get("materials"):
        info["materials"] = [str(m) for m in result["materials"]]
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
) -> str:
    """
    Modify an existing object's transform or visibility.

    Args:
        name: Name of the object to modify
        location: New position as [x, y, z]
        rotation: New rotation in radians as [x, y, z]
        scale: New scale as [x, y, z]
        visible: Set visibility (True/False)

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

    return _preview(f"Screenshot saved to: {path}", path)


@mcp.tool(annotations=_CAPTURE, structured_output=False)
async def blender_render(
    filepath: Optional[str] = None,
    engine: str = "CYCLES",
    samples: int = 128,
    resolution_x: int = 1920,
    resolution_y: int = 1080,
):
    """
    Render the current scene and return the image.

    Renders block until finished; high sample counts can take several minutes.

    Args:
        filepath: Where to save the render (default: temp file)
        engine: Render engine - 'CYCLES', 'BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'
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

    return _preview(f"Render saved to: {path}", path)


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


@mcp.tool(annotations=_ADDITIVE)
async def blender_set_keyframe(
    object_name: str,
    frame: int,
    location: Optional[list] = None,
    rotation: Optional[list] = None,
    scale: Optional[list] = None,
) -> str:
    """
    Set a keyframe for an object at a specific frame.

    Args:
        object_name: Name of the object to animate
        frame: Frame number to set the keyframe at
        location: Position as [x, y, z] (optional)
        rotation: Rotation in radians as [x, y, z] (optional)
        scale: Scale as [x, y, z] (optional)

    Returns:
        Result message
    """
    frame = int(frame)

    code = f'''
import bpy

obj = bpy.data.objects.get({object_name!r})
if not obj:
    __result__ = "Object " + {object_name!r} + " not found"
else:
    bpy.context.scene.frame_set({frame})
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
    if keyframes_set:
        __result__ = "Keyframes set for " + ", ".join(keyframes_set) + " at frame {frame}"
    else:
        __result__ = "No properties specified for keyframe"
'''

    client = get_blender()
    result = _unwrap(await client.execute(code))

    if result.get("error"):
        raise ToolError(f"Keyframe failed: {result['error']}")
    return result.get("result", "Keyframe operation completed")


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
    from ai_services.local_text_to_3d import ProceduralGenerator
    gen = ProceduralGenerator()
    result = gen.generate({object_type!r}, size={float(size)!r}, seed={seed!r})
    __result__ = result
except Exception as e:
    __result__ = {{"success": False, "error": str(e)}}
'''

    client = get_blender()
    result = _unwrap(await client.execute(code, timeout=300.0)).get("result", {})

    if isinstance(result, dict):
        if result.get("success"):
            return f"Generated procedural {object_type}: '{result.get('object_name')}'"
        raise ToolError(f"Generation failed: {result.get('error', 'Unknown error')}")

    return f"Result: {result}"


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
    from ai_services.comfyui_bridge import get_comfyui

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
    result = _unwrap(await client.execute(code, timeout=900.0)).get("result", {})

    if isinstance(result, dict):
        if result.get("success"):
            images = result.get("images", [])
            return f"Generated image with ComfyUI\nSaved to: {', '.join(images)}"
        raise ToolError(f"Generation failed: {result.get('error', 'Unknown error')}")

    return f"Result: {result}"


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

from ai_services.local_text_to_3d import ProceduralGenerator
gen = ProceduralGenerator()
result = gen.generate(obj_type)
__result__ = result
'''
    else:
        code = f'''
try:
    from ai_services.local_text_to_3d import get_local_text_to_3d

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
    result = _unwrap(await client.execute(code, timeout=1800.0)).get("result", {})

    if isinstance(result, dict):
        if result.get("success"):
            if result.get("object_name"):
                return f"Generated procedural object: '{result.get('object_name')}'"
            objects = result.get("objects", [])
            return (
                f"Generated 3D model from: '{prompt}'\n"
                f"File: {result.get('filepath')}\n"
                f"Imported: {', '.join(objects) if objects else 'No'}"
            )
        raise ToolError(f"Generation failed: {result.get('error', 'Unknown error')}")

    return f"Result: {result}"


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
    from ai_services.local_image_to_3d import get_local_image_to_3d

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
    result = _unwrap(await client.execute(code, timeout=1800.0)).get("result", {})

    if isinstance(result, dict):
        if result.get("success"):
            objects = result.get("objects", [])
            return (
                f"Converted image to 3D\nSource: {image_path}\n"
                f"File: {result.get('filepath')}\n"
                f"Imported: {', '.join(objects) if objects else 'No'}"
            )
        raise ToolError(f"Conversion failed: {result.get('error', 'Unknown error')}")

    return f"Result: {result}"


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
    from ai_services.comfyui_bridge import get_comfyui
    comfy = get_comfyui()
    if comfy.is_available():
        results["comfyui"] = {"available": True, "note": "Running at localhost:8188"}
    else:
        results["comfyui"] = {"available": False, "note": "Not running. Start ComfyUI first."}
except Exception as e:
    results["comfyui"] = {"available": False, "note": f"Error: {e}"}

__result__ = results
'''

    result = _unwrap(await client.execute(code, timeout=120.0)).get("result", {})

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


# =============================================================================
# Prompts
# =============================================================================


@mcp.prompt(title="Studio lighting setup")
def studio_lighting(subject: str = "the active object") -> str:
    """Guide a classic three-point lighting setup around a subject."""
    return (
        f"Set up three-point studio lighting in Blender around {subject}:\n"
        "1. Inspect the scene (blender_get_scene) and find the subject's location and size.\n"
        "2. Add a large AREA key light at ~45 degrees front-left, above the subject.\n"
        "3. Add a softer fill light front-right at roughly half the key's power.\n"
        "4. Add a rim/back light behind and above to separate the subject from the background.\n"
        "5. Add a camera framing the subject, take a blender_screenshot, and adjust "
        "light power/positions based on what you see."
    )


@mcp.prompt(title="Turntable animation")
def turntable_animation(object_name: str, seconds: int = 4, fps: int = 24) -> str:
    """Guide a 360-degree turntable animation of an object."""
    frames = max(2, int(seconds) * int(fps))
    return (
        f"Create a {seconds}s turntable animation of '{object_name}':\n"
        f"1. Verify the object exists with blender_get_object.\n"
        f"2. Set the frame range to 1-{frames} with blender_set_frame_range.\n"
        f"3. Add an empty at the object's location, parent a camera to it aimed at the object.\n"
        f"4. Keyframe the empty's Z rotation: 0 at frame 1, 2*pi at frame {frames} "
        "(blender_set_keyframe or blender_execute), and set linear interpolation.\n"
        "5. Take a screenshot at a mid frame to verify framing before rendering."
    )


# =============================================================================
# Entry Point
# =============================================================================


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
