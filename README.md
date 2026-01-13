# Claude Blender

AI-powered Blender control via Claude Code using the Model Context Protocol (MCP).

Control Blender through natural language, execute Python scripts, generate 3D content with local AI models, and render scenes - all from Claude Code.

## Features

### Core Features
- **Natural Language Control**: Control Blender via Claude Code commands
- **MCP Integration**: Full Model Context Protocol support with 20+ tools
- **JSON-RPC API**: Direct programmatic access to Blender over TCP
- **Scene Introspection**: Get detailed scene information in multiple formats
- **Remote Rendering**: Trigger renders and retrieve results

### Local AI Services (No External APIs Required)
- **Text-to-3D**: Generate 3D models using Shap-E (OpenAI) - runs locally
- **Image-to-3D**: Convert images to 3D with TripoSR (Stability AI) - runs locally
- **Procedural Generation**: Create rocks, trees, terrain, buildings algorithmically
- **ComfyUI Bridge**: Connect to local ComfyUI for Stable Diffusion workflows
- **Depth-to-Mesh**: Convert depth maps to 3D meshes

## Architecture

```
                         Claude Code CLI
                    "Create a low-poly dragon"
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MCP SERVER (Python)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Scene Tools │  │  AI Tools   │  │    Render Tools         │  │
│  │ - execute   │  │ - text_to_3d│  │    - render             │  │
│  │ - get_scene │  │ - img_to_3d │  │    - screenshot         │  │
│  │ - add_object│  │ - procedural│  │    - export             │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                    JSON-RPC over TCP (localhost:9876)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     BLENDER ADDON (Python)                       │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌───────────┐  │
│  │   Server   │  │  Executor  │  │ AI Router  │  │  Scene    │  │
│  │(Timer-poll)│  │(Main thrd) │  │ (Dispatch) │  │  Utils    │  │
│  └────────────┘  └────────────┘  └────────────┘  └───────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  LOCAL AI SERVICES                        │   │
│  │  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌───────────────┐  │   │
│  │  │ Shap-E  │ │ TripoSR  │ │Depth2Mesh│ │   ComfyUI    │  │   │
│  │  │ (Local) │ │ (Local)  │ │ (Local) │ │   Bridge     │  │   │
│  │  └─────────┘ └──────────┘ └─────────┘ └───────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites
- Blender 4.0+ (tested on 4.3)
- Python 3.10+
- pip (for MCP server)

### 1. Install the Blender Addon

**Option A: Install from folder**
1. In Blender, go to **Edit > Preferences > Add-ons**
2. Click **Install...**
3. Navigate to `claude_blender/blender_addon/` and select the folder
4. Enable the addon by checking the box

**Option B: Symlink for development**
```bash
# macOS
ln -s /path/to/claudeblender/claude_blender/blender_addon \
      ~/Library/Application\ Support/Blender/4.3/scripts/addons/claude_blender

# Linux
ln -s /path/to/claudeblender/claude_blender/blender_addon \
      ~/.config/blender/4.3/scripts/addons/claude_blender
```

### 2. Install the MCP Server

```bash
cd claude_blender
pip install -e .
```

Or install with AI dependencies:
```bash
pip install -e ".[ai]"
```

### 3. Configure Claude Code

Add to your `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "blender": {
      "command": "python3",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/claudeblender/claude_blender",
      "env": {
        "BLENDER_HOST": "127.0.0.1",
        "BLENDER_PORT": "9876"
      }
    }
  }
}
```

### 4. Start the Server in Blender

1. Open Blender
2. Press **N** to show the sidebar
3. Go to **Claude** tab
4. Click **Start Server**

## Usage

### Via Claude Code (MCP)

Simply ask Claude to interact with Blender:

```
"Add a red cube at position (0, 0, 2)"
"Create a simple scene with a sphere and a light"
"Render the current scene and show me the result"
"Generate a procedural rock using local AI"
```

### Via Python Client

```python
import socket
import json

# Connect
sock = socket.socket()
sock.connect(('127.0.0.1', 9876))

