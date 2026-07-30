# SPDX-License-Identifier: MIT
"""
Camera utilities for Claude Blender.

Pure-math camera framing that works headless (no view3d context needed).
"""

import math
from typing import Any, Dict, List, Optional

import bpy
from mathutils import Vector

# Object types that contribute to framing bounds by default.
_FRAMEABLE_TYPES = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT'}


def _world_bounds(objs) -> Dict[str, Any]:
    """Bounding-sphere (center, radius) of the given objects in world space."""
    points = []
    for obj in objs:
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        # Empties and lights have a degenerate bound_box; fall back to origin.
        points.extend(corners if corners else [])
        points.append(obj.matrix_world.translation.copy())

    lo = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    hi = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    center = (lo + hi) / 2
    radius = max((p - center).length for p in points)
    return {'center': center, 'radius': max(radius, 0.01)}


def _get_or_create_camera(name: Optional[str]):
    """Resolve the camera to use, creating one when the scene has none."""
    if name:
        cam = bpy.data.objects.get(name)
        if cam is None or cam.type != 'CAMERA':
            return None, f"Camera not found: {name}"
        return cam, None

    if bpy.context.scene.camera:
        return bpy.context.scene.camera, None

    for obj in bpy.context.scene.objects:
        if obj.type == 'CAMERA':
            return obj, None

    cam_data = bpy.data.cameras.new('Camera')
    cam = bpy.data.objects.new('Camera', cam_data)
    bpy.context.scene.collection.objects.link(cam)
    return cam, None


def frame_camera(
    targets: Optional[List[str]] = None,
    camera: Optional[str] = None,
    azimuth_deg: float = 45.0,
    elevation_deg: float = 20.0,
    margin: float = 1.15,
    distance: Optional[float] = None,
    lens: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Position and aim a camera so the target objects fill the frame.

    Args:
        targets: Object names to frame (default: all visible geometry)
        camera: Camera object name (default: scene camera, created if missing)
        azimuth_deg: Horizontal orbit angle around the subject (0 = +X axis)
        elevation_deg: Vertical angle above the subject's horizon
        margin: Framing margin (1.0 = subject touches frame edges)
        distance: Explicit camera distance, overriding the fit calculation
        lens: Optional focal length in mm to set before fitting

    Returns:
        Dict with camera name, final transform, distance and framed targets
    """
    if targets:
        objs, missing = [], []
        for name in targets:
            obj = bpy.data.objects.get(name)
            if obj:
                objs.append(obj)
            else:
                missing.append(name)
        if missing:
            return {'success': False, 'error': f'Objects not found: {", ".join(missing)}'}
    else:
        objs = [
            o for o in bpy.context.scene.objects
            if o.type in _FRAMEABLE_TYPES and not o.hide_viewport and not o.hide_render
        ]
        if not objs:
            return {'success': False, 'error': 'No visible geometry to frame'}

    bounds = _world_bounds(objs)
    center, radius = bounds['center'], bounds['radius']

    cam, err = _get_or_create_camera(camera)
    if err:
        return {'success': False, 'error': err}

    if lens and cam.data.type == 'PERSP':
        cam.data.lens = float(lens)

    az = math.radians(azimuth_deg)
    el = math.radians(elevation_deg)
    direction = Vector((
        math.cos(el) * math.cos(az),
        math.cos(el) * math.sin(az),
        math.sin(el),
    ))

    if cam.data.type == 'ORTHO':
        cam.data.ortho_scale = 2.0 * radius * margin
        dist = distance if distance is not None else radius * 3.0
    else:
        # sin() (not tan()) so the bounding sphere is tangent to the frustum.
        fov = min(cam.data.angle_x, cam.data.angle_y)
        dist = distance if distance is not None else (radius * margin) / math.sin(fov / 2)

    cam.location = center + direction * dist
    cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()

    # Keep the subject inside the clip range.
    if dist + radius > cam.data.clip_end:
        cam.data.clip_end = (dist + radius) * 4
    cam.data.clip_start = min(cam.data.clip_start, max(dist - radius, 0.01) / 10)

    bpy.context.scene.camera = cam

    return {
        'success': True,
        'camera': cam.name,
        'location': list(cam.location),
        'rotation_euler': list(cam.rotation_euler),
        'distance': dist,
        'target_center': list(center),
        'target_radius': radius,
        'targets': [o.name for o in objs],
    }
