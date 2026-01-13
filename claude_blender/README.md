# Claude Blender - Core Package

This directory contains the core Claude Blender package.

See the main [README.md](../README.md) in the parent directory for full documentation.

## Quick Start

### Install
```bash
pip install -e .
```

### Test Connection
```bash
python test_client.py
```

### Interactive Mode
```bash
python test_client.py -i
```

## Package Structure

- `blender_addon/` - The Blender addon (install in Blender)
- `mcp_server/` - MCP server for Claude Code integration
- `test_client.py` - Test script for verifying connection
- `demo_creative.py` - Creative demo showcasing capabilities
