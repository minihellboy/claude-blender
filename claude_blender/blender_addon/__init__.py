# SPDX-License-Identifier: MIT
"""
Claude Blender - AI-Powered Blender Integration

A comprehensive plugin for controlling Blender via Claude Code,
with integrations for text-to-3D, image-to-3D, AI textures, and more.
"""

bl_info = {
    "name": "Claude Blender",
    "author": "Claude Code",
    "version": (0, 5, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Claude",
    "description": "AI-powered Blender control via Claude Code",
    "doc_url": "https://github.com/minihellboy/claude-blender",
    "category": "Development",
}

import bpy
from bpy.props import IntProperty, BoolProperty
from bpy.types import Operator, Panel, AddonPreferences

# Import core modules
from .core.server import BlenderServer, get_server
from .core.protocol import JSONRPCHandler
from .core.executor import CommandExecutor
from .core.scene_utils import SceneSerializer
from .core import io_utils, camera_utils, visual_utils


# Global instances
_handler: JSONRPCHandler = None
_executor: CommandExecutor = None
_scene_utils: SceneSerializer = None


def _setup_handler():
    """Set up the JSON-RPC handler with all methods."""
    global _handler, _executor, _scene_utils

    _executor = CommandExecutor()
    _scene_utils = SceneSerializer()
    _handler = JSONRPCHandler()

    # Register methods
    _handler.register_methods({
        # Basic methods
        'ping': lambda: 'pong',
        'version': lambda: {
            'addon_version': '.'.join(str(v) for v in bl_info['version']),
            'blender_version': bpy.app.version_string,
        },

        # Code execution
        'execute': lambda code, capture_output=True: _executor.execute_python(code, capture_output),
        'operator': lambda operator, **kwargs: _executor.execute_operator(operator, **kwargs),

        # Object manipulation
        'add_object': lambda **kwargs: _executor.add_object(**kwargs),
        'modify_object': lambda **kwargs: _executor.modify_object(**kwargs),
        'delete_object': lambda name: _executor.delete_object(name),

        # Scene info
        'get_scene': lambda detail_level='basic': _scene_utils.get_scene_info(detail_level),
        'get_object': lambda name: _scene_utils.get_object_info(name),
        'scene_state': lambda **kwargs: _scene_utils.scene_state(**kwargs),

        # Rendering
        'screenshot': lambda **kwargs: _scene_utils.capture_viewport(**kwargs),
        'render': lambda **kwargs: _scene_utils.render_image(**kwargs),
        'render_animation': lambda **kwargs: _scene_utils.render_animation(**kwargs),
        'render_views': lambda **kwargs: visual_utils.render_views(**kwargs),
        'contact_sheet': lambda **kwargs: visual_utils.contact_sheet(**kwargs),
        'encode_video': lambda **kwargs: visual_utils.encode_video(**kwargs),

        # File
        'save_file': lambda **kwargs: _scene_utils.save_file(**kwargs),

        # Import / export
        'import_model': lambda **kwargs: io_utils.import_model(**kwargs),
        'export_model': lambda **kwargs: io_utils.export_model(**kwargs),

        # Camera
        'frame_camera': lambda **kwargs: camera_utils.frame_camera(**kwargs),

        # Modifiers
        'add_modifier': lambda **kwargs: _executor.add_modifier(**kwargs),
        'apply_modifier': lambda **kwargs: _executor.apply_modifier(**kwargs),
        'remove_modifier': lambda **kwargs: _executor.remove_modifier(**kwargs),

        # Batch / organization
        'duplicate_object': lambda **kwargs: _executor.duplicate_object(**kwargs),
        'set_parent': lambda **kwargs: _executor.set_parent(**kwargs),
        'move_to_collection': lambda **kwargs: _executor.move_to_collection(**kwargs),

        # Undo stack
        'checkpoint': lambda **kwargs: _executor.checkpoint(**kwargs),
        'undo': lambda **kwargs: _executor.undo(**kwargs),
        'redo': lambda **kwargs: _executor.redo(**kwargs),
    })

    # Set handler on server
    server = get_server()
    server.set_request_handler(_handler.handle)


# ============================================================================
# Addon Preferences
# ============================================================================

def _auto_start_updated(self, context):
    """Apply the auto-start toggle immediately instead of on next restart."""
    if self.auto_start:
        server = get_server()
        if not server.is_running:
            _setup_handler()
            server.port = self.port
            server.start()


class ClaudeBlenderPreferences(AddonPreferences):
    bl_idname = __name__

    port: IntProperty(
        name="Server Port",
        description="TCP port for the command server",
        default=9876,
        min=1024,
        max=65535,
    )

    auto_start: BoolProperty(
        name="Auto-start Server",
        description="Automatically start the server when Blender opens",
        default=True,
        update=_auto_start_updated,
    )

    def draw(self, context):
        layout = self.layout

        # Server settings
        box = layout.box()
        box.label(text="Server Settings", icon='NETWORK_DRIVE')
        box.prop(self, "port")
        box.prop(self, "auto_start")


# ============================================================================
# Operators
# ============================================================================

class CLAUDE_OT_start_server(Operator):
    """Start the Claude Blender server"""
    bl_idname = "claude.start_server"
    bl_label = "Start Server"
    bl_options = {'REGISTER'}

    def execute(self, context):
        prefs = context.preferences.addons[__name__].preferences
        server = get_server()

        # The server is process-global and survives file loads; ask IT.
        if server.is_running:
            self.report({'WARNING'}, "Server is already running")
            return {'CANCELLED'}

        # Ensure handler is set up
        _setup_handler()
        server.port = prefs.port

        if server.start():
            self.report({'INFO'}, f"Server started on port {prefs.port}")
            return {'FINISHED'}

        reason = server.last_error or "unknown error"
        if "address already in use" in reason.lower():
            reason += f" - another process is using port {prefs.port}; " \
                      "change it in the addon preferences"
        self.report({'ERROR'}, f"Failed to start server on port {prefs.port}: {reason}")
        return {'CANCELLED'}


class CLAUDE_OT_stop_server(Operator):
    """Stop the Claude Blender server"""
    bl_idname = "claude.stop_server"
    bl_label = "Stop Server"
    bl_options = {'REGISTER'}

    def execute(self, context):
        server = get_server()

        if not server.is_running:
            self.report({'WARNING'}, "Server is not running")
            return {'CANCELLED'}

        server.stop()
        self.report({'INFO'}, "Server stopped")
        return {'FINISHED'}


class CLAUDE_OT_test_connection(Operator):
    """Test the server connection"""
    bl_idname = "claude.test_connection"
    bl_label = "Test Connection"
    bl_options = {'REGISTER'}

    def execute(self, context):
        import socket
        import json

        prefs = context.preferences.addons[__name__].preferences

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect(('127.0.0.1', prefs.port))

            # Send ping
            request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
            sock.send(request.encode() + b'\n')

            # Get response
            response = sock.recv(4096).decode()
            sock.close()

            self.report({'INFO'}, f"Connection OK: {response[:50]}")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Connection failed: {e}")
            return {'CANCELLED'}


# ============================================================================
# Panels
# ============================================================================

class CLAUDE_PT_main_panel(Panel):
    """Main panel for Claude Blender"""
    bl_label = "Claude Blender"
    bl_idname = "CLAUDE_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Claude'

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__name__].preferences

        # Status comes from the process-global server, never from scene
        # state - the server survives File > New / Open, scene props don't.
        server = get_server()
        running = server.is_running

        box = layout.box()
        row = box.row()
        if running:
            row.label(text="Status: Running", icon='CHECKMARK')
        else:
            row.label(text="Status: Stopped", icon='X')

        row = box.row()
        row.label(text=f"Port: {prefs.port}")

        if running:
            row = box.row()
            row.label(text=f"Clients: {server.client_count}")
        else:
            row = box.row()
            row.label(text="Claude Code needs this running", icon='INFO')

        # Controls
        layout.separator()

        if running:
            layout.operator("claude.stop_server", icon='PAUSE')
        else:
            layout.operator("claude.start_server", icon='PLAY')

        layout.operator("claude.test_connection", icon='LINKED')


