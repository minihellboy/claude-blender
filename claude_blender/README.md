# Claude Blender - Core Package

This directory contains the core Claude Blender package.

See the main [README.md](../README.md) in the parent directory for full documentation.

## Quick Start

### Install
From the repository root (uv project):
```bash
uv sync
```

### Test Connection
From the repository root:
```bash
uv run python claude_blender/test_client.py
```

### Interactive Mode
```bash
uv run python claude_blender/test_client.py -i
```

## Package Structure

- `blender_addon/` - The Blender addon (install in Blender)
- `claude_blender_mcp/` - MCP server for Claude Code integration (MCP SDK v2)
- `test_client.py` - Test script for verifying connection
- `demo_creative.py` - Creative demo showcasing capabilities
