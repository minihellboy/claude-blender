# SPDX-License-Identifier: MIT
"""
Claude Blender MCP Server

Model Context Protocol server for Claude Code integration with Blender.
Provides tools for scene manipulation, object creation, rendering, and LOCAL AI generation.

All AI runs locally - no external API calls.
"""

import asyncio
import os
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .blender_client import get_client, BlenderClient


# Create the MCP server
mcp = FastMCP(
    "blender",
    description="Control Blender 3D through natural language. Create, modify, and render 3D scenes. AI generation runs locally."
)


def get_blender() -> BlenderClient:
    """Get the Blender client instance."""
    host = os.environ.get("BLENDER_HOST", "127.0.0.1")
    port = int(os.environ.get("BLENDER_PORT", "9876"))
    return get_client(host, port)


# =============================================================================
# Connection Tools
# =============================================================================

@mcp.tool()
async def blender_ping() -> str:
    """
    Check if Blender is running and reachable.

    Returns:
        Connection status message
    """
    client = get_blender()
    if await client.ping():
        return "Blender is connected and responding"
    return "Cannot connect to Blender. Make sure Blender is running with the Claude addon enabled and server started."


@mcp.tool()
async def blender_version() -> str:
    """
    Get Blender and addon version information.

    Returns:
        Version information as formatted string
    """
    client = get_blender()
    response = await client.call("version")
    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {})
    return f"Blender {result.get('blender_version', 'unknown')}, Addon v{result.get('addon_version', 'unknown')}"


# =============================================================================
# Scene Tools
# =============================================================================

@mcp.tool()
async def blender_get_scene(detail_level: str = "basic") -> str:
    """
    Get information about the current Blender scene.

    Args:
        detail_level: Level of detail - 'minimal', 'basic', 'detailed', or 'full'

    Returns:
        Scene information as formatted text
    """
    client = get_blender()
    response = await client.get_scene(detail_level)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {})

    lines = [
        f"Scene: {result.get('name', 'Unknown')}",
        f"Objects: {result.get('object_count', 0)}",
        f"Active Object: {result.get('active_object', 'None')}",
    ]

    if "objects" in result:
        lines.append("\nObjects in scene:")
        for obj in result["objects"]:
            if isinstance(obj, dict):
                lines.append(f"  - {obj.get('name', 'Unknown')} ({obj.get('type', 'Unknown')})")
            else:
                lines.append(f"  - {obj}")

    return "\n".join(lines)


@mcp.tool()
async def blender_get_object(name: str) -> str:
    """
    Get detailed information about a specific object.

    Args:
        name: Name of the object to inspect

    Returns:
        Object information as formatted text
    """
    client = get_blender()
    response = await client.get_object(name)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {})

    if "error" in result:
        return f"Error: {result['error']}"

    lines = [
        f"Object: {result.get('name', 'Unknown')}",
        f"Type: {result.get('type', 'Unknown')}",
        f"Location: {result.get('location', [0, 0, 0])}",
        f"Rotation: {result.get('rotation', [0, 0, 0])}",
        f"Scale: {result.get('scale', [1, 1, 1])}",
        f"Visible: {result.get('visible', True)}",
    ]

    if "dimensions" in result:
        lines.append(f"Dimensions: {result['dimensions']}")

    if "materials" in result and result["materials"]:
        lines.append(f"Materials: {', '.join(result['materials'])}")

    return "\n".join(lines)


# =============================================================================
# Object Creation Tools
# =============================================================================

@mcp.tool()
async def blender_add_object(
    object_type: str,
    name: Optional[str] = None,
    location: Optional[list] = None,
    rotation: Optional[list] = None,
    scale: Optional[list] = None
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

    response = await client.call("add_object", **kwargs)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {})
    if result.get("success"):
        return f"Created {object_type}: '{result.get('object_name', name or object_type)}'"
    else:
        return f"Failed to create object: {result.get('error', 'Unknown error')}"


@mcp.tool()
async def blender_modify_object(
    name: str,
    location: Optional[list] = None,
    rotation: Optional[list] = None,
    scale: Optional[list] = None,
    visible: Optional[bool] = None
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

    response = await client.modify_object(**kwargs)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {})
    if result.get("success"):
        return f"Modified object '{name}'"
    else:
        return f"Failed to modify object: {result.get('error', 'Unknown error')}"


@mcp.tool()
async def blender_delete_object(name: str) -> str:
    """
    Delete an object from the scene.

    Args:
        name: Name of the object to delete

    Returns:
        Result message
    """
    client = get_blender()
    response = await client.delete_object(name)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {})
    if result.get("success"):
        return f"Deleted object '{name}'"
    else:
        return f"Failed to delete object: {result.get('error', 'Unknown error')}"


# =============================================================================
# Code Execution Tools
# =============================================================================

