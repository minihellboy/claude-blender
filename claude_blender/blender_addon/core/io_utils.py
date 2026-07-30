# SPDX-License-Identifier: MIT
"""
Import/export utilities for Claude Blender.

Wraps Blender 4.x file-format operators behind a uniform interface so that
callers only supply a filepath (format is inferred from the extension).
"""

import os
from typing import Any, Dict, List, Optional

import bpy


# Extension -> (operator path, extra kwargs) for Blender 4.x importers.
_IMPORTERS = {
    '.obj': ('wm.obj_import', {}),
    '.stl': ('wm.stl_import', {}),
    '.ply': ('wm.ply_import', {}),
    '.fbx': ('import_scene.fbx', {}),
    '.gltf': ('import_scene.gltf', {}),
    '.glb': ('import_scene.gltf', {}),
    '.usd': ('wm.usd_import', {}),
    '.usda': ('wm.usd_import', {}),
    '.usdc': ('wm.usd_import', {}),
    '.usdz': ('wm.usd_import', {}),
    '.dae': ('wm.collada_import', {}),
    '.abc': ('wm.alembic_import', {}),
}

# Extension -> (operator path, name of its "selected objects only" flag, extra kwargs).
_EXPORTERS = {
    '.obj': ('wm.obj_export', 'export_selected_objects', {}),
    '.stl': ('wm.stl_export', 'export_selected_objects', {}),
    '.ply': ('wm.ply_export', 'export_selected_objects', {}),
    '.fbx': ('export_scene.fbx', 'use_selection', {}),
    '.gltf': ('export_scene.gltf', 'use_selection', {'export_format': 'GLTF_SEPARATE'}),
    '.glb': ('export_scene.gltf', 'use_selection', {'export_format': 'GLB'}),
    '.usd': ('wm.usd_export', 'selected_objects_only', {}),
    '.usda': ('wm.usd_export', 'selected_objects_only', {}),
    '.usdc': ('wm.usd_export', 'selected_objects_only', {}),
    '.dae': ('wm.collada_export', 'selected', {}),
    '.abc': ('wm.alembic_export', 'selected', {}),
}


def _resolve_operator(path: str):
    """Resolve 'category.name' to the bpy.ops callable."""
    category, name = path.split('.')
    return getattr(getattr(bpy.ops, category), name)


def _extension(filepath: str, format_hint: Optional[str]) -> str:
    """Normalize the effective extension, letting an explicit format win."""
    if format_hint:
        ext = format_hint.lower().lstrip('.')
        return f'.{ext}'
    return os.path.splitext(filepath)[1].lower()


def import_model(filepath: str, format: Optional[str] = None) -> Dict[str, Any]:
    """
    Import a model file into the current scene.

    Args:
        filepath: Path to the model file
        format: Optional explicit format ('obj', 'stl', ...); inferred from
                the extension when omitted

    Returns:
        Dict with success, objects_added (names) and filepath
    """
    filepath = os.path.abspath(bpy.path.abspath(os.path.expanduser(filepath)))
    if not os.path.isfile(filepath):
        return {'success': False, 'error': f'File not found: {filepath}'}

    ext = _extension(filepath, format)
    entry = _IMPORTERS.get(ext)
    if not entry:
        return {
            'success': False,
            'error': f"Unsupported import format '{ext}'. "
                     f"Supported: {', '.join(sorted(_IMPORTERS))}",
        }

    op_path, extra = entry
    try:
        op = _resolve_operator(op_path)
    except AttributeError:
        return {'success': False, 'error': f'Importer not available in this Blender: {op_path}'}

    before = set(bpy.data.objects.keys())
    try:
        op(filepath=filepath, **extra)
    except Exception as e:
        return {'success': False, 'error': f'{type(e).__name__}: {e}'}

    added = sorted(set(bpy.data.objects.keys()) - before)
    return {
        'success': True,
        'filepath': filepath,
        'format': ext.lstrip('.'),
        'objects_added': added,
    }


def export_model(
    filepath: str,
    format: Optional[str] = None,
    objects: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Export the scene (or specific objects) to a model file.

    Args:
        filepath: Output path; the extension selects the format
        format: Optional explicit format overriding the extension
        objects: Optional list of object names to export (whole scene if omitted)

    Returns:
        Dict with success, filepath, exported object count and file size
    """
    filepath = os.path.abspath(bpy.path.abspath(os.path.expanduser(filepath)))
    ext = _extension(filepath, format)
    # When an explicit format overrides a mismatched extension, rename the
    # output to match - exporters write by their own format, and a stale
    # extension would fail the success check below.
    if format and not filepath.lower().endswith(ext):
        filepath = os.path.splitext(filepath)[0] + ext

    entry = _EXPORTERS.get(ext)
    if not entry:
        return {
            'success': False,
            'error': f"Unsupported export format '{ext}'. "
                     f"Supported: {', '.join(sorted(_EXPORTERS))}",
        }

    op_path, selection_flag, extra = entry
    try:
        op = _resolve_operator(op_path)
    except AttributeError:
        return {'success': False, 'error': f'Exporter not available in this Blender: {op_path}'}

    out_dir = os.path.dirname(filepath)
    if out_dir and not os.path.isdir(out_dir):
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            return {'success': False, 'error': f'Cannot create output directory: {e}'}

    kwargs = dict(extra)
    exported_count = len(bpy.context.scene.objects)

    view_layer = bpy.context.view_layer
    prev_selected = [o.name for o in bpy.context.selected_objects]
    prev_active = view_layer.objects.active

    try:
        if objects:
            missing = [n for n in objects if n not in bpy.data.objects]
            if missing:
                return {'success': False, 'error': f'Objects not found: {", ".join(missing)}'}
            try:
                for obj in bpy.context.scene.objects:
                    obj.select_set(False)
                for name in objects:
                    bpy.data.objects[name].select_set(True)
                view_layer.objects.active = bpy.data.objects[objects[0]]
            except RuntimeError as e:
                return {'success': False,
                        'error': f'Cannot select for export (object not in the '
                                 f'current view layer?): {e}'}
            kwargs[selection_flag] = True
            exported_count = len(objects)

        try:
            op(filepath=filepath, **kwargs)
        except Exception as e:
            return {'success': False, 'error': f'{type(e).__name__}: {e}'}
    finally:
        # The user's selection is not ours to keep.
        if objects:
            try:
                for obj in bpy.context.scene.objects:
                    obj.select_set(obj.name in prev_selected)
                view_layer.objects.active = prev_active
            except Exception:
                pass

    if not os.path.isfile(filepath):
        return {'success': False, 'error': f'Exporter finished but no file at {filepath}'}

    return {
        'success': True,
        'filepath': filepath,
        'format': ext.lstrip('.'),
        'object_count': exported_count,
        'file_size': os.path.getsize(filepath),
    }
