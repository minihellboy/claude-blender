#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Test client for Claude Blender addon.

Run this script to test communication with Blender.
Make sure the addon is enabled and server is started in Blender first.
"""

import socket
import json
import sys
from typing import Any, Dict, Optional


class BlenderClient:
    """Simple client to communicate with Claude Blender addon."""

    def __init__(self, host: str = '127.0.0.1', port: int = 9876):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self._id = 0

    def connect(self):
        """Connect to the Blender server."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(10.0)
        self.socket.connect((self.host, self.port))
        print(f"Connected to {self.host}:{self.port}")

    def disconnect(self):
        """Disconnect from the server."""
        if self.socket:
            self.socket.close()
            self.socket = None

    def call(self, method: str, **params) -> Dict[str, Any]:
        """
        Call a JSON-RPC method.

        Args:
            method: Method name
            **params: Method parameters

        Returns:
            Response dict
        """
        self._id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": method,
            "params": params if params else {}
        }

        # Send request (sendall: send() may write only part of the payload)
        self.socket.sendall(json.dumps(request).encode() + b'\n')

        # Receive response
        response_data = b''
        while b'\n' not in response_data:
            chunk = self.socket.recv(65536)
            if not chunk:
                raise ConnectionError("Connection closed")
            response_data += chunk

        # Parse response
        response = json.loads(response_data.decode().strip())
        return response

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()


def test_ping(client: BlenderClient):
    """Test ping method."""
    print("\n=== Testing ping ===")
    response = client.call("ping")
    print(f"Response: {response}")
    assert response.get("result") == "pong", "Ping failed!"
    print("PASSED")


def test_version(client: BlenderClient):
    """Test version method."""
    print("\n=== Testing version ===")
    response = client.call("version")
    print(f"Response: {response}")
    assert "result" in response, "Version failed!"
    print(f"Addon version: {response['result']['addon_version']}")
    print(f"Blender version: {response['result']['blender_version']}")
    print("PASSED")


def test_get_scene(client: BlenderClient):
    """Test get_scene method."""
    print("\n=== Testing get_scene ===")
    response = client.call("get_scene", detail_level="basic")
    print(f"Response: {json.dumps(response, indent=2)}")
    assert "result" in response, "Get scene failed!"
    print(f"Scene: {response['result']['name']}")
    print(f"Objects: {response['result']['object_count']}")
    print("PASSED")


def test_add_object(client: BlenderClient):
    """Test add_object method."""
    print("\n=== Testing add_object (cube) ===")
    response = client.call(
        "add_object",
        object_type="cube",
        name="TestCube",
        location=(2, 0, 0),
        scale=(0.5, 0.5, 0.5)
    )
    print(f"Response: {json.dumps(response, indent=2)}")
    assert response.get("result", {}).get("success"), "Add object failed!"
    print(f"Created: {response['result']['object_name']}")
    print("PASSED")


def test_execute(client: BlenderClient):
    """Test execute method."""
    print("\n=== Testing execute (Python code) ===")
    code = """
import bpy
print("Hello from Blender!")
__result__ = len(bpy.data.objects)
"""
    response = client.call("execute", code=code)
    print(f"Response: {json.dumps(response, indent=2)}")
    assert response.get("result", {}).get("success"), "Execute failed!"
    print(f"Output: {response['result']['output']}")
    print(f"Result: {response['result']['result']}")
    print("PASSED")


def test_modify_object(client: BlenderClient):
    """Test modify_object method."""
    print("\n=== Testing modify_object ===")
    response = client.call(
        "modify_object",
        name="TestCube",
        location=(3, 1, 0.5),
        scale=(1, 1, 1)
    )
    print(f"Response: {json.dumps(response, indent=2)}")
    assert response.get("result", {}).get("success"), "Modify object failed!"
    print("PASSED")


def test_get_object(client: BlenderClient):
    """Test get_object method."""
    print("\n=== Testing get_object ===")
    response = client.call("get_object", name="TestCube")
    print(f"Response: {json.dumps(response, indent=2)}")
    assert "result" in response, "Get object failed!"
    assert "error" not in response["result"], f"Error: {response['result'].get('error')}"
    print(f"Object type: {response['result']['type']}")
    print(f"Location: {response['result']['location']}")
    print("PASSED")


def test_delete_object(client: BlenderClient):
    """Test delete_object method."""
    print("\n=== Testing delete_object ===")
    response = client.call("delete_object", name="TestCube")
    print(f"Response: {json.dumps(response, indent=2)}")
    assert response.get("result", {}).get("success"), "Delete object failed!"
    print("PASSED")


def run_all_tests(host: str = '127.0.0.1', port: int = 9876):
    """Run all tests."""
    print(f"Connecting to Blender at {host}:{port}...")
    print("Make sure Blender is running with the addon enabled and server started!")
    print("=" * 60)

    try:
        with BlenderClient(host, port) as client:
            test_ping(client)
            test_version(client)
            test_get_scene(client)
            test_add_object(client)
            test_execute(client)
            test_modify_object(client)
            test_get_object(client)
            test_delete_object(client)

            print("\n" + "=" * 60)
            print("ALL TESTS PASSED!")
            print("=" * 60)

    except ConnectionRefusedError:
        print("\nERROR: Could not connect to Blender.")
        print("Make sure:")
        print("  1. Blender is running")
        print("  2. Claude Blender addon is enabled")
        print("  3. Server is started (click 'Start Server' in the Claude panel)")
        sys.exit(1)

    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


def interactive_mode(host: str = '127.0.0.1', port: int = 9876):
    """Interactive REPL for testing."""
    print(f"Connecting to Blender at {host}:{port}...")

    try:
        with BlenderClient(host, port) as client:
            print("Connected! Enter JSON-RPC commands or 'quit' to exit.")
            print("Example: ping")
            print("Example: get_scene detail_level=detailed")
            print("Example: add_object object_type=sphere location=[0,0,2]")
            print()

            while True:
                try:
                    line = input(">>> ").strip()
                    if not line:
                        continue
                    if line.lower() in ('quit', 'exit', 'q'):
                        break

                    # Parse command
                    parts = line.split(maxsplit=1)
                    method = parts[0]
                    params = {}

                    if len(parts) > 1:
                        # Parse key=value pairs
                        for kv in parts[1].split():
                            if '=' in kv:
                                k, v = kv.split('=', 1)
                                # Try to parse as JSON
                                try:
                                    params[k] = json.loads(v)
                                except:
                                    params[k] = v

                    response = client.call(method, **params)
                    print(json.dumps(response, indent=2))

                except KeyboardInterrupt:
                    print()
                    break
                except Exception as e:
                    print(f"Error: {e}")

    except ConnectionRefusedError:
        print("Could not connect to Blender. Is the server running?")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test client for Claude Blender")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", type=int, default=9876, help="Server port")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")

    args = parser.parse_args()

    if args.interactive:
        interactive_mode(args.host, args.port)
    else:
        run_all_tests(args.host, args.port)
