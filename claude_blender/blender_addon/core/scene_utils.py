# SPDX-License-Identifier: MIT
"""
Scene utilities for Claude Blender.

Provides scene introspection and serialization.
"""

import os
import tempfile
from typing import Any, Dict, List, Optional

import bpy


class SceneSerializer:
    """Serializes Blender scene data to JSON-compatible dicts."""

    def get_scene_info(self, detail_level: str = 'basic') -> Dict[str, Any]:
        """
        Get information about the current scene.

        Args:
            detail_level: 'minimal', 'basic', 'detailed', or 'full'

        Returns:
            Dict containing scene information
        """
        scene = bpy.context.scene

        info = {
            'name': scene.name,
            'frame_current': scene.frame_current,
            'frame_start': scene.frame_start,
            'frame_end': scene.frame_end,
            'fps': scene.render.fps,
            'object_count': len(scene.objects),
        }

        if detail_level in ('basic', 'detailed', 'full'):
            info['objects'] = self._get_objects_list(scene, detail_level)

        if detail_level in ('detailed', 'full'):
            info['render'] = self._get_render_settings()
            info['world'] = self._get_world_info()

        if detail_level == 'full':
            info['materials'] = self._get_materials_list()
            info['collections'] = self._get_collections_list()

        return info

    def get_object_info(self, name: str) -> Dict[str, Any]:
        """Get detailed information about a specific object."""
        obj = bpy.data.objects.get(name)
        if not obj:
            return {'error': f'Object not found: {name}'}

        info = {
            'name': obj.name,
            'type': obj.type,
            'location': list(obj.location),
            'rotation_euler': list(obj.rotation_euler),
            'scale': list(obj.scale),
            'dimensions': list(obj.dimensions),
            'visible': not obj.hide_viewport,
            'selected': obj.select_get(),
            'parent': obj.parent.name if obj.parent else None,
            'children': [c.name for c in obj.children],
        }

        # Add type-specific info
        if obj.type == 'MESH':
            info['mesh'] = self._get_mesh_info(obj)
        elif obj.type == 'CAMERA':
            info['camera'] = self._get_camera_info(obj)
        elif obj.type == 'LIGHT':
            info['light'] = self._get_light_info(obj)

        # Materials
        if obj.data and hasattr(obj.data, 'materials'):
            info['materials'] = [m.name for m in obj.data.materials if m]

        return info

    def capture_viewport(
        self,
        filepath: Optional[str] = None,
        width: int = 1920,
        height: int = 1080
    ) -> Dict[str, Any]:
        """
        Capture the 3D viewport as an image.

        Args:
            filepath: Output path (or None for temp file)
            width: Image width
            height: Image height

        Returns:
            Dict with filepath and success status
        """
        if filepath is None:
            filepath = os.path.join(tempfile.gettempdir(), 'blender_viewport.png')

        try:
            # Find 3D viewport area
            for area in bpy.context.screen.areas:
                if area.type == 'VIEW_3D':
                    # Use OpenGL render
                    override = bpy.context.copy()
                    override['area'] = area
                    override['region'] = area.regions[-1]

                    # Store current resolution
                    old_x = bpy.context.scene.render.resolution_x
                    old_y = bpy.context.scene.render.resolution_y

                    # Set capture resolution
                    bpy.context.scene.render.resolution_x = width
                    bpy.context.scene.render.resolution_y = height

                    # Capture
                    with bpy.context.temp_override(**override):
                        bpy.ops.render.opengl(write_still=True)

                    # Save
                    bpy.data.images['Render Result'].save_render(filepath)

                    # Restore resolution
                    bpy.context.scene.render.resolution_x = old_x
                    bpy.context.scene.render.resolution_y = old_y

                    return {
                        'success': True,
                        'filepath': filepath,
                        'width': width,
                        'height': height
                    }

            return {
                'success': False,
                'error': 'No 3D viewport found'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def render_image(
        self,
        filepath: Optional[str] = None,
        engine: Optional[str] = None,
        samples: Optional[int] = None,
        resolution_x: Optional[int] = None,
        resolution_y: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Render the scene to an image.

        Args:
            filepath: Output path
            engine: Render engine ('CYCLES', 'BLENDER_EEVEE', etc.)
            samples: Number of samples (for Cycles)
            resolution_x: Output width in pixels
            resolution_y: Output height in pixels

        Returns:
            Dict with filepath and success status
        """
        if filepath is None:
            filepath = os.path.join(tempfile.gettempdir(), 'blender_render.png')

        try:
            scene = bpy.context.scene

            # Set engine if specified
            if engine:
                scene.render.engine = engine

            # Set samples if specified
            if samples and scene.render.engine == 'CYCLES':
                scene.cycles.samples = samples

            # Set resolution if specified (100% scale so it applies exactly)
            if resolution_x:
                scene.render.resolution_x = int(resolution_x)
            if resolution_y:
                scene.render.resolution_y = int(resolution_y)
            if resolution_x or resolution_y:
                scene.render.resolution_percentage = 100

            # Set output path
            scene.render.filepath = filepath

            # Render
            bpy.ops.render.render(write_still=True)

            return {
                'success': True,
                'filepath': filepath,
                'engine': scene.render.engine,
                'resolution': [scene.render.resolution_x, scene.render.resolution_y]
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _get_objects_list(self, scene, detail_level: str) -> List[Dict]:
        """Get list of objects in the scene."""
        objects = []
        for obj in scene.objects:
            obj_info = {
                'name': obj.name,
                'type': obj.type,
            }

            if detail_level in ('detailed', 'full'):
                obj_info.update({
                    'location': list(obj.location),
                    'rotation': list(obj.rotation_euler),
                    'scale': list(obj.scale),
                    'visible': not obj.hide_viewport,
                    'parent': obj.parent.name if obj.parent else None,
                })

            objects.append(obj_info)

        return objects

    def _get_render_settings(self) -> Dict[str, Any]:
        """Get render settings."""
        render = bpy.context.scene.render
        return {
            'engine': render.engine,
            'resolution_x': render.resolution_x,
            'resolution_y': render.resolution_y,
            'resolution_percentage': render.resolution_percentage,
            'fps': render.fps,
            'film_transparent': render.film_transparent,
        }

    def _get_world_info(self) -> Optional[Dict[str, Any]]:
        """Get world/environment info."""
        world = bpy.context.scene.world
        if not world:
            return None

        info = {'name': world.name}

        if world.use_nodes and world.node_tree:
            # Try to get background color
            for node in world.node_tree.nodes:
                if node.type == 'BACKGROUND':
                    info['background_color'] = list(node.inputs['Color'].default_value)
                    info['background_strength'] = node.inputs['Strength'].default_value
                    break

        return info

    def _get_materials_list(self) -> List[Dict[str, Any]]:
        """Get list of all materials."""
        materials = []
        for mat in bpy.data.materials:
            mat_info = {
                'name': mat.name,
                'use_nodes': mat.use_nodes,
            }
            if not mat.use_nodes:
                mat_info['diffuse_color'] = list(mat.diffuse_color)
            materials.append(mat_info)
        return materials

    def _get_collections_list(self) -> List[Dict[str, Any]]:
        """Get list of collections."""
        collections = []
        for coll in bpy.data.collections:
            collections.append({
                'name': coll.name,
                'object_count': len(coll.objects),
                'objects': [obj.name for obj in coll.objects],
            })
        return collections

    def _get_mesh_info(self, obj) -> Dict[str, Any]:
        """Get mesh-specific information."""
        mesh = obj.data
        return {
            'vertex_count': len(mesh.vertices),
            'edge_count': len(mesh.edges),
            'polygon_count': len(mesh.polygons),
            'has_uv': len(mesh.uv_layers) > 0,
            'uv_layers': [uv.name for uv in mesh.uv_layers],
        }

    def _get_camera_info(self, obj) -> Dict[str, Any]:
        """Get camera-specific information."""
        cam = obj.data
        return {
            'type': cam.type,
            'lens': cam.lens if cam.type == 'PERSP' else None,
            'ortho_scale': cam.ortho_scale if cam.type == 'ORTHO' else None,
            'clip_start': cam.clip_start,
            'clip_end': cam.clip_end,
        }

    def _get_light_info(self, obj) -> Dict[str, Any]:
        """Get light-specific information."""
        light = obj.data
        return {
            'type': light.type,
            'color': list(light.color),
            'energy': light.energy,
        }
