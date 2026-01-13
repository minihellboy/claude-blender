# Claude Code Blender Plugin - Technical Analysis

## Executive Summary

This document provides a deep technical analysis for building a Claude Code plugin for Blender 4.3.2, using only Blender's native Python API without third-party dependencies.

---

## 1. Environment Analysis

### Blender Instance
- **Version**: Blender 4.3.2 (running as PID 45544)
- **Platform**: macOS Darwin (ARM64)
- **Python**: Bundled Python 3.11
- **Location**: `/Applications/Blender.app/Contents/MacOS/Blender`

### User Configuration Paths
```
~/Library/Application Support/Blender/4.3/
├── config/
│   ├── userpref.blend      # User preferences
│   ├── bookmarks.txt
│   └── platform_support.txt
├── extensions/             # Extension repository cache
└── scripts/               # User scripts (to be created)
    ├── addons/            # User addons
    └── startup/           # Auto-run scripts
```

---

## 2. Critical Constraints

### Threading Limitation
**Blender Python is NOT thread-safe.** From the official docs:
> "Python Threads are Not Supported"

This means:
- Cannot use `threading.Thread` for background socket servers
- Cannot use `asyncio` event loops directly
- All code must execute in Blender's main thread

### Solution: Timer-based Polling
Use `bpy.app.timers.register()` to periodically check for external commands:
```python
def check_commands():
    # Non-blocking check for incoming data
    # Execute in main thread
    return 0.1  # Re-run every 100ms

bpy.app.timers.register(check_commands)
```

### Context Requirements
- Operators require proper context (`bpy.context`)
- Some operations only work in specific modes (Edit, Object, Pose)
- Use `context.temp_override()` for context manipulation:
```python
with bpy.context.temp_override(active_object=obj, selected_objects=[obj]):
    bpy.ops.object.delete()
```

---

## 3. IPC Architecture Options

### Option A: TCP Socket Server (Recommended)

```
┌─────────────────┐     JSON-RPC/TCP     ┌──────────────────────┐
│   Claude Code   │◄──────────────────►  │   Blender Addon      │
│   (External)    │    localhost:9876    │   (Socket Server)    │
└─────────────────┘                      └──────────────────────┘
                                                   │
                                         ┌─────────▼─────────┐
                                         │  Timer Callback   │
                                         │  (Main Thread)    │
                                         └─────────┬─────────┘
                                                   │
                                         ┌─────────▼─────────┐
                                         │  bpy.ops/bpy.data │
                                         │  Execute Commands │
                                         └───────────────────┘
```

**Implementation Pattern:**
```python
import socket
import json
import bpy

class BlenderCommandServer:
    def __init__(self, port=9876):
        self.port = port
        self.server = None
        self.conn = None

    def start(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.setblocking(False)  # Non-blocking!
        self.server.bind(('127.0.0.1', self.port))
        self.server.listen(1)
        bpy.app.timers.register(self._poll, persistent=True)

    def _poll(self):
        try:
            if self.conn is None:
                self.conn, addr = self.server.accept()
                self.conn.setblocking(False)

            data = self.conn.recv(4096)
            if data:
                command = json.loads(data.decode())
                result = self._execute(command)
                self.conn.send(json.dumps(result).encode())
        except BlockingIOError:
            pass  # No data available
        except Exception as e:
            pass  # Handle errors gracefully

        return 0.05  # Poll every 50ms

    def _execute(self, command):
        # Execute Python code in main thread context
        try:
            exec_globals = {'bpy': bpy, 'result': None}
            exec(command['code'], exec_globals)
            return {'status': 'ok', 'result': str(exec_globals.get('result'))}
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
```

**Pros:**
- Real-time bidirectional communication
- Low latency (~50ms)
- Standard protocol (JSON-RPC compatible)

**Cons:**
- Port conflicts possible
- Requires socket cleanup on exit

---

### Option B: File-based IPC

```
┌─────────────────┐                      ┌──────────────────────┐
│   Claude Code   │──write──►/tmp/cmd────│   Blender Addon      │
│   (External)    │◄─read───/tmp/resp◄───│   (File Watcher)     │
└─────────────────┘                      └──────────────────────┘
```

**Implementation Pattern:**
```python
import os
import json
import bpy

COMMAND_FILE = '/tmp/blender_claude_cmd.json'
RESPONSE_FILE = '/tmp/blender_claude_resp.json'

def watch_command_file():
    if os.path.exists(COMMAND_FILE):
        try:
            with open(COMMAND_FILE, 'r') as f:
                command = json.load(f)
            os.remove(COMMAND_FILE)  # Consume the command

            result = execute_command(command)

            with open(RESPONSE_FILE, 'w') as f:
                json.dump(result, f)
        except Exception as e:
            with open(RESPONSE_FILE, 'w') as f:
                json.dump({'error': str(e)}, f)

    return 0.1  # Check every 100ms
```

**Pros:**
- Simple implementation
- No port conflicts
- Works across security boundaries
- Easy debugging (inspect files)

**Cons:**
- Higher latency (file I/O)
- Filesystem cleanup needed
- Potential race conditions

---

### Option C: Unix Domain Socket

```python
import socket

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.bind('/tmp/blender_claude.sock')
```

**Pros:**
- Faster than TCP (no network stack)
- No port conflicts
- Secure (filesystem permissions)

**Cons:**
- Unix-only (not Windows)
- Requires cleanup on crash

---

## 4. Addon Architecture