@mcp.tool()
async def blender_execute(code: str) -> str:
    """
    Execute Python code in Blender's environment.

    This gives you full access to Blender's Python API (bpy).
    Use __result__ variable to return a value.

    Args:
        code: Python code to execute. Has access to bpy and all Blender modules.

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
    response = await client.execute(code)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {})

    lines = []
    if result.get("output"):
        lines.append(f"Output:\n{result['output']}")

    if result.get("result") is not None:
        lines.append(f"Result: {result['result']}")

    if result.get("error"):
        lines.append(f"Error: {result['error']}")

    if not lines:
        if result.get("success"):
            return "Code executed successfully"
        return "Execution completed with no output"

    return "\n".join(lines)


# =============================================================================
# Render & Screenshot Tools
# =============================================================================

@mcp.tool()
async def blender_screenshot(
    filepath: Optional[str] = None,
    width: int = 1920,
    height: int = 1080
) -> str:
    """
    Capture a screenshot of the 3D viewport.

    Args:
        filepath: Where to save the image (default: temp file)
        width: Image width in pixels
        height: Image height in pixels

    Returns:
        Path to the saved screenshot
    """
    client = get_blender()
    response = await client.screenshot(filepath=filepath, width=width, height=height)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {})
    if result.get("success"):
        return f"Screenshot saved to: {result.get('filepath', 'unknown')}"
    else:
        return f"Screenshot failed: {result.get('error', 'Unknown error')}"


@mcp.tool()
async def blender_render(
    filepath: Optional[str] = None,
    engine: str = "CYCLES",
    samples: int = 128,
    resolution_x: int = 1920,
    resolution_y: int = 1080
) -> str:
    """
    Render the current scene.

    Args:
        filepath: Where to save the render (default: temp file)
        engine: Render engine - 'CYCLES', 'BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'
        samples: Number of render samples (higher = better quality, slower)
        resolution_x: Output width in pixels
        resolution_y: Output height in pixels

    Returns:
        Path to the rendered image
    """
    client = get_blender()
    response = await client.render(
        filepath=filepath,
        engine=engine,
        samples=samples,
        resolution_x=resolution_x,
        resolution_y=resolution_y
    )

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {})
    if result.get("success"):
        return f"Render saved to: {result.get('filepath', 'unknown')}"
    else:
        return f"Render failed: {result.get('error', 'Unknown error')}"


# =============================================================================
# Material Tools
# =============================================================================

@mcp.tool()
async def blender_create_material(
    name: str,
    color: Optional[list] = None,
    metallic: float = 0.0,
    roughness: float = 0.5,
    apply_to: Optional[str] = None
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
    color = color or [0.8, 0.8, 0.8, 1.0]

    code = f'''
import bpy

mat = bpy.data.materials.new("{name}")
mat.use_nodes = True
nodes = mat.node_tree.nodes
bsdf = nodes.get("Principled BSDF")
if bsdf:
    bsdf.inputs["Base Color"].default_value = {color}
    bsdf.inputs["Metallic"].default_value = {metallic}
    bsdf.inputs["Roughness"].default_value = {roughness}

__result__ = "Material '{name}' created"
'''

    if apply_to:
        code += f'''
obj = bpy.data.objects.get("{apply_to}")
if obj and hasattr(obj.data, 'materials'):
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    __result__ = "Material '{name}' created and applied to '{apply_to}'"
'''

    client = get_blender()
    response = await client.execute(code)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {})
    return result.get("result", "Material operation completed")


# =============================================================================
# Animation Tools
# =============================================================================

@mcp.tool()
async def blender_set_keyframe(
    object_name: str,
    frame: int,
    location: Optional[list] = None,
    rotation: Optional[list] = None,
    scale: Optional[list] = None
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
    code = f'''
import bpy

obj = bpy.data.objects.get("{object_name}")
if not obj:
    __result__ = "Object '{object_name}' not found"
else:
    bpy.context.scene.frame_set({frame})
    keyframes_set = []
'''

    if location:
        code += f'''
    obj.location = {location}
    obj.keyframe_insert(data_path="location", frame={frame})
    keyframes_set.append("location")
'''

    if rotation:
        code += f'''
    obj.rotation_euler = {rotation}
    obj.keyframe_insert(data_path="rotation_euler", frame={frame})
    keyframes_set.append("rotation")
'''

    if scale:
        code += f'''
    obj.scale = {scale}
    obj.keyframe_insert(data_path="scale", frame={frame})
    keyframes_set.append("scale")
'''

    code += '''
    if keyframes_set:
        __result__ = f"Keyframes set for {', '.join(keyframes_set)} at frame {frame}"
    else:
        __result__ = "No properties specified for keyframe"
'''

    client = get_blender()
    response = await client.execute(code)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {})
    return result.get("result", "Keyframe operation completed")


@mcp.tool()
async def blender_set_frame_range(start: int, end: int) -> str:
    """
    Set the animation frame range.

    Args:
        start: Start frame
        end: End frame

    Returns:
        Result message
    """
    code = f'''
import bpy
bpy.context.scene.frame_start = {start}
bpy.context.scene.frame_end = {end}
__result__ = f"Frame range set to {start} - {end}"
'''

    client = get_blender()
    response = await client.execute(code)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {})
    return result.get("result", "Frame range set")


# =============================================================================
# LOCAL AI Generation Tools (No External APIs)
# =============================================================================

@mcp.tool()
async def ai_generate_procedural(
    object_type: str,
    size: float = 1.0,
    seed: Optional[int] = None
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
    client = get_blender()

    seed_code = f"random.seed({seed})" if seed else ""

    code = f'''
import bpy
import random
import time

{seed_code}

# Import procedural generator
try:
    from ai_services.local_text_to_3d import ProceduralGenerator
    gen = ProceduralGenerator()
    result = gen.generate("{object_type}", size={size}, seed={seed if seed else 'None'})
    __result__ = result
except Exception as e:
    __result__ = {{"success": False, "error": str(e)}}
'''

    response = await client.execute(code)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {}).get("result", {})

    if isinstance(result, dict):
        if result.get("success"):
            return f"Generated procedural {object_type}: '{result.get('object_name')}'"
        else:
            return f"Generation failed: {result.get('error', 'Unknown error')}"

    return f"Result: {result}"


@mcp.tool()
async def ai_comfyui_generate(
    prompt: str,
    negative_prompt: str = "ugly, blurry, low quality",
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    checkpoint: Optional[str] = None
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
    client = get_blender()

    code = f'''
import os
import tempfile

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
            prompt="""{prompt}""",
            negative_prompt="""{negative_prompt}""",
            width={width},
            height={height},
            steps={steps},
            checkpoint={f'"{checkpoint}"' if checkpoint else 'None'}
        )
        __result__ = result

except Exception as e:
    __result__ = {{"success": False, "error": str(e)}}
'''

    response = await client.execute(code)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {}).get("result", {})

    if isinstance(result, dict):
        if result.get("success"):
            images = result.get("images", [])
            return f"Generated image with ComfyUI\nSaved to: {', '.join(images)}"
        else:
            return f"Generation failed: {result.get('error', 'Unknown error')}"

    return f"Result: {result}"


@mcp.tool()
async def ai_local_text_to_3d(
    prompt: str,
    provider: str = "shap_e"
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
    client = get_blender()

    if provider == "procedural":
        # Map prompt to procedural type
        code = f'''
# Try to infer procedural type from prompt
prompt_lower = "{prompt}".lower()
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

    service = get_local_text_to_3d("{provider}")

    if not service.is_available():
        deps = service.check_dependencies()
        missing = [k for k, v in deps.items() if not v]
        __result__ = {{
            "success": False,
            "error": f"Missing dependencies: {{missing}}. Install with: pip install torch diffusers transformers trimesh"
        }}
    else:
        result = service.generate(prompt="{prompt}")

        if result.get("success") and result.get("filepath"):
            # Import to Blender
            import_result = service.import_to_blender(result["filepath"])
            result["imported"] = import_result.get("success", False)
            result["objects"] = import_result.get("imported_objects", [])

        __result__ = result

except Exception as e:
    __result__ = {{"success": False, "error": str(e)}}
'''

    response = await client.execute(code)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {}).get("result", {})

    if isinstance(result, dict):
        if result.get("success"):
            if result.get("object_name"):
                return f"Generated procedural object: '{result.get('object_name')}'"
            objects = result.get("objects", [])
            return f"Generated 3D model from: '{prompt}'\nFile: {result.get('filepath')}\nImported: {', '.join(objects) if objects else 'No'}"
        else:
            return f"Generation failed: {result.get('error', 'Unknown error')}"

    return f"Result: {result}"


@mcp.tool()
async def ai_local_image_to_3d(
    image_path: str,
    provider: str = "depth2mesh"
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
    import os as _os
    if not _os.path.exists(image_path):
        return f"Error: Image not found: {image_path}"

    client = get_blender()

    code = f'''
try:
    from ai_services.local_image_to_3d import get_local_image_to_3d

    service = get_local_image_to_3d("{provider}")

    if not service.is_available():
        deps = service.check_dependencies()
        missing = [k for k, v in deps.items() if not v]
        __result__ = {{
            "success": False,
            "error": f"Missing dependencies: {{missing}}. Install with: pip install torch transformers trimesh"
        }}
    else:
        result = service.generate(image_path="{image_path}")

        if result.get("success") and result.get("filepath"):
            import_result = service.import_to_blender(result["filepath"])
            result["imported"] = import_result.get("success", False)
            result["objects"] = import_result.get("imported_objects", [])

        __result__ = result

except Exception as e:
    __result__ = {{"success": False, "error": str(e)}}
'''

    response = await client.execute(code)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {}).get("result", {})

    if isinstance(result, dict):
        if result.get("success"):
            objects = result.get("objects", [])
            return f"Converted image to 3D\nSource: {image_path}\nFile: {result.get('filepath')}\nImported: {', '.join(objects) if objects else 'No'}"
        else:
            return f"Conversion failed: {result.get('error', 'Unknown error')}"

    return f"Result: {result}"


@mcp.tool()
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

    response = await client.execute(code)

    if "error" in response:
        return f"Error: {response['error'].get('message', 'Unknown error')}"

    result = response.get("result", {}).get("result", {})

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
# Entry Point
# =============================================================================

def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
