# SPDX-License-Identifier: MIT
"""
Client for communicating with the Blender addon server.
"""

import socket
import json
from typing import Any, Dict, Optional
import asyncio


class BlenderClient:
    """
    Async client for communicating with Claude Blender addon.

    Uses JSON-RPC 2.0 over TCP.
    """

    def __init__(self, host: str = '127.0.0.1', port: int = 9876):
        self.host = host
        self.port = port
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._id = 0
        self._lock = asyncio.Lock()

    async def connect(self) -> bool:
        """Connect to the Blender server."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=5.0
            )
            return True
        except Exception as e:
            print(f"[BlenderClient] Connection failed: {e}")
            return False

    async def disconnect(self):
        """Disconnect from the server."""
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except:
                pass
        self._reader = None
        self._writer = None

    async def ensure_connected(self) -> bool:
        """Ensure we're connected, reconnecting if necessary."""
        if self._writer is None or self._writer.is_closing():
            return await self.connect()
        return True

    async def call(self, method: str, **params) -> Dict[str, Any]:
        """
        Call a JSON-RPC method on the Blender server.

        Args:
            method: Method name
            **params: Method parameters

        Returns:
            Response dict with 'result' or 'error'
        """
        async with self._lock:
            if not await self.ensure_connected():
                return {"error": {"code": -32000, "message": "Not connected to Blender"}}

            self._id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self._id,
                "method": method,
                "params": params if params else {}
            }

            try:
                # Send request
                data = json.dumps(request).encode() + b'\n'
                self._writer.write(data)
                await self._writer.drain()

                # Read response
                response_data = await asyncio.wait_for(
                    self._reader.readline(),
                    timeout=30.0
                )

                if not response_data:
                    await self.disconnect()
                    return {"error": {"code": -32000, "message": "Connection closed"}}

                return json.loads(response_data.decode())

            except asyncio.TimeoutError:
                return {"error": {"code": -32000, "message": "Request timeout"}}
            except Exception as e:
                await self.disconnect()
                return {"error": {"code": -32000, "message": str(e)}}

    async def ping(self) -> bool:
        """Check if Blender is reachable."""
        response = await self.call("ping")
        return response.get("result") == "pong"

    async def execute(self, code: str) -> Dict[str, Any]:
        """Execute Python code in Blender."""
        return await self.call("execute", code=code)

    async def get_scene(self, detail_level: str = "basic") -> Dict[str, Any]:
        """Get scene information."""
        return await self.call("get_scene", detail_level=detail_level)

    async def add_object(
        self,
        object_type: str,
        name: Optional[str] = None,
        location: tuple = (0, 0, 0),
        **kwargs
    ) -> Dict[str, Any]:
        """Add an object to the scene."""
        return await self.call(
            "add_object",
            object_type=object_type,
            name=name,
            location=list(location),
            **kwargs
        )

    async def modify_object(self, name: str, **kwargs) -> Dict[str, Any]:
        """Modify an object."""
        return await self.call("modify_object", name=name, **kwargs)

    async def delete_object(self, name: str) -> Dict[str, Any]:
        """Delete an object."""
        return await self.call("delete_object", name=name)

    async def get_object(self, name: str) -> Dict[str, Any]:
        """Get object information."""
        return await self.call("get_object", name=name)

    async def screenshot(self, filepath: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Capture viewport screenshot."""
        return await self.call("screenshot", filepath=filepath, **kwargs)

    async def render(self, filepath: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Render the scene."""
        return await self.call("render", filepath=filepath, **kwargs)


# Global client instance
_client: Optional[BlenderClient] = None


def get_client(host: str = '127.0.0.1', port: int = 9876) -> BlenderClient:
    """Get or create the global client instance."""
    global _client
    if _client is None:
        _client = BlenderClient(host, port)
    return _client
