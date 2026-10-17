# SPDX-License-Identifier: MIT
"""
Scene utilities for Claude Blender.

Provides scene introspection and serialization.
"""

import os
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import bpy


@contextmanager
def _render_state(scene):
    """Save and restore every render setting our handlers touch.

    Render parameters passed to a tool call are per-call overrides; the
    user's scene configuration must survive the call - including when it
    raises (e.g. a bad engine name or a failed OpenGL capture).
    """
    r = scene.render
    saved = {
        'engine': r.engine,
        'resolution_x': r.resolution_x,
        'resolution_y': r.resolution_y,
        'resolution_percentage': r.resolution_percentage,
        'file_format': r.image_settings.file_format,
        'filepath': r.filepath,
        'fps': r.fps,
        'frame_current': scene.frame_current,
    }
    cycles_samples = getattr(getattr(scene, 'cycles', None), 'samples', None)
    eevee_samples = getattr(getattr(scene, 'eevee', None), 'taa_render_samples', None)
    try:
        yield
    finally:
        r.engine = saved['engine']  # restore engine first: samples live on it
        r.resolution_x = saved['resolution_x']
        r.resolution_y = saved['resolution_y']
        r.resolution_percentage = saved['resolution_percentage']
        r.image_settings.file_format = saved['file_format']
        r.filepath = saved['filepath']
        r.fps = saved['fps']
        # An animation render walks the playhead to its last frame. frame_set
        # (not a bare assignment) re-evaluates animation, so objects don't
        # stay posed at the rendered frame.
        if scene.frame_current != saved['frame_current']:
            frame_set = getattr(scene, 'frame_set', None)
            if frame_set is not None:
                frame_set(saved['frame_current'])
            else:
                scene.frame_current = saved['frame_current']
        if cycles_samples is not None:
            scene.cycles.samples = cycles_samples
        if eevee_samples is not None:
            scene.eevee.taa_render_samples = eevee_samples


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
        active = bpy.context.view_layer.objects.active

        info = {
            'name': scene.name,
            'frame_current': scene.frame_current,
            'frame_start': scene.frame_start,
            'frame_end': scene.frame_end,
            'fps': scene.render.fps,
            'object_count': len(scene.objects),
            'active_object': active.name if active else None,
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

        # Modifier stack and collection membership
        if hasattr(obj, 'modifiers'):
            info['modifiers'] = [
                {'name': m.name, 'type': m.type, 'show_viewport': m.show_viewport}
                for m in obj.modifiers
            ]
        info['collections'] = [c.name for c in obj.users_collection]

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
            screen = getattr(bpy.context, 'screen', None)
            if screen is None:
                return {'success': False,
                        'error': 'No screen available (headless Blender has no viewport)'}

            # Find 3D viewport area
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    region = next(
                        (r for r in area.regions if r.type == 'WINDOW'),
                        area.regions[-1],
                    )
                    override = bpy.context.copy()
                    override['area'] = area
                    override['region'] = region

                    scene = bpy.context.scene
                    with _render_state(scene):
                        scene.render.resolution_x = width
                        scene.render.resolution_y = height
                        scene.render.resolution_percentage = 100
                        # save_render honors image_settings; a prior animation
                        # render leaves a movie format behind, which cannot
                        # write a single image.
                        scene.render.image_settings.file_format = 'PNG'

                        # No write_still: it would clobber whatever file
                        # scene.render.filepath currently points at.
                        with bpy.context.temp_override(**override):
                            bpy.ops.render.opengl()
                        bpy.data.images['Render Result'].save_render(filepath)

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
        resolution_y: Optional[int] = None,
        frame: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Render the scene to an image.

        Args:
            filepath: Output path
            engine: Render engine ('CYCLES', 'BLENDER_EEVEE', etc.)
            samples: Number of samples (for Cycles)
            resolution_x: Output width in pixels
            resolution_y: Output height in pixels
            frame: Render this frame instead of the current one (the
                   playhead is restored afterwards)

        Returns:
            Dict with filepath and success status
        """
        if filepath is None:
            filepath = os.path.join(tempfile.gettempdir(), 'blender_render.png')

        try:
            scene = bpy.context.scene

            # All parameters are per-call overrides; the user's settings
            # are restored afterwards, success or failure.
            with _render_state(scene):
                if frame is not None:
                    scene.frame_set(int(frame))

                if engine:
                    scene.render.engine = engine

                if samples:
                    if scene.render.engine == 'CYCLES':
                        scene.cycles.samples = int(samples)
                    elif scene.render.engine.startswith('BLENDER_EEVEE'):
                        scene.eevee.taa_render_samples = int(samples)

                # Set resolution if specified (100% scale so it applies exactly)
                if resolution_x:
                    scene.render.resolution_x = int(resolution_x)
                if resolution_y:
                    scene.render.resolution_y = int(resolution_y)
                if resolution_x or resolution_y:
                    scene.render.resolution_percentage = 100

                # A prior animation render may have left a movie format
                # selected, which write_still cannot use.
                scene.render.image_settings.file_format = 'PNG'

                scene.render.filepath = filepath
                bpy.ops.render.render(write_still=True)

                engine_used = scene.render.engine
                resolution = [scene.render.resolution_x, scene.render.resolution_y]

            return {
                'success': True,
                'filepath': filepath,
                'engine': engine_used,
                'resolution': resolution
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def render_animation(
        self,
        filepath: Optional[str] = None,
        frame_start: Optional[int] = None,
        frame_end: Optional[int] = None,
        fps: Optional[int] = None,
        engine: Optional[str] = None,
        samples: Optional[int] = None,
        resolution_x: Optional[int] = None,
        resolution_y: Optional[int] = None,
        container: str = 'MP4'
    ) -> Dict[str, Any]:
        """
        Render the animation frame range to an MP4 video or PNG sequence.

        Args:
            filepath: Output .mp4 path (MP4) or output directory (PNG)
            frame_start: First frame (default: scene frame_start)
            frame_end: Last frame (default: scene frame_end)
            fps: Frames per second (default: scene fps)
            engine: Render engine ('CYCLES', 'BLENDER_EEVEE_NEXT', ...)
            samples: Sample count for the chosen engine
            resolution_x: Output width in pixels
            resolution_y: Output height in pixels
            container: 'MP4' (H.264 video) or 'PNG' (image sequence)

        Returns:
            Dict with filepath, frame_count, resolution and render time
        """
        import time

        scene = bpy.context.scene
        container = container.upper()
        if container not in ('MP4', 'PNG'):
            return {'success': False, 'error': "container must be 'MP4' or 'PNG'"}

        orig_range = (scene.frame_start, scene.frame_end)
        start = int(frame_start) if frame_start is not None else scene.frame_start
        end = int(frame_end) if frame_end is not None else scene.frame_end
        if end < start:
            return {'success': False, 'error': f'frame_end {end} < frame_start {start}'}
        frame_count = end - start + 1
        if frame_count > 1000:
            return {
                'success': False,
                'error': f'{frame_count} frames requested; capped at 1000. '
                         'Render a smaller range (or lower fps).'
            }

        try:
            # All parameters (frame range included) are per-call overrides;
            # _render_state and the finally below restore the user's scene.
            with _render_state(scene):
                scene.frame_start = start
                scene.frame_end = end
                if fps:
                    scene.render.fps = int(fps)
                if engine:
                    scene.render.engine = engine
                if samples:
                    if scene.render.engine == 'CYCLES':
                        scene.cycles.samples = int(samples)
                    elif scene.render.engine.startswith('BLENDER_EEVEE'):
                        scene.eevee.taa_render_samples = int(samples)
                if resolution_x:
                    scene.render.resolution_x = int(resolution_x)
                if resolution_y:
                    scene.render.resolution_y = int(resolution_y)
                if resolution_x or resolution_y:
                    scene.render.resolution_percentage = 100

                if container == 'MP4':
                    if filepath is None:
                        filepath = os.path.join(tempfile.gettempdir(), 'blender_animation.mp4')
                    # bpy.path.abspath resolves Blender's '//' (blend-relative)
                    # prefix, which os.path.abspath would preserve literally.
                    filepath = os.path.abspath(bpy.path.abspath(os.path.expanduser(filepath)))
                    stem = filepath[:-4] if filepath.lower().endswith('.mp4') else filepath
                    if '#' in os.path.basename(stem):
                        return {'success': False,
                                'error': "'#' in the output name conflicts with "
                                         "Blender's frame-number substitution; "
                                         "use a plain filename"}

                    scene.render.image_settings.file_format = 'FFMPEG'
                    scene.render.ffmpeg.format = 'MPEG4'
                    scene.render.ffmpeg.codec = 'H264'
                    scene.render.ffmpeg.constant_rate_factor = 'HIGH'
                    scene.render.ffmpeg.audio_codec = 'NONE'
                    # Blender appends the frame range to the stem for video output.
                    scene.render.filepath = stem
                    expected = f'{stem}{start:04d}-{end:04d}.mp4'
                else:
                    if filepath is None:
                        filepath = os.path.join(tempfile.gettempdir(), 'blender_animation_frames')
                    filepath = os.path.abspath(bpy.path.abspath(os.path.expanduser(filepath)))
                    os.makedirs(filepath, exist_ok=True)
                    scene.render.image_settings.file_format = 'PNG'
                    scene.render.filepath = os.path.join(filepath, 'frame_####')
                    expected = filepath

                started = time.monotonic()
                bpy.ops.render.render(animation=True)
                elapsed = time.monotonic() - started

                fps_used = scene.render.fps
                engine_used = scene.render.engine
                resolution = [scene.render.resolution_x, scene.render.resolution_y]

            final_path = expected
            if container == 'MP4':
                if os.path.isfile(expected) and expected != f'{stem}.mp4':
                    final_path = f'{stem}.mp4'
                    os.replace(expected, final_path)
                elif not os.path.isfile(expected):
                    return {
                        'success': False,
                        'error': f'Animation render finished but no file at {expected}'
                    }

            return {
                'success': True,
                'filepath': final_path,
                'container': container,
                'frame_start': start,
                'frame_end': end,
                'frame_count': frame_count,
                'fps': fps_used,
                'engine': engine_used,
                'resolution': resolution,
                'render_time_seconds': round(elapsed, 1),
            }

        except Exception as e:
            return {'success': False, 'error': f'{type(e).__name__}: {e}'}
        finally:
            # The frame range override is per-call; don't leak it into the scene.
            scene.frame_start, scene.frame_end = orig_range

    def save_file(
        self,
        filepath: Optional[str] = None,
        copy: bool = False
    ) -> Dict[str, Any]:
        """
        Save the current .blend file.

        Args:
            filepath: Where to save; defaults to the file's current path
            copy: Save a copy without switching the session to the new path

        Returns:
            Dict with the saved path
        """
        try:
            if filepath:
                filepath = os.path.abspath(bpy.path.abspath(os.path.expanduser(filepath)))
                if not filepath.lower().endswith('.blend'):
                    filepath += '.blend'
                out_dir = os.path.dirname(filepath)
                if out_dir:
                    os.makedirs(out_dir, exist_ok=True)
                bpy.ops.wm.save_as_mainfile(filepath=filepath, copy=bool(copy))
                saved_path = filepath
            else:
                if not bpy.data.filepath:
                    return {'success': False,
                            'error': 'This session has never been saved; '
                                     'provide a filepath'}
                bpy.ops.wm.save_mainfile()
                saved_path = bpy.data.filepath

            if not os.path.isfile(saved_path):
                return {'success': False,
                        'error': f'Save reported success but no file at {saved_path}'}
            return {
                'success': True,
                'filepath': saved_path,
                'copy': bool(copy),
                'file_size': os.path.getsize(saved_path),
            }
        except Exception as e:
            return {'success': False, 'error': f'{type(e).__name__}: {e}'}

    def scene_state(self, max_objects: int = 5000) -> Dict[str, Any]:
        """
        Compact, diffable fingerprint of the scene.

        Everything is rounded so float noise never shows up as a change.
        The MCP side stores these as snapshots and diffs them; the shape is
        deliberately flat (field -> JSON value) to keep that diff generic.

        Args:
            max_objects: Refuse (rather than stall Blender) beyond this count

        Returns:
            Dict with 'scene' settings and per-object 'objects' state
        """
        scene = bpy.context.scene
        objs = list(scene.objects)
        if len(objs) > max_objects:
            return {'success': False,
                    'error': f'{len(objs)} objects exceeds max_objects={max_objects}'}

        def r(values, nd=4):
            return [round(float(v), nd) for v in values]

        objects = {}
        for obj in objs:
            state = {
                'type': obj.type,
                'location': r(obj.location),
                'rotation': r(obj.rotation_euler),
                'scale': r(obj.scale),
                'dimensions': r(obj.dimensions),
                'hidden': bool(obj.hide_viewport or obj.hide_render),
                'parent': obj.parent.name if obj.parent else None,
                'data': obj.data.name if obj.data else None,
                'materials': [s.material.name for s in obj.material_slots if s.material],
                'modifiers': [f'{m.name}:{m.type}' for m in obj.modifiers],
                'collections': sorted(c.name for c in obj.users_collection),
            }
            if obj.type == 'MESH' and obj.data:
                state['vertices'] = len(obj.data.vertices)
                state['polygons'] = len(obj.data.polygons)
            elif obj.type == 'LIGHT' and obj.data:
                state['light'] = f'{obj.data.type} {round(obj.data.energy, 2)}W'
                state['light_color'] = r(obj.data.color, 3)
            elif obj.type == 'CAMERA' and obj.data:
                state['lens'] = round(obj.data.lens, 2)
            anim = obj.animation_data
            if anim and anim.action:
                state['action'] = anim.action.name
            objects[obj.name] = state

        render = scene.render
        settings = {
            'engine': render.engine,
            'resolution': [render.resolution_x, render.resolution_y],
            'fps': render.fps,
            'frame_range': [scene.frame_start, scene.frame_end],
            'frame_current': scene.frame_current,
            'camera': scene.camera.name if scene.camera else None,
            'world': scene.world.name if scene.world else None,
            'materials': len(bpy.data.materials),
        }
        world = self._get_world_info()
        if world and 'background_color' in world:
            settings['world_color'] = r(world['background_color'], 3)
            settings['world_strength'] = round(float(world['background_strength']), 3)

        return {'success': True, 'scene': settings, 'objects': objects}

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
