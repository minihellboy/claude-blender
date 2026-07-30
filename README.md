# Claude Blender

[![CI](https://github.com/minihellboy/claude-blender/actions/workflows/ci.yml/badge.svg)](https://github.com/minihellboy/claude-blender/actions/workflows/ci.yml)

AI-powered Blender control via Claude Code using the Model Context Protocol (MCP).

Control Blender through natural language, execute Python scripts, generate 3D content with local AI models, and render scenes - all from Claude Code.

![Product shot rendered by Claude via MCP](examples/images/product-final.png)
*Rendered end-to-end by Claude through the MCP tools — see [examples/](examples/README.md).*

## Features

### Core Features
- **Natural Language Control**: Control Blender via Claude Code commands
- **MCP Integration**: Built on MCP SDK v2 (protocol 2026-07-28) — 27 tools, 3 resources, and workflow prompts, with tool annotations and structured output
- **Visual Feedback Loop**: Screenshots and renders come back inline so Claude can see, critique, and iterate on its own work
- **Import / Export**: OBJ, STL, PLY, FBX, glTF/GLB, USD, Collada, Alembic
- **Animation Rendering**: MP4 turntables and image sequences with inline preview stills
- **Camera Framing**: One call positions and aims a camera to frame any object
- **Undo Checkpoints**: Checkpoint before risky edits, roll back when they go wrong
- **JSON-RPC API**: Direct programmatic access to Blender over TCP
- **Scene Introspection**: Get detailed scene information in multiple formats

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
- [uv](https://docs.astral.sh/uv/) (manages Python 3.10+ and dependencies)

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

This is a uv project (root `pyproject.toml` + `uv.lock`, built on `mcp>=2.0.0`, MCP protocol revision 2026-07-28). From the repo root:

```bash
uv sync
```

That creates `.venv/` and installs the pinned dependencies. Local AI features (Shap-E, TripoSR, etc.) have their own optional dependencies — see [Local AI Services](#local-ai-services) below.

### 3. Configure Claude Code

This repository ships a project-scoped `.mcp.json` at the repo root; opening the repo in Claude Code will prompt you to enable the `blender` server. It launches the server with `uv run claude-blender`, so it works as soon as `uv sync` has been run (uv also re-syncs automatically on launch).

To register it user-wide instead (available in every project):

```bash
claude mcp add --scope user blender \
  --env BLENDER_HOST=127.0.0.1 --env BLENDER_PORT=9876 \
  -- uv run --project /path/to/claude-blender claude-blender
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

### Headless (no GUI)

Run a background Blender that serves the addon — renders, imports/exports,
and all object tools work; only viewport screenshots and undo need the GUI:

```bash
blender --background --python scripts/headless_blender.py -- --port 9876
```

### Tests

```bash
uv run pytest -m "not live"            # full suite against a fake Blender server
BLENDER_LIVE=1 uv run pytest -m live   # against a real Blender on port 9876
```

The fake server compiles every generated `execute` payload, so quoting or
injection regressions fail in CI without needing Blender.

### Test Client

```bash
# Run all tests (talks JSON-RPC directly to the addon)
uv run python claude_blender/test_client.py

# Interactive mode
uv run python claude_blender/test_client.py -i
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
| `blender_screenshot` | Capture viewport — returns the image inline so Claude can see it |
| `blender_render` | Render scene — returns the image inline so Claude can see it |
| `blender_render_animation` | Render MP4 video or PNG sequence — returns preview stills inline |

### Camera
| Tool | Description |
|------|-------------|
| `blender_frame_camera` | Position and aim a camera to frame objects (fit math included) |

### Import / Export
| Tool | Description |
|------|-------------|
| `blender_import_model` | Import OBJ, STL, PLY, FBX, glTF/GLB, USD, DAE, ABC |
| `blender_export` | Export scene or selected objects to any of the above |

### Modifiers & Organization
| Tool | Description |
|------|-------------|
| `blender_modifier` | Add, apply, or remove modifiers (SUBSURF, BOOLEAN, ARRAY, ...) |
| `blender_duplicate` | Duplicate N times with cumulative offset (one-call arrays) |
| `blender_organize` | Parent/unparent objects, move to collections |

### Undo
| Tool | Description |
|------|-------------|
| `blender_checkpoint` | Push an undo checkpoint before risky edits |
| `blender_undo` | Undo/redo N steps |

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

### Resources & Prompts
| Item | Description |
|------|-------------|
| `blender://scene` (resource) | Live JSON snapshot of the scene graph |
| `blender://object/{name}` (resource) | Full details of one object (transform, mesh stats, modifiers) |
| `blender://render/latest` (resource) | The most recent render/screenshot as PNG |
| `studio_lighting` (prompt) | Guided three-point lighting workflow |
| `turntable_animation` (prompt) | Guided 360° turntable animation workflow |

### Project Skills

Working inside this repo, three slash commands encode complete workflows
(each is a walkthrough in [examples/](examples/README.md)):

```
/blender-iterate <visual goal>       # render–critique–adjust loop
/blender-studio-shot <object>        # lighting + framing + final render
/blender-turntable <object> [secs]   # 360° turntable video
```

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
claude-blender/
├── claude_blender/
│   ├── blender_addon/
│   │   ├── __init__.py          # Addon entry point (bl_info, RPC registry)
│   │   ├── core/
│   │   │   ├── server.py        # Timer-polled TCP server
│   │   │   ├── protocol.py      # JSON-RPC 2.0 handler
│   │   │   ├── executor.py      # Objects, modifiers, duplicate, undo
│   │   │   ├── scene_utils.py   # Introspection, render, render_animation
│   │   │   ├── io_utils.py      # Import/export (format from extension)
│   │   │   └── camera_utils.py  # frame_camera fit math (headless-safe)
│   │   └── ai_services/
│   │       ├── base.py          # Base service classes
│   │       ├── local_text_to_3d.py    # Shap-E, Point-E, Procedural
│   │       ├── local_image_to_3d.py   # TripoSR, Depth2Mesh
│   │       └── comfyui_bridge.py      # ComfyUI integration
│   │
│   ├── claude_blender_mcp/
│   │   ├── __init__.py          # MCP entry point
│   │   ├── server.py            # MCPServer (MCP SDK v2): 27 tools, resources, prompts
│   │   └── blender_client.py    # Async Blender client
│   │
│   ├── test_client.py           # Raw JSON-RPC test script
│   └── demo_creative.py         # Creative demo script
│
├── tests/                       # pytest suite (fake Blender + live markers)
├── scripts/headless_blender.py  # Serve the addon from blender --background
├── examples/                    # Walkthroughs with real committed renders
├── .claude/skills/              # /blender-iterate, /blender-studio-shot, /blender-turntable
├── .github/workflows/ci.yml     # uv + pytest on 3.11/3.13
├── CLAUDE.md                    # Architecture & invariants for agents/devs
├── pyproject.toml               # uv project / package configuration
├── uv.lock                      # Locked dependencies (managed by uv)
├── .mcp.json                    # Project-scoped Claude Code MCP config
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
