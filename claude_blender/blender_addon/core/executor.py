# SPDX-License-Identifier: MIT
"""
Command executor for Claude Blender.

Executes Python code and Blender operations in a safe context.
"""

import sys
import io
import traceback
from typing import Any, Dict, Optional, Tuple
from contextlib import redirect_stdout, redirect_stderr

import bpy


class CommandExecutor:
    """
    Executes Python code and Blender commands.

    All code runs in Blender's main thread (via timer callbacks),
    ensuring thread safety.
    """

    def __init__(self):
        self.last_result: Any = None
        self.execution_count: int = 0

    def execute_python(self, code: str, capture_output: bool = True) -> Dict[str, Any]:
        """
        Execute arbitrary Python code.

        Args:
            code: Python code to execute
            capture_output: Whether to capture stdout/stderr

        Returns:
            Dict with:
                - success: bool
                - result: Any (last expression value or None)
                - output: str (captured stdout)
                - error: str (error message if failed)
        """
        self.execution_count += 1

        # Create execution namespace with common imports
        namespace = {
            'bpy': bpy,
            'mathutils': __import__('mathutils'),
            'math': __import__('math'),
            '__builtins__': __builtins__,
            '__result__': None,
        }

        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        try:
            # Compile the code
            compiled = compile(code, '<claude_code>', 'exec')

            # Execute with output capture
            if capture_output:
                with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                    exec(compiled, namespace)
            else:
                exec(compiled, namespace)

            # Get result (if code sets __result__)
            result = namespace.get('__result__')
            self.last_result = result

            return {
                'success': True,
                'result': self._serialize_result(result),
                'output': stdout_capture.getvalue(),
                'error': None
            }

        except SyntaxError as e:
            return {
                'success': False,
                'result': None,
                'output': stdout_capture.getvalue(),
                'error': f"SyntaxError: {e.msg} (line {e.lineno})"
            }
        except Exception as e:
            return {
                'success': False,
                'result': None,
                'output': stdout_capture.getvalue(),
                'error': f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            }

    def execute_operator(
        self,
        operator: str,
        context_override: Optional[Dict] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute a Blender operator.

        Args:
            operator: Operator ID (e.g., 'mesh.primitive_cube_add')
            context_override: Optional context override dict
            **kwargs: Operator arguments

        Returns:
            Dict with:
                - success: bool
                - result: str (operator result set)
                - error: str (error message if failed)
        """
        try:
            # Get operator function
            parts = operator.split('.')
            if len(parts) != 2:
                return {
                    'success': False,
                    'result': None,
                    'error': f"Invalid operator format: {operator}"
                }

            category, name = parts
            op_category = getattr(bpy.ops, category, None)
            if op_category is None:
                return {
                    'success': False,
                    'result': None,
                    'error': f"Unknown operator category: {category}"
                }

            op_func = getattr(op_category, name, None)
            if op_func is None:
                return {
                    'success': False,
                    'result': None,
                    'error': f"Unknown operator: {operator}"
                }

            # Execute with optional context override
            if context_override:
                with bpy.context.temp_override(**context_override):
                    result = op_func(**kwargs)
            else:
                result = op_func(**kwargs)

            return {
                'success': True,
                'result': str(result),
                'error': None
            }

        except Exception as e:
            return {
                'success': False,
                'result': None,
                'error': f"{type(e).__name__}: {str(e)}"
            }

    def add_object(
        self,
        object_type: str,
        name: Optional[str] = None,
        location: Tuple[float, float, float] = (0, 0, 0),
        rotation: Tuple[float, float, float] = (0, 0, 0),
        scale: Tuple[float, float, float] = (1, 1, 1),
        **kwargs
    ) -> Dict[str, Any]:
        """
        Add a primitive object to the scene.

        Args:
            object_type: Type of primitive (cube, sphere, cylinder, etc.)
            name: Optional object name
            location: Object location
            rotation: Object rotation (radians)
            scale: Object scale
            **kwargs: Additional operator arguments

        Returns:
            Dict with object info or error
        """
        # Map type names to operators
        type_map = {
            'cube': 'mesh.primitive_cube_add',
            'sphere': 'mesh.primitive_uv_sphere_add',
            'ico_sphere': 'mesh.primitive_ico_sphere_add',
            'cylinder': 'mesh.primitive_cylinder_add',
            'cone': 'mesh.primitive_cone_add',
            'torus': 'mesh.primitive_torus_add',
            'plane': 'mesh.primitive_plane_add',
            'circle': 'mesh.primitive_circle_add',
            'monkey': 'mesh.primitive_monkey_add',
            'empty': 'object.empty_add',
            'camera': 'object.camera_add',
            'light': 'object.light_add',
            'point_light': 'object.light_add',
            'sun': 'object.light_add',
            'spot': 'object.light_add',
            'area': 'object.light_add',
        }

        operator = type_map.get(object_type.lower())
        if not operator:
            return {
                'success': False,
                'object_name': None,
                'error': f"Unknown object type: {object_type}"
            }

        # Add light type for light objects
        if object_type.lower() in ('point_light', 'sun', 'spot', 'area'):
            light_types = {
                'point_light': 'POINT',
                'sun': 'SUN',
                'spot': 'SPOT',
                'area': 'AREA'
            }
            kwargs['type'] = light_types.get(object_type.lower(), 'POINT')

        # Execute operator (scale is applied post-creation: primitive_*_add
        # operators silently ignore their scale argument in object mode)
        result = self.execute_operator(
            operator,
            location=location,
            rotation=rotation,
            **kwargs
        )

        if not result['success']:
            return {
                'success': False,
                'object_name': None,
                'error': result['error']
            }

        # Get created object, rename and scale if needed
        obj = bpy.context.active_object
        if obj and name:
            obj.name = name
        if obj and tuple(scale) != (1, 1, 1):
            obj.scale = scale

        return {
            'success': True,
            'object_name': obj.name if obj else None,
            'object_type': obj.type if obj else None,
            'location': list(obj.location) if obj else None,
            'error': None
        }

    def modify_object(
        self,
        name: str,
        location: Optional[Tuple[float, float, float]] = None,
        rotation: Optional[Tuple[float, float, float]] = None,
        scale: Optional[Tuple[float, float, float]] = None,
        visible: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Modify an existing object's properties.

        Args:
            name: Object name
            location: New location (or None to keep current)
            rotation: New rotation in radians (or None)
            scale: New scale (or None)
            visible: Visibility (or None)

        Returns:
            Dict with success status
        """
        obj = bpy.data.objects.get(name)
        if not obj:
            return {
                'success': False,
                'error': f"Object not found: {name}"
            }

        try:
            if location is not None:
                obj.location = location
            if rotation is not None:
                obj.rotation_euler = rotation
            if scale is not None:
                obj.scale = scale
            if visible is not None:
                obj.hide_viewport = not visible
                obj.hide_render = not visible

            return {
                'success': True,
                'object_name': obj.name,
                'location': list(obj.location),
                'rotation': list(obj.rotation_euler),
                'scale': list(obj.scale),
                'error': None
            }

        except Exception as e:
            return {
                'success': False,
                'error': f"{type(e).__name__}: {str(e)}"
            }

    def delete_object(self, name: str) -> Dict[str, Any]:
        """Delete an object by name."""
        obj = bpy.data.objects.get(name)
        if not obj:
            return {
                'success': False,
                'error': f"Object not found: {name}"
            }

        try:
            bpy.data.objects.remove(obj, do_unlink=True)
            return {
                'success': True,
                'deleted': name,
                'error': None
            }
        except Exception as e:
            return {
                'success': False,
                'error': f"{type(e).__name__}: {str(e)}"
            }

    def add_modifier(
        self,
        object_name: str,
        modifier_type: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Add a modifier to an object and configure its parameters.

        Args:
            object_name: Object to add the modifier to
            modifier_type: Blender modifier type (e.g. 'SUBSURF', 'BOOLEAN',
                           'ARRAY', 'MIRROR', 'SOLIDIFY', 'BEVEL')
            params: Modifier attribute values; string values for attributes
                    that expect an object (e.g. boolean 'object') are resolved
                    by object name

        Returns:
            Dict with the created modifier name plus per-param results
        """
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {'success': False, 'error': f'Object not found: {object_name}'}
        if not hasattr(obj, 'modifiers'):
            return {'success': False, 'error': f'Object type {obj.type} has no modifiers'}

        modifier_type = modifier_type.upper()
        try:
            mod = obj.modifiers.new(name=modifier_type.title(), type=modifier_type)
        except (TypeError, RuntimeError) as e:
            return {'success': False, 'error': f'Invalid modifier type {modifier_type}: {e}'}
        if mod is None:
            return {'success': False, 'error': f'Modifier type {modifier_type} rejected for {obj.type}'}

        params_set, params_failed = [], {}
        for key, value in (params or {}).items():
            try:
                setattr(mod, key, value)
                params_set.append(key)
            except (TypeError, AttributeError) as e:
                # Attributes expecting a datablock get a name string from JSON.
                target = bpy.data.objects.get(value) if isinstance(value, str) else None
                if target is not None:
                    try:
                        setattr(mod, key, target)
                        params_set.append(key)
                        continue
                    except Exception as e2:
                        e = e2
                params_failed[key] = str(e)

        result = {
            'success': True,
            'object': obj.name,
            'modifier': mod.name,
            'type': mod.type,
            'params_set': params_set,
        }
        if params_failed:
            result['params_failed'] = params_failed
        return result

    def apply_modifier(self, object_name: str, modifier_name: str) -> Dict[str, Any]:
        """Apply (bake) a modifier into the object's mesh data."""
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {'success': False, 'error': f'Object not found: {object_name}'}
        if modifier_name not in obj.modifiers:
            return {'success': False, 'error': f'Modifier not found on {object_name}: {modifier_name}'}

        try:
            with bpy.context.temp_override(
                object=obj, active_object=obj, selected_objects=[obj]
            ):
                bpy.ops.object.modifier_apply(modifier=modifier_name)
            return {'success': True, 'object': obj.name, 'applied': modifier_name}
        except Exception as e:
            return {'success': False, 'error': f'{type(e).__name__}: {e}'}

    def remove_modifier(self, object_name: str, modifier_name: str) -> Dict[str, Any]:
        """Remove a modifier without applying it."""
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {'success': False, 'error': f'Object not found: {object_name}'}
        mod = obj.modifiers.get(modifier_name)
        if not mod:
            return {'success': False, 'error': f'Modifier not found on {object_name}: {modifier_name}'}
        obj.modifiers.remove(mod)
        return {'success': True, 'object': obj.name, 'removed': modifier_name}

    def duplicate_object(
        self,
        name: str,
        count: int = 1,
        offset: Tuple[float, float, float] = (0, 0, 0),
        linked: bool = False
    ) -> Dict[str, Any]:
        """
        Duplicate an object N times with a cumulative offset (linear array).

        Args:
            name: Source object name
            count: Number of copies (1-100)
            offset: Per-copy location offset [x, y, z]
            linked: Share mesh data with the source (instances) instead of copying

        Returns:
            Dict with the names of the created objects
        """
        from mathutils import Vector

        src = bpy.data.objects.get(name)
        if not src:
            return {'success': False, 'error': f'Object not found: {name}'}

        count = int(count)
        if not 1 <= count <= 100:
            return {'success': False, 'error': 'count must be between 1 and 100'}

        collection = src.users_collection[0] if src.users_collection \
            else bpy.context.scene.collection
        step = Vector(offset)
        created = []
        try:
            for i in range(1, count + 1):
                dup = src.copy()
                if src.data and not linked:
                    dup.data = src.data.copy()
                dup.location = src.location + step * i
                collection.objects.link(dup)
                created.append(dup.name)
        except Exception as e:
            return {'success': False, 'error': f'{type(e).__name__}: {e}', 'created': created}

        return {'success': True, 'source': src.name, 'created': created}

    def set_parent(
        self,
        child_names: list,
        parent_name: Optional[str] = None,
        keep_transform: bool = True
    ) -> Dict[str, Any]:
        """Parent objects to a target (or clear parents when parent_name is None)."""
        parent = None
        if parent_name is not None:
            parent = bpy.data.objects.get(parent_name)
            if not parent:
                return {'success': False, 'error': f'Parent not found: {parent_name}'}

        changed, missing = [], []
        for child_name in child_names:
            child = bpy.data.objects.get(child_name)
            if not child:
                missing.append(child_name)
                continue
            if parent is not None:
                child.parent = parent
                if keep_transform:
                    child.matrix_parent_inverse = parent.matrix_world.inverted()
            else:
                if keep_transform:
                    world = child.matrix_world.copy()
                    child.parent = None
                    child.matrix_world = world
                else:
                    child.parent = None
            changed.append(child_name)

        if missing:
            return {'success': False, 'error': f'Objects not found: {", ".join(missing)}',
                    'changed': changed}
        return {'success': True, 'parent': parent_name, 'changed': changed}

    def move_to_collection(
        self,
        names: list,
        collection_name: str,
        create: bool = True
    ) -> Dict[str, Any]:
        """Move objects into a collection, creating and linking it if needed."""
        coll = bpy.data.collections.get(collection_name)
        if coll is None:
            if not create:
                return {'success': False, 'error': f'Collection not found: {collection_name}'}
            coll = bpy.data.collections.new(collection_name)
            bpy.context.scene.collection.children.link(coll)

        moved, missing = [], []
        for name in names:
            obj = bpy.data.objects.get(name)
            if not obj:
                missing.append(name)
                continue
            for old in list(obj.users_collection):
                old.objects.unlink(obj)
            coll.objects.link(obj)
            moved.append(name)

        if missing:
            return {'success': False, 'error': f'Objects not found: {", ".join(missing)}',
                    'moved': moved}
        return {'success': True, 'collection': coll.name, 'moved': moved}

    def _undo_override(self):
        """Context override with a window, required by undo ops in timers."""
        wm = bpy.context.window_manager
        if wm and wm.windows:
            win = wm.windows[0]
            return bpy.context.temp_override(window=win, screen=win.screen)
        from contextlib import nullcontext
        return nullcontext()

    def checkpoint(self, label: str = 'Claude checkpoint') -> Dict[str, Any]:
        """Push an undo checkpoint so later changes can be rolled back."""
        if bpy.app.background:
            return {'success': False,
                    'error': 'Undo stack is disabled in background (headless) mode'}
        try:
            with self._undo_override():
                bpy.ops.ed.undo_push(message=str(label))
            return {'success': True, 'label': str(label)}
        except Exception as e:
            return {'success': False, 'error': f'{type(e).__name__}: {e}'}

    def undo(self, steps: int = 1) -> Dict[str, Any]:
        """Undo the last N steps."""
        return self._undo_redo('undo', steps)

    def redo(self, steps: int = 1) -> Dict[str, Any]:
        """Redo the last N undone steps."""
        return self._undo_redo('redo', steps)

    def _undo_redo(self, direction: str, steps: int) -> Dict[str, Any]:
        if bpy.app.background:
            return {'success': False,
                    'error': 'Undo stack is disabled in background (headless) mode'}
        steps = max(1, min(int(steps), 50))
        op = bpy.ops.ed.undo if direction == 'undo' else bpy.ops.ed.redo
        performed = 0
        try:
            with self._undo_override():
                for _ in range(steps):
                    if 'FINISHED' not in op():
                        break
                    performed += 1
        except Exception as e:
            if performed == 0:
                return {'success': False, 'error': f'{type(e).__name__}: {e}'}
        return {'success': True, 'direction': direction,
                'steps_requested': steps, 'steps_performed': performed}

    def _serialize_result(self, value: Any) -> Any:
        """Serialize a Python value for JSON."""
        if value is None:
            return None
        if isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, (list, tuple)):
            return [self._serialize_result(v) for v in value]
        if isinstance(value, dict):
            return {k: self._serialize_result(v) for k, v in value.items()}
        if hasattr(value, 'to_list'):  # mathutils types
            return value.to_list()
        if hasattr(value, '__iter__'):
            return [self._serialize_result(v) for v in value]
        # Fallback to string representation
        return str(value)
