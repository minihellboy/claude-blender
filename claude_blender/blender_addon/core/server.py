# SPDX-License-Identifier: MIT
"""
Non-blocking TCP socket server for Blender.

Uses bpy.app.timers for polling since Blender Python is NOT thread-safe.
"""

import socket
import json
from typing import Optional, List, Callable
import bpy


class BlenderServer:
    """
    Timer-based TCP server that polls for connections in the main thread.

    This is necessary because Blender's Python API is not thread-safe.
    Using threading.Thread would crash Blender.
    """

    def __init__(self, host: str = '127.0.0.1', port: int = 9876):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.clients: List[socket.socket] = []
        self._running = False
        self._request_handler: Optional[Callable[[bytes], bytes]] = None
        self._buffer: dict = {}  # Client -> buffer mapping for partial reads

    def set_request_handler(self, handler: Callable[[bytes], bytes]):
        """Set the handler function for processing requests."""
        self._request_handler = handler

    def start(self) -> bool:
        """Start the server and register the polling timer."""
        if self._running:
            print("[Claude Blender] Server already running")
            return False

        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.setblocking(False)
            self.socket.bind((self.host, self.port))
            self.socket.listen(5)
            self._running = True

            # Register timer for polling (persistent across file loads)
            bpy.app.timers.register(self._poll, persistent=True)

            print(f"[Claude Blender] Server started on {self.host}:{self.port}")
            return True

        except Exception as e:
            print(f"[Claude Blender] Failed to start server: {e}")
            self._cleanup()
            return False

    def stop(self):
        """Stop the server and clean up resources."""
        self._running = False
        self._cleanup()
        print("[Claude Blender] Server stopped")

    def _cleanup(self):
        """Clean up all socket resources."""
        # Close all client connections
        for client in self.clients:
            try:
                client.close()
            except:
                pass
        self.clients.clear()
        self._buffer.clear()

        # Close server socket
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None

    def _poll(self) -> Optional[float]:
        """
        Timer callback that polls for socket activity.

        Returns:
            float: Time until next poll (seconds), or None to unregister
        """
        if not self._running:
            return None  # Unregister timer

        # Accept new connections (non-blocking)
        try:
            client, addr = self.socket.accept()
            client.setblocking(False)
            self.clients.append(client)
            self._buffer[client] = b''
            print(f"[Claude Blender] Client connected: {addr}")
        except BlockingIOError:
            pass  # No pending connections
        except Exception as e:
            print(f"[Claude Blender] Accept error: {e}")

        # Process data from each client
        for client in self.clients[:]:  # Copy list to allow modification
            try:
                # Try to receive data (non-blocking)
                data = client.recv(65536)

                if data:
                    # Append to buffer
                    self._buffer[client] += data

                    # Process complete messages (newline-delimited)
                    while b'\n' in self._buffer[client]:
                        message, self._buffer[client] = self._buffer[client].split(b'\n', 1)
                        if message:
                            self._handle_message(client, message)
                else:
                    # Empty data means client disconnected
                    self._remove_client(client)

            except BlockingIOError:
                pass  # No data available
            except ConnectionResetError:
                self._remove_client(client)
            except Exception as e:
                print(f"[Claude Blender] Client error: {e}")
                self._remove_client(client)

        return 0.016  # Poll at ~60 Hz

    def _handle_message(self, client: socket.socket, message: bytes):
        """Process a complete message from a client."""
        if self._request_handler:
            try:
                response = self._request_handler(message)
                client.send(response + b'\n')
            except Exception as e:
                error_response = json.dumps({
                    "jsonrpc": "2.0",
                    "error": {"code": -32000, "message": str(e)},
                    "id": None
                }).encode()
                client.send(error_response + b'\n')
        else:
            print("[Claude Blender] No request handler set")

    def _remove_client(self, client: socket.socket):
        """Remove a client and clean up its resources."""
        if client in self.clients:
            self.clients.remove(client)
        if client in self._buffer:
            del self._buffer[client]
        try:
            client.close()
        except:
            pass
        print("[Claude Blender] Client disconnected")

    @property
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._running

    @property
    def client_count(self) -> int:
        """Get the number of connected clients."""
        return len(self.clients)


# Global server instance
_server: Optional[BlenderServer] = None


def get_server() -> BlenderServer:
    """Get or create the global server instance."""
    global _server
    if _server is None:
        _server = BlenderServer()
    return _server


def start_server(port: int = 9876) -> bool:
    """Start the global server instance."""
    server = get_server()
    server.port = port
    return server.start()


def stop_server():
    """Stop the global server instance."""
    global _server
    if _server:
        _server.stop()
