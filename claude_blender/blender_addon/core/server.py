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
        self._out: dict = {}     # Client -> pending outgoing bytes (partial writes)
        self.last_error: Optional[str] = None

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
            self.last_error = None

            # Register timer for polling (persistent across file loads)
            bpy.app.timers.register(self._poll, persistent=True)

            print(f"[Claude Blender] Server started on {self.host}:{self.port}")
            return True

        except Exception as e:
            self.last_error = str(e)
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
        self._out.clear()

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

        # Drain pending partial writes (large responses span multiple polls)
        for client in list(self._out):
            self._flush(client)

        return 0.016  # Poll at ~60 Hz

    def _handle_message(self, client: socket.socket, message: bytes):
        """Process a complete message from a client."""
        if self._request_handler:
            try:
                response = self._request_handler(message)
            except Exception as e:
                response = json.dumps({
                    "jsonrpc": "2.0",
                    "error": {"code": -32000, "message": str(e)},
                    "id": None
                }).encode()
            if response:
                self._queue_send(client, response + b'\n')
        else:
            print("[Claude Blender] No request handler set")

    def _queue_send(self, client: socket.socket, data: bytes):
        """Queue data for a client and flush as much as the socket accepts.

        A non-blocking send() writes only what fits in the kernel buffer;
        the remainder is kept here and drained on subsequent polls, so large
        responses are never silently truncated.
        """
        self._out[client] = self._out.get(client, b'') + data
        self._flush(client)

    def _flush(self, client: socket.socket):
        """Send as much pending output as the socket will take right now."""
        buf = self._out.get(client)
        if not buf:
            return
        try:
            while buf:
                sent = client.send(buf)
                if sent <= 0:
                    break
                buf = buf[sent:]
        except BlockingIOError:
            pass  # Kernel buffer full; retry on the next poll
        except OSError:
            self._remove_client(client)
            return
        if buf:
            self._out[client] = buf
        else:
            self._out.pop(client, None)

    def _remove_client(self, client: socket.socket):
        """Remove a client and clean up its resources."""
        if client in self.clients:
            self.clients.remove(client)
        self._buffer.pop(client, None)
        self._out.pop(client, None)
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
