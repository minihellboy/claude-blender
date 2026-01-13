# SPDX-License-Identifier: MIT
"""
Claude Blender MCP Server

Model Context Protocol server for Claude Code integration with Blender.
"""

from .server import main, mcp
from .blender_client import BlenderClient

__all__ = ['main', 'mcp', 'BlenderClient']
