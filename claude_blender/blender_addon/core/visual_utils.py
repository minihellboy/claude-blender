# SPDX-License-Identifier: MIT
"""
Visual review utilities for Claude Blender.

Multi-view contact sheets (judge a model from every side in ONE image) and
frame-sequence -> MP4 encoding for the MCP-side render jobs. Everything here
is headless-safe: no viewport, no GPU drawing, only renders and image buffers.
"""

import math
import os
import tempfile
from typing import Any, Dict, List, Optional

import bpy

from . import camera_utils
from .scene_utils import SceneSerializer, _render_state

# name -> (azimuth_deg, elevation_deg) in frame_camera's convention
# (azimuth 0 = camera on +X; Blender's "front" looks from -Y).
VIEW_PRESETS = {
    'front': (-90.0, 5.0),
    'back': (90.0, 5.0),
    'right': (0.0, 5.0),
    'left': (180.0, 5.0),
    'top': (-90.0, 90.0),
    'bottom': (-90.0, -90.0),
    'three_quarter': (-45.0, 25.0),
    'three_quarter_back': (135.0, 25.0),
}
DEFAULT_VIEWS = ['front', 'right', 'top', 'three_quarter']

_MAX_CELLS = 12
_GUTTER = 4
_BACKGROUND = (0.08, 0.08, 0.08, 1.0)


def _resolve_views(views) -> List[Dict[str, Any]]:
    """Normalize preset names and {name, azimuth, elevation} dicts."""
    specs = []
    for v in views or DEFAULT_VIEWS:
        if isinstance(v, str):
            key = v.lower()
            if key not in VIEW_PRESETS:
                raise ValueError(
                    f"Unknown view '{v}'. Presets: {', '.join(VIEW_PRESETS)} "
                    "(or pass {'name', 'azimuth', 'elevation'})"
                )
            az, el = VIEW_PRESETS[key]
            specs.append({'name': key, 'azimuth': az, 'elevation': el})
        elif isinstance(v, dict) and 'azimuth' in v:
            specs.append({
                'name': str(v.get('name') or f"az{v['azimuth']:g}_el{v.get('elevation', 0):g}"),
                'azimuth': float(v['azimuth']),
                'elevation': float(v.get('elevation', 0.0)),
            })
        else:
            raise ValueError(f'Invalid view spec: {v!r}')
    if not specs:
        raise ValueError('No views requested')
    if len(specs) > _MAX_CELLS:
        raise ValueError(f'{len(specs)} views requested; max is {_MAX_CELLS}')
    return specs


