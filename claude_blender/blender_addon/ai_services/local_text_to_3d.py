# SPDX-License-Identifier: MIT
"""
Local Text-to-3D services.

Runs 3D generation models locally using PyTorch.
No external API calls.

Supported models:
    - Shap-E: OpenAI's text-to-3D model
    - Point-E: OpenAI's point cloud to 3D

Requirements:
    pip install torch torchvision
    pip install transformers diffusers
    pip install trimesh pygltflib
"""

import os
import time
import tempfile
from typing import Any, Dict, Optional, List
from .base import BaseLocalService, ModelOutputMixin, AIServiceError


class LocalShapE(BaseLocalService, ModelOutputMixin):
    """
    Local Shap-E text-to-3D service.

    Shap-E is OpenAI's model for generating 3D objects from text.
    Generates neural radiance fields which are converted to meshes.

    Model: openai/shap-e (Hugging Face)
    """

    def __init__(self, device: Optional[str] = None):
        super().__init__()
        self.device = device
        self._pipe = None

    @property
    def service_name(self) -> str:
        return "shap_e"

    @property
    def required_packages(self) -> list:
        return ["torch", "diffusers", "transformers", "trimesh"]

    def _get_device(self) -> str:
        if self.device:
            return self.device
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            elif torch.backends.mps.is_available():
                return "mps"
            return "cpu"
        except:
            return "cpu"

    def load_model(self) -> bool:
        """Load Shap-E pipeline."""
        if self._pipe is not None:
            return True

        try:
            import torch
            from diffusers import ShapEPipeline

            device = self._get_device()
            print(f"[Shap-E] Loading model on {device}...")

            self._pipe = ShapEPipeline.from_pretrained(
                "openai/shap-e",
                torch_dtype=torch.float16 if device != "cpu" else torch.float32
            ).to(device)

            self._model_loaded = True
            print("[Shap-E] Model loaded successfully")
            return True

        except Exception as e:
            print(f"[Shap-E] Failed to load model: {e}")
            return False

    def generate(
        self,
        prompt: str,
        guidance_scale: float = 15.0,
        num_inference_steps: int = 64,
        output_format: str = "glb",
        frame_size: int = 256
    ) -> Dict[str, Any]:
        """
        Generate a 3D model from text.

        Args:
            prompt: Text description of the 3D model
            guidance_scale: How closely to follow the prompt
            num_inference_steps: Number of denoising steps
            output_format: Output format (glb, obj, ply)
            frame_size: Resolution for NeRF rendering

        Returns:
            Dict with model path
        """
        if not self.load_model():
            return {
                "success": False,
                "error": "Failed to load Shap-E. Install: pip install diffusers transformers torch"
            }

        try:
            import torch

            print(f"[Shap-E] Generating: {prompt}")

            # Generate
            images = self._pipe(
                prompt,
                guidance_scale=guidance_scale,
                num_inference_steps=num_inference_steps,
                frame_size=frame_size,
                output_type="mesh"
            ).images

            if not images:
                return {"success": False, "error": "No mesh generated"}

            mesh = images[0]

            # Save mesh
            output_path = os.path.join(
                self._temp_dir,
                f"shape_{int(time.time())}.{output_format}"
            )

            # Export using trimesh
            mesh.export(output_path, file_type=output_format)

            return {
                "success": True,
                "filepath": output_path,
                "prompt": prompt,
                "format": output_format
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


class LocalPointE(BaseLocalService, ModelOutputMixin):
    """
    Local Point-E text-to-3D service.

    Point-E generates point clouds from text, then converts to mesh.
    Faster than Shap-E but lower quality.

    Model: openai/point-e (Hugging Face)
    """

    def __init__(self, device: Optional[str] = None):
        super().__init__()
        self.device = device
        self._pipe = None

    @property
    def service_name(self) -> str:
        return "point_e"

    @property
    def required_packages(self) -> list:
        return ["torch", "diffusers", "transformers"]

    def _get_device(self) -> str:
        if self.device:
            return self.device
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            elif torch.backends.mps.is_available():
                return "mps"
            return "cpu"
        except:
            return "cpu"

    def load_model(self) -> bool:
        """Load Point-E pipeline."""
        if self._pipe is not None:
            return True

        try:
            # Point-E requires special setup
            print("[Point-E] Loading model...")
            # Placeholder - Point-E has a different architecture
            return False

        except Exception as e:
            print(f"[Point-E] Failed to load: {e}")
            return False

    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate 3D from text."""
        return {
            "success": False,
            "error": "Point-E not fully implemented. Use shap_e instead."
        }


class ProceduralGenerator(BaseLocalService, ModelOutputMixin):
    """
    Procedural 3D generation without AI models.

    Uses algorithmic/procedural techniques to generate 3D objects.
    Works offline, no model downloads needed.

    Useful for:
    - Basic primitives with variations
    - Procedural textures
    - L-system plants/trees
    - Noise-based terrain
    """

    def __init__(self):
        super().__init__()

    @property
    def service_name(self) -> str:
        return "procedural"

    @property
    def required_packages(self) -> list:
        return []  # Uses Blender's built-in tools

    def load_model(self) -> bool:
        return True  # No model to load

    def is_available(self) -> bool:
        return True  # Always available

    def generate(
        self,
        object_type: str,
        **params
    ) -> Dict[str, Any]:
        """
        Generate procedural 3D content.

        Args:
            object_type: Type of procedural generation
                - "rock": Procedural rock/boulder
                - "tree": L-system tree
                - "terrain": Noise-based terrain
                - "building": Simple procedural building

        Returns:
            Dict with result info (generates directly in Blender)
        """
        generators = {
            "rock": self._generate_rock,
            "tree": self._generate_tree,
            "terrain": self._generate_terrain,
            "building": self._generate_building,
        }

        generator = generators.get(object_type.lower())
        if not generator:
            return {
                "success": False,
                "error": f"Unknown type: {object_type}. Available: {list(generators.keys())}"
            }

        return generator(**params)

    def _generate_rock(
        self,
        size: float = 1.0,
        detail: int = 3,
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """Generate a procedural rock."""
        import bpy
        import random

        if seed is not None:
            random.seed(seed)

        # Create icosphere
        bpy.ops.mesh.primitive_ico_sphere_add(
            subdivisions=detail,
            radius=size
        )
        obj = bpy.context.active_object
        obj.name = f"Rock_{int(time.time())}"

        # Add displacement modifier
        bpy.ops.object.modifier_add(type='DISPLACE')
        displace = obj.modifiers["Displace"]

        # Create noise texture
        tex = bpy.data.textures.new(f"RockNoise_{obj.name}", 'CLOUDS')
        tex.noise_scale = 0.5
        displace.texture = tex
        displace.strength = size * 0.3

        # Apply modifier
        bpy.ops.object.modifier_apply(modifier="Displace")

        # Add subdivision for smoothing
        bpy.ops.object.modifier_add(type='SUBSURF')
        obj.modifiers["Subdivision"].levels = 1
        bpy.ops.object.modifier_apply(modifier="Subdivision")

        return {
            "success": True,
            "object_name": obj.name,
            "type": "rock"
        }

    def _generate_tree(
        self,
        height: float = 3.0,
        branches: int = 5,
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """Generate a simple procedural tree."""
        import bpy
        import math
        import random

        if seed is not None:
            random.seed(seed)

        # Create trunk
        bpy.ops.mesh.primitive_cylinder_add(
            radius=height * 0.05,
            depth=height * 0.6,
            location=(0, 0, height * 0.3)
        )
        trunk = bpy.context.active_object
        trunk.name = f"Tree_Trunk_{int(time.time())}"

        # Create foliage (simple cones)
        foliage_objs = []
        for i in range(3):
            h = height * (0.5 + i * 0.2)
            r = height * (0.4 - i * 0.1)
            bpy.ops.mesh.primitive_cone_add(
                radius1=r,
                depth=height * 0.3,
                location=(0, 0, h)
            )
            foliage = bpy.context.active_object
            foliage.name = f"Tree_Foliage_{i}"
            foliage_objs.append(foliage)

        # Parent foliage to trunk
        for f in foliage_objs:
            f.parent = trunk

        return {
            "success": True,
            "object_name": trunk.name,
            "type": "tree"
        }

    def _generate_terrain(
        self,
        size: float = 10.0,
        resolution: int = 50,
        height_scale: float = 2.0,
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """Generate noise-based terrain."""
        import bpy
        import random

        if seed is not None:
            random.seed(seed)

        # Create grid
        bpy.ops.mesh.primitive_grid_add(
            x_subdivisions=resolution,
            y_subdivisions=resolution,
            size=size
        )
        terrain = bpy.context.active_object
        terrain.name = f"Terrain_{int(time.time())}"

        # Add displacement
        bpy.ops.object.modifier_add(type='DISPLACE')
        displace = terrain.modifiers["Displace"]

        tex = bpy.data.textures.new(f"TerrainNoise_{terrain.name}", 'CLOUDS')
        tex.noise_scale = 1.0
        tex.noise_depth = 4
        displace.texture = tex
        displace.strength = height_scale
        displace.mid_level = 0.5

        bpy.ops.object.modifier_apply(modifier="Displace")

        return {
            "success": True,
            "object_name": terrain.name,
            "type": "terrain"
        }

    def _generate_building(
        self,
        width: float = 2.0,
        depth: float = 2.0,
        height: float = 4.0,
        floors: int = 2,
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """Generate a simple procedural building."""
        import bpy
        import random

        if seed is not None:
            random.seed(seed)

        # Main structure
        bpy.ops.mesh.primitive_cube_add(
            size=1,
            location=(0, 0, height / 2)
        )
        building = bpy.context.active_object
        building.name = f"Building_{int(time.time())}"
        building.scale = (width / 2, depth / 2, height / 2)
        bpy.ops.object.transform_apply(scale=True)

        # Add roof
        bpy.ops.mesh.primitive_cone_add(
            radius1=max(width, depth) * 0.6,
            depth=height * 0.3,
            location=(0, 0, height + height * 0.15)
        )
        roof = bpy.context.active_object
        roof.name = f"Building_Roof"
        roof.parent = building

        return {
            "success": True,
            "object_name": building.name,
            "type": "building"
        }


# Factory function
def get_local_text_to_3d(
    provider: str = "shap_e",
    device: Optional[str] = None
) -> BaseLocalService:
    """
    Get a local text-to-3D service.

    Args:
        provider: Service provider (shap_e, point_e, procedural)
        device: Device to use (cuda, mps, cpu)

    Returns:
        Service instance
    """
    providers = {
        "shap_e": lambda: LocalShapE(device=device),
        "shape": lambda: LocalShapE(device=device),  # Alias
        "point_e": lambda: LocalPointE(device=device),
        "procedural": lambda: ProceduralGenerator(),
    }

    factory = providers.get(provider.lower())
    if not factory:
        raise ValueError(f"Unknown provider: {provider}. Available: {list(providers.keys())}")

    return factory()