class CLAUDE_PT_connection_panel(Panel):
    """Connection info panel"""
    bl_label = "Connection Info"
    bl_idname = "CLAUDE_PT_connection_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Claude'
    bl_parent_id = "CLAUDE_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__name__].preferences

        box = layout.box()
        box.label(text="Connect via TCP:", icon='INFO')
        box.label(text=f"  Host: 127.0.0.1")
        box.label(text=f"  Port: {prefs.port}")

        layout.separator()

        box = layout.box()
        box.label(text="Test with Python:", icon='CONSOLE')
        col = box.column(align=True)
        col.scale_y = 0.8
        col.label(text="import socket, json")
        col.label(text="s = socket.socket()")
        col.label(text=f"s.connect(('127.0.0.1', {prefs.port}))")
        col.label(text='s.send(b\'{"jsonrpc":"2.0",')
        col.label(text='  "method":"ping","id":1}\\n\')')


# ============================================================================
# Registration
# ============================================================================

classes = [
    ClaudeBlenderPreferences,
    CLAUDE_OT_start_server,
    CLAUDE_OT_stop_server,
    CLAUDE_OT_test_connection,
    CLAUDE_PT_main_panel,
    CLAUDE_PT_connection_panel,
]


def _auto_start():
    """Delayed auto-start to ensure Blender is fully loaded."""
    try:
        prefs = bpy.context.preferences.addons[__name__].preferences
        if prefs.auto_start and not get_server().is_running:
            _setup_handler()
            server = get_server()
            server.port = prefs.port
            if server.start():
                print(f"[Claude Blender] Auto-started on port {prefs.port}")
    except Exception as e:
        print(f"[Claude Blender] Auto-start failed: {e}")
    return None  # Don't repeat


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    # Schedule auto-start check
    prefs = bpy.context.preferences.addons.get(__name__)
    if prefs and prefs.preferences.auto_start:
        bpy.app.timers.register(_auto_start, first_interval=1.0)

    print("[Claude Blender] Addon registered")


def unregister():
    # Stop server if running
    try:
        server = get_server()
        server.stop()
    except:
        pass

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    print("[Claude Blender] Addon unregistered")


if __name__ == "__main__":
    register()
