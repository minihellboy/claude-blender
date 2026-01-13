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

        # Execute operator
        result = self.execute_operator(
            operator,
            location=location,
            rotation=rotation,
            scale=scale,
            **kwargs
        )

        if not result['success']:
            return {
                'success': False,
                'object_name': None,
                'error': result['error']
            }

        # Get created object and rename if needed
        obj = bpy.context.active_object
        if obj and name:
            obj.name = name

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