def contact_sheet(
    paths: List[str],
    filepath: Optional[str] = None,
    columns: Optional[int] = None,
    cell_width: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Tile equally sized images into one PNG grid (row-major, top-left first).

    Args:
        paths: Image files to tile
        filepath: Output PNG path (default: temp file)
        columns: Grid columns (default: ceil(sqrt(n)))
        cell_width: Downscale cells wider than this (keeps sheets of
                    full-HD frames small enough to inline)

    Returns:
        Dict with filepath, grid shape and cell size
    """
    import numpy as np

    if not paths:
        return {'success': False, 'error': 'No images to tile'}
    if len(paths) > 64:
        return {'success': False, 'error': f'{len(paths)} images; max is 64'}
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        return {'success': False, 'error': f'Images not found: {", ".join(missing[:5])}'}

    filepath = filepath or os.path.join(tempfile.gettempdir(), 'claude_contact_sheet.png')
    filepath = os.path.abspath(bpy.path.abspath(os.path.expanduser(filepath)))

    loaded = []
    sheet_img = None
    try:
        for p in paths:
            loaded.append(bpy.data.images.load(p, check_existing=False))
        w, h = loaded[0].size
        odd = [p for p, img in zip(paths, loaded) if tuple(img.size) != (w, h)]
        if odd:
            return {'success': False,
                    'error': f'All images must be {w}x{h}; mismatched: {", ".join(odd[:5])}'}
        if cell_width and w > int(cell_width):
            w, h = int(cell_width), max(1, round(h * int(cell_width) / w))
            for img in loaded:
                img.scale(w, h)

        n = len(loaded)
        cols = max(1, min(int(columns), n)) if columns else math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        g = _GUTTER
        W = cols * w + (cols + 1) * g
        H = rows * h + (rows + 1) * g

        sheet = np.empty((H, W, 4), dtype=np.float32)
        sheet[:] = _BACKGROUND
        px = np.empty(w * h * 4, dtype=np.float32)
        for i, img in enumerate(loaded):
            img.pixels.foreach_get(px)
            r, c = divmod(i, cols)
            x0 = g + c * (w + g)
            # Image buffers are bottom-up; place row 0 at the TOP of the sheet.
            y0 = H - (g + r * (h + g)) - h
            sheet[y0:y0 + h, x0:x0 + w] = px.reshape(h, w, 4)

        sheet_img = bpy.data.images.new('_claude_contact_sheet', W, H, alpha=True)
        sheet_img.pixels.foreach_set(sheet.ravel())
        out_dir = os.path.dirname(filepath)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        sheet_img.filepath_raw = filepath
        sheet_img.file_format = 'PNG'
        sheet_img.save()

        return {
            'success': True,
            'filepath': filepath,
            'columns': cols,
            'rows': rows,
            'cell_size': [w, h],
            'size': [W, H],
        }
    except Exception as e:
        return {'success': False, 'error': f'{type(e).__name__}: {e}'}
    finally:
        for img in loaded:
            bpy.data.images.remove(img)
        if sheet_img is not None:
            bpy.data.images.remove(sheet_img)


def render_views(
    targets: Optional[List[str]] = None,
    views: Optional[List[Any]] = None,
    engine: str = 'BLENDER_EEVEE_NEXT',
    samples: int = 16,
    resolution_x: int = 480,
    resolution_y: int = 360,
    ortho: bool = False,
    margin: float = 1.2,
    columns: Optional[int] = None,
    filepath: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Render the subject from several angles and tile them into one image.

    Uses a temporary camera, so the user's camera, its transform and the
    scene's active camera are untouched; render settings are per-call.

    Args:
        targets: Objects to frame (default: all visible geometry)
        views: Preset names or {'name', 'azimuth', 'elevation'} dicts
        engine: Render engine for every cell
        samples: Samples per cell
        resolution_x: Cell width in pixels
        resolution_y: Cell height in pixels
        ortho: Orthographic projection (true proportions, no perspective)
        margin: Framing margin passed to the camera fit
        columns: Grid columns (default: ceil(sqrt(n)))
        filepath: Output PNG path (default: temp file)

    Returns:
        Dict with the sheet filepath, per-cell view list and grid shape
    """
    try:
        specs = _resolve_views(views)
    except ValueError as e:
        return {'success': False, 'error': str(e)}

    scene = bpy.context.scene
    serializer = SceneSerializer()
    orig_camera = scene.camera
    cell_dir = tempfile.mkdtemp(prefix='claude_views_')

    cam_data = bpy.data.cameras.new('_claude_views_cam')
    cam_data.type = 'ORTHO' if ortho else 'PERSP'
    cam = bpy.data.objects.new('_claude_views_cam', cam_data)
    scene.collection.objects.link(cam)

    cells = []
    try:
        with _render_state(scene):
            # The ortho fit reads the render aspect, so set the cell size first.
            scene.render.resolution_x = int(resolution_x)
            scene.render.resolution_y = int(resolution_y)
            scene.render.resolution_percentage = 100
            for i, spec in enumerate(specs):
                fit = camera_utils.frame_camera(
                    targets=targets, camera=cam.name,
                    azimuth_deg=spec['azimuth'], elevation_deg=spec['elevation'],
                    margin=margin,
                )
                if not fit.get('success'):
                    return fit
                cell = os.path.join(cell_dir, f"{i:02d}_{spec['name']}.png")
                res = serializer.render_image(
                    filepath=cell, engine=engine, samples=samples,
                    resolution_x=resolution_x, resolution_y=resolution_y,
                )
                if not res.get('success'):
                    return {'success': False,
                            'error': f"Render of view '{spec['name']}' failed: {res.get('error')}"}
                cells.append(cell)
            framed = fit.get('targets', [])
    except Exception as e:
        return {'success': False, 'error': f'{type(e).__name__}: {e}'}
    finally:
        scene.camera = orig_camera
        bpy.data.objects.remove(cam, do_unlink=True)
        bpy.data.cameras.remove(cam_data)

    sheet = contact_sheet(cells, filepath=filepath, columns=columns)
    if not sheet.get('success'):
        return sheet
    sheet.update({
        'views': [s['name'] for s in specs],
        'targets': framed,
        'projection': 'ORTHO' if ortho else 'PERSP',
    })
    return sheet


def encode_video(
    frame_paths: List[str],
    filepath: Optional[str] = None,
    fps: int = 24,
) -> Dict[str, Any]:
    """
    Encode a PNG frame sequence (one directory) to an H.264 MP4.

    Runs the sequencer of a throwaway scene, so the user's scene and its
    render settings are never touched.

    Args:
        frame_paths: Ordered frame files, all in the same directory
        filepath: Output .mp4 path (default: temp file)
        fps: Frames per second

    Returns:
        Dict with the video filepath, frame count and resolution
    """
    if not frame_paths:
        return {'success': False, 'error': 'No frames to encode'}
    dirs = {os.path.dirname(os.path.abspath(p)) for p in frame_paths}
    if len(dirs) != 1:
        return {'success': False, 'error': 'All frames must be in one directory'}
    missing = [p for p in frame_paths if not os.path.isfile(p)]
    if missing:
        return {'success': False, 'error': f'Frames not found: {", ".join(missing[:5])}'}

    filepath = filepath or os.path.join(tempfile.gettempdir(), 'claude_render_job.mp4')
    filepath = os.path.abspath(bpy.path.abspath(os.path.expanduser(filepath)))
    stem = filepath[:-4] if filepath.lower().endswith('.mp4') else filepath
    if '#' in os.path.basename(stem):
        return {'success': False,
                'error': "'#' in the output name conflicts with Blender's "
                         "frame-number substitution; use a plain filename"}
    out_dir = os.path.dirname(stem)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    probe = bpy.data.images.load(frame_paths[0], check_existing=False)
    w, h = probe.size
    bpy.data.images.remove(probe)
    if w % 2 or h % 2:
        return {'success': False, 'error': f'H.264 needs even dimensions; frames are {w}x{h}'}

    n = len(frame_paths)
    tmp = bpy.data.scenes.new('_claude_encode')
    try:
        se = tmp.sequence_editor_create()
        strips = getattr(se, 'strips', None) or se.sequences  # 'strips' since 4.4
        strip = strips.new_image(
            name='frames', filepath=os.path.abspath(frame_paths[0]),
            channel=1, frame_start=1,
        )
        for p in frame_paths[1:]:
            strip.elements.append(os.path.basename(p))

        tmp.frame_start = 1
        tmp.frame_end = n
        # Frames are already display-referred; a filmic/AgX view transform
        # would tone-map them a second time.
        tmp.view_settings.view_transform = 'Standard'
        r = tmp.render
        r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
        r.fps = int(fps)
        r.use_sequencer = True
        r.image_settings.file_format = 'FFMPEG'
        r.ffmpeg.format = 'MPEG4'
        r.ffmpeg.codec = 'H264'
        r.ffmpeg.constant_rate_factor = 'HIGH'
        r.ffmpeg.audio_codec = 'NONE'
        r.filepath = stem

        bpy.ops.render.render(animation=True, scene=tmp.name)
    except Exception as e:
        return {'success': False, 'error': f'{type(e).__name__}: {e}'}
    finally:
        bpy.data.scenes.remove(tmp)

    # Blender appends the frame range to the stem for video output.
    produced = f'{stem}{1:04d}-{n:04d}.mp4'
    final = f'{stem}.mp4'
    if os.path.isfile(produced):
        os.replace(produced, final)
    if not os.path.isfile(final):
        return {'success': False, 'error': f'Encoding finished but no file at {final}'}
    return {
        'success': True,
        'filepath': final,
        'frame_count': n,
        'fps': int(fps),
        'resolution': [w, h],
        'file_size': os.path.getsize(final),
    }
