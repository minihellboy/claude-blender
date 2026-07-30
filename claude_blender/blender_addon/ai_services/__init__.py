# SPDX-License-Identifier: MIT
"""
Local AI Services for Claude Blender.

All AI runs locally - NO external API calls.

This module provides:
- Text-to-3D: Shap-E (local), Procedural generation
- Image-to-3D: TripoSR (local), Depth-to-Mesh
- Text-to-Image: ComfyUI bridge (local Stable Diffusion)

Requirements vary by service - see individual modules for pip install commands.
"""

from .base import (
    BaseLocalService,
    AIServiceError,
    ModelNotFoundError,
    InferenceError,
    ModelOutputMixin,
    TextureOutputMixin,
)

from .comfyui_bridge import (
    ComfyUIBridge,
    get_comfyui,
)

from .local_text_to_3d import (
    LocalShapE,
    ProceduralGenerator,
    get_local_text_to_3d,
)

from .local_image_to_3d import (
    LocalTripoSR,
    Depth2MeshService,
    get_local_image_to_3d,
)


__all__ = [
    # Base
    "BaseLocalService",
    "AIServiceError",
    "ModelNotFoundError",
    "InferenceError",
    "ModelOutputMixin",
    "TextureOutputMixin",

    # ComfyUI (local image generation)
    "ComfyUIBridge",
    "get_comfyui",

    # Text-to-3D (local)
    "LocalShapE",
    "ProceduralGenerator",
    "get_local_text_to_3d",

    # Image-to-3D (local)
    "LocalTripoSR",
    "Depth2MeshService",
    "get_local_image_to_3d",
]


def get_available_services() -> dict:
    """
    Get information about all available local AI services.

    Returns:
        Dict mapping service names to their info
    """
    return {
        "text_to_3d": {
            "providers": ["shap_e", "procedural"],
            "description": "Generate 3D models from text descriptions (runs locally)",
            "requirements": {
                "shap_e": "pip install torch diffusers transformers trimesh",
                "procedural": "No dependencies (uses Blender)",
            },
        },
        "image_to_3d": {
            "providers": ["triposr", "depth2mesh"],
            "description": "Convert images to 3D models (runs locally)",
            "requirements": {
                "triposr": "pip install torch transformers trimesh rembg",
                "depth2mesh": "pip install torch transformers",
            },
        },
        "text_to_image": {
            "providers": ["comfyui"],
            "description": "Generate images from text (requires local ComfyUI)",
            "requirements": {
                "comfyui": "Install ComfyUI separately, run on localhost:8188",
            },
        },
    }


def check_all_dependencies() -> dict:
    """
    Check which services are available based on installed packages.

    Returns:
        Dict mapping service names to availability status
    """
    results = {}

    # Check Shap-E
    try:
        import torch
        import diffusers
        results["shap_e"] = True
    except ImportError:
        results["shap_e"] = False

    # Check TripoSR
    try:
        import torch
        import transformers
        results["triposr"] = True
    except ImportError:
        results["triposr"] = False

    # Check ComfyUI
    comfy = get_comfyui()
    results["comfyui"] = comfy.is_available()

    # Procedural always available
    results["procedural"] = True

    # Depth2Mesh
    try:
        import torch
        import transformers
        results["depth2mesh"] = True
    except ImportError:
        results["depth2mesh"] = False

    return results