### File Structure
```
claude_code_bridge/
├── __init__.py           # Main addon entry point
├── server.py             # Socket/IPC server
├── executor.py           # Command execution engine
├── protocol.py           # JSON-RPC message handling
└── blender_manifest.toml # Blender 4.x extension manifest
```

### Addon Entry Point (`__init__.py`)
```python
bl_info = {
    "name": "Claude Code Bridge",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (4, 3, 0),
    "location": "View3D > Sidebar > Claude",
    "description": "Bridge between Claude Code and Blender",
    "category": "Development",
}

import bpy
from . import server

class CLAUDE_PT_panel(bpy.types.Panel):
    bl_label = "Claude Code Bridge"
    bl_idname = "CLAUDE_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Claude'

    def draw(self, context):
        layout = self.layout
        layout.operator("claude.start_server")
        layout.operator("claude.stop_server")
        layout.label(text=f"Port: {server.PORT}")
        layout.label(text=f"Status: {'Running' if server.is_running() else 'Stopped'}")

class CLAUDE_OT_start_server(bpy.types.Operator):
    bl_idname = "claude.start_server"
    bl_label = "Start Server"

    def execute(self, context):
        server.start()
        return {'FINISHED'}

class CLAUDE_OT_stop_server(bpy.types.Operator):
    bl_idname = "claude.stop_server"
    bl_label = "Stop Server"

    def execute(self, context):
        server.stop()
        return {'FINISHED'}

classes = [CLAUDE_PT_panel, CLAUDE_OT_start_server, CLAUDE_OT_stop_server]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    # Auto-start server
    server.start()

def unregister():
    server.stop()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
```

---

## 5. Command Protocol

### JSON-RPC 2.0 Compatible Messages

**Request:**
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "execute",
    "params": {
        "code": "bpy.ops.mesh.primitive_cube_add(location=(0, 0, 2))",
        "context": {
            "mode": "OBJECT"
        }
    }
}
```

**Response (Success):**
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "status": "ok",
        "output": "Created Cube at (0, 0, 2)"
    }
}
```

**Response (Error):**
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "error": {
        "code": -32000,
        "message": "RuntimeError: Operator requires EDIT mode"
    }
}
```

### Supported Methods
| Method | Description |
|--------|-------------|
| `execute` | Execute arbitrary Python code |
| `get_scene_info` | Return scene objects, materials, etc. |
| `get_object_info` | Return specific object properties |
| `screenshot` | Capture viewport and return path |
| `ping` | Health check |

---

## 6. Key Blender APIs for Integration

### Scene Access
```python
# All objects
bpy.data.objects

# Active object
bpy.context.active_object

# Selected objects
bpy.context.selected_objects

# Scene
bpy.context.scene
```

### Object Manipulation
```python
# Create cube
bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))

# Move object
obj = bpy.context.active_object
obj.location = (1, 2, 3)
obj.rotation_euler = (0, 0, 3.14159)
obj.scale = (2, 2, 2)

# Delete
bpy.ops.object.delete()
```

### Materials
```python
# Create material
mat = bpy.data.materials.new(name="Material")
mat.use_nodes = True

# Assign to object
obj.data.materials.append(mat)
```

### Rendering
```python
# Set render settings
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.render.filepath = '/tmp/render.png'

# Render
bpy.ops.render.render(write_still=True)
```

---

## 7. Claude Code Integration

### MCP Server Approach (Recommended)
Build an MCP (Model Context Protocol) server that Claude Code can connect to:

```python
# Claude Code can use MCP tools like:
# - blender_execute: Run Python code
# - blender_add_object: Add primitives
# - blender_render: Render scene
# - blender_screenshot: Capture viewport
```

### Direct CLI Integration
Use hooks or custom commands:
```bash
# In .claude-code/hooks.json
{
    "pre-execute": [
        "python3 /path/to/blender_sync.py"
    ]
}
```

---

## 8. Security Considerations

1. **Localhost Only**: Bind to 127.0.0.1, never 0.0.0.0
2. **Code Execution**: The server executes arbitrary Python - only allow trusted connections
3. **No eval() on untrusted input**: Validate/sanitize commands
4. **Rate Limiting**: Prevent DoS via command flooding
5. **Timeout**: Kill long-running commands

---

## 9. Testing Strategy

### Unit Tests (External)
```python
import socket
import json

def test_ping():
    sock = socket.socket()
    sock.connect(('127.0.0.1', 9876))
    sock.send(json.dumps({"method": "ping"}).encode())
    response = json.loads(sock.recv(4096).decode())
    assert response["result"] == "pong"
```

### Integration Test (In Blender)
```python
# Run in Blender's Python console
import bpy
bpy.ops.claude.start_server()
# Then test from external script
```

---

## 10. Next Steps

1. **Create minimal addon** with socket server
2. **Test basic communication** from external Python
3. **Add command protocol** with proper error handling
4. **Build Claude Code MCP server** wrapper
5. **Add UI panel** for status/control
6. **Implement screenshot/render** capture
7. **Add scene introspection** commands

---

## References

- [Blender Python API](https://docs.blender.org/api/current/index.html)
- [bpy.app.timers](https://docs.blender.org/api/current/bpy.app.timers.html)
- [Operator Development](https://docs.blender.org/api/current/bpy.types.Operator.html)
- [Addon Tutorial](https://docs.blender.org/manual/en/latest/advanced/scripting/addon_tutorial.html)
