# SPDX-License-Identifier: MIT
"""
Base classes for local AI service integrations.

All AI runs locally - no external API calls.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Callable
import os
import tempfile


class AIServiceError(Exception):
    """Base exception for AI service errors."""
    pass


class ModelNotFoundError(AIServiceError):
    """Model not installed or not found."""
    pass


class InferenceError(AIServiceError):
    """Error during model inference."""
    pass


class BaseLocalService(ABC):
    """
    Abstract base class for local AI service integrations.

    All services run models locally - no external API calls.
    """

    def __init__(self):
        self._temp_dir = tempfile.gettempdir()
        self._model_loaded = False

    @property
    @abstractmethod
    def service_name(self) -> str:
        """Return the name of this service."""
        pass

    @property
    @abstractmethod
    def required_packages(self) -> list:
        """Return list of required Python packages."""
        pass

    def check_dependencies(self) -> Dict[str, bool]:
        """Check if required packages are installed."""
        results = {}
        for package in self.required_packages:
            try:
                __import__(package.replace("-", "_"))
                results[package] = True
            except ImportError:
                results[package] = False
        return results

    def is_available(self) -> bool:
        """Check if this service is available (all dependencies installed)."""
        deps = self.check_dependencies()
        return all(deps.values())

    @abstractmethod
    def load_model(self) -> bool:
        """Load the model into memory."""
        pass

    @abstractmethod
    def generate(self, **kwargs) -> Dict[str, Any]:
        """Run generation/inference."""
        pass


class ModelOutputMixin:
    """
    Mixin for handling 3D model outputs.
    """

    def import_to_blender(self, filepath: str) -> Dict[str, Any]:
        """
        Import a model file into Blender.

        Args:
            filepath: Path to the model file

        Returns:
            Dict with import results
        """
        import bpy

        ext = filepath.lower().split(".")[-1]

        # Store objects before import
        existing = set(bpy.data.objects.keys())

        try:
            if ext in ("glb", "gltf"):
                bpy.ops.import_scene.gltf(filepath=filepath)
            elif ext == "obj":
                bpy.ops.wm.obj_import(filepath=filepath)
            elif ext == "fbx":
                bpy.ops.import_scene.fbx(filepath=filepath)
            elif ext == "stl":
                # Blender 4.1 removed the legacy import_mesh.stl operator
                bpy.ops.wm.stl_import(filepath=filepath)
            elif ext == "ply":
                # Blender 4.0 removed the legacy import_mesh.ply operator
                bpy.ops.wm.ply_import(filepath=filepath)
            else:
                return {"success": False, "error": f"Unsupported format: {ext}"}

            # Find imported objects
            imported = [name for name in bpy.data.objects.keys() if name not in existing]

            return {
                "success": True,
                "filepath": filepath,
                "imported_objects": imported,
                "count": len(imported)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


class TextureOutputMixin:
    """
    Mixin for handling texture/image outputs.
    """

    def apply_texture_to_object(
        self,
        object_name: str,
        texture_path: str,
        texture_type: str = "diffuse"
    ) -> Dict[str, Any]:
        """
        Apply a texture to an object in Blender.

        Args:
            object_name: Name of the target object
            texture_path: Path to the texture file
            texture_type: Type of texture (diffuse, normal, roughness)

        Returns:
            Dict with results
        """
        import bpy

        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"success": False, "error": f"Object not found: {object_name}"}

        if not hasattr(obj.data, "materials"):
            return {"success": False, "error": "Object doesn't support materials"}

        # Create or get material
        mat_name = f"{object_name}_AI_Material"
        mat = bpy.data.materials.get(mat_name)
        if not mat:
            mat = bpy.data.materials.new(mat_name)
        # A pre-existing material may not use nodes; node_tree would be None
        mat.use_nodes = True

        if not obj.data.materials:
            obj.data.materials.append(mat)
        else:
            obj.data.materials[0] = mat

        # Load texture
        try:
            img = bpy.data.images.load(texture_path)
        except RuntimeError as e:
            return {"success": False, "error": f"Cannot load texture: {e}"}

        # Add texture node
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        bsdf = nodes.get("Principled BSDF")
        if bsdf is None:
            bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf is None:
            return {"success": False,
                    "error": f"Material {mat_name} has no Principled BSDF node"}

        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.image = img

        # Connect based on type
        if texture_type == "diffuse":
            links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
        elif texture_type == "normal":
            normal_map = nodes.new("ShaderNodeNormalMap")
            links.new(tex_node.outputs["Color"], normal_map.inputs["Color"])
            links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
            tex_node.image.colorspace_settings.name = "Non-Color"
        elif texture_type == "roughness":
            links.new(tex_node.outputs["Color"], bsdf.inputs["Roughness"])
            tex_node.image.colorspace_settings.name = "Non-Color"
        elif texture_type == "metallic":
            links.new(tex_node.outputs["Color"], bsdf.inputs["Metallic"])
            tex_node.image.colorspace_settings.name = "Non-Color"

        return {
            "success": True,
            "material": mat_name,
            "texture_type": texture_type,
            "texture_path": texture_path
        }
