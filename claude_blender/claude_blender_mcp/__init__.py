# SPDX-License-Identifier: MIT
"""
Claude Blender MCP Server

Model Context Protocol server for Claude Code integration with Blender.
Built on MCP SDK v2 (protocol revision 2026-07-28).
"""

__version__ = "0.2.0"

from .server import main, mcp
from .blender_client import BlenderClient

__all__ = ['main', 'mcp', 'BlenderClient', '__version__']