# Send request
request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "add_object",
    "params": {
        "object_type": "cube",
        "location": [0, 0, 2],
        "scale": [0.5, 0.5, 0.5]
    }
}
sock.send(json.dumps(request).encode() + b'\n')

# Get response
response = json.loads(sock.recv(4096).decode())
print(response)
```

### Test Client

```bash
# Run all tests
python claude_blender/test_client.py

# Interactive mode
python claude_blender/test_client.py -i
```

## MCP Tools

### Scene Tools
| Tool | Description |
|------|-------------|
| `blender_ping` | Health check |
| `blender_version` | Get Blender and addon versions |
| `blender_get_scene` | Get scene info (minimal/basic/detailed/full) |
| `blender_get_object` | Get detailed object information |

### Object Tools
| Tool | Description |
|------|-------------|
| `blender_add_object` | Add primitive (cube, sphere, etc.) |
| `blender_modify_object` | Transform object (location, rotation, scale) |
| `blender_delete_object` | Delete object by name |

### Code Execution
| Tool | Description |
|------|-------------|
| `blender_execute` | Execute arbitrary Python code in Blender |

### Rendering
| Tool | Description |
|------|-------------|
| `blender_screenshot` | Capture viewport |
| `blender_render` | Render scene with specified settings |

### Materials & Animation
| Tool | Description |
|------|-------------|
| `blender_create_material` | Create and assign materials |
| `blender_set_keyframe` | Set animation keyframes |
| `blender_set_frame_range` | Set animation frame range |

### Local AI Generation
| Tool | Description |
|------|-------------|
| `ai_generate_procedural` | Generate rocks, trees, terrain, buildings |
| `ai_local_text_to_3d` | Text-to-3D with Shap-E (local) |
| `ai_local_image_to_3d` | Image-to-3D with TripoSR (local) |
| `ai_comfyui_generate` | Generate images via local ComfyUI |
| `ai_check_local_services` | Check which AI services are available |

## Local AI Services

### Shap-E (Text-to-3D)
Requires:
```bash
pip install torch diffusers transformers trimesh
```

### TripoSR (Image-to-3D)
Requires:
```bash
pip install torch transformers trimesh rembg
```

### ComfyUI Bridge
Requires ComfyUI running locally on `http://127.0.0.1:8188`

### Procedural Generator
No additional dependencies - uses Blender's built-in modifiers.

## File Structure

```
claudeblender/
├── claude_blender/
│   ├── blender_addon/
│   │   ├── __init__.py          # Addon entry point (bl_info)
│   │   ├── core/
│   │   │   ├── server.py        # Timer-polled TCP server
│   │   │   ├── protocol.py      # JSON-RPC 2.0 handler
│   │   │   ├── executor.py      # Command execution
│   │   │   └── scene_utils.py   # Scene introspection
│   │   └── ai_services/
│   │       ├── base.py          # Base service classes
│   │       ├── local_text_to_3d.py    # Shap-E, Point-E, Procedural
│   │       ├── local_image_to_3d.py   # TripoSR, Depth2Mesh
│   │       └── comfyui_bridge.py      # ComfyUI integration
│   │
│   ├── mcp_server/
│   │   ├── __init__.py          # MCP entry point
│   │   ├── server.py            # FastMCP server with all tools
│   │   └── blender_client.py    # Async Blender client
│   │
│   ├── test_client.py           # Test script
│   ├── demo_creative.py         # Creative demo script
│   └── pyproject.toml           # Package configuration
│
├── LICENSE                      # MIT License
└── README.md                    # This file
```

## Technical Details

### Why Timer-Based Polling?
Blender's Python API is **NOT thread-safe**. Using `threading.Thread` will crash Blender. The timer system (`bpy.app.timers`) runs callbacks in the main thread, ensuring safe API access.

### Why JSON-RPC?
- Standard protocol with good tooling
- Bidirectional communication
- Built-in error handling
- Easy to debug and test

### Why Separate MCP Server?
- MCP runs outside Blender process
- Can restart without affecting Blender
- Clean separation of concerns
- Easier testing

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## Credits

Created with Claude Code by Anthropic.
