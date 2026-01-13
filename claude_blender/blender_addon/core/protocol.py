# SPDX-License-Identifier: MIT
"""
JSON-RPC 2.0 protocol handler for Claude Blender.
"""

import json
from typing import Any, Dict, Optional, Callable, Union


class JSONRPCError(Exception):
    """JSON-RPC error with code and message."""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


# Standard JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SERVER_ERROR = -32000


class JSONRPCHandler:
    """
    JSON-RPC 2.0 request handler.

    Supports:
    - Single requests
    - Batch requests (array of requests)
    - Notifications (requests without id)
    """

    def __init__(self):
        self.methods: Dict[str, Callable] = {}

    def register_method(self, name: str, handler: Callable):
        """Register a method handler."""
        self.methods[name] = handler

    def register_methods(self, methods: Dict[str, Callable]):
        """Register multiple method handlers."""
        self.methods.update(methods)

    def handle(self, request: bytes) -> bytes:
        """
        Handle a JSON-RPC request and return the response.

        Args:
            request: Raw JSON-RPC request bytes

        Returns:
            Raw JSON-RPC response bytes
        """
        try:
            data = json.loads(request.decode('utf-8'))
        except json.JSONDecodeError as e:
            return self._error_response(None, PARSE_ERROR, f"Parse error: {e}")

        # Handle batch requests
        if isinstance(data, list):
            if not data:
                return self._error_response(None, INVALID_REQUEST, "Empty batch")
            responses = [self._process_request(req) for req in data]
            # Filter out None responses (notifications)
            responses = [r for r in responses if r is not None]
            if not responses:
                return b''  # All were notifications
            return json.dumps(responses).encode('utf-8')

        # Handle single request
        response = self._process_request(data)
        if response is None:
            return b''  # Notification
        return json.dumps(response).encode('utf-8')

    def _process_request(self, data: Any) -> Optional[Dict]:
        """Process a single JSON-RPC request."""
        # Validate request structure
        if not isinstance(data, dict):
            return self._error_dict(None, INVALID_REQUEST, "Request must be an object")

        # Check JSON-RPC version
        if data.get('jsonrpc') != '2.0':
            return self._error_dict(
                data.get('id'),
                INVALID_REQUEST,
                "Invalid JSON-RPC version"
            )

        method = data.get('method')
        params = data.get('params', {})
        request_id = data.get('id')

        # Method must be a string
        if not isinstance(method, str):
            return self._error_dict(request_id, INVALID_REQUEST, "Method must be a string")

        # Check if method exists
        if method not in self.methods:
            return self._error_dict(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")

        # Execute method
        try:
            handler = self.methods[method]

            # Call with params (dict or list)
            if isinstance(params, dict):
                result = handler(**params)
            elif isinstance(params, list):
                result = handler(*params)
            else:
                result = handler()

            # If this is a notification (no id), don't return a response
            if request_id is None:
                return None

            return self._success_dict(request_id, result)

        except JSONRPCError as e:
            return self._error_dict(request_id, e.code, e.message, e.data)
        except TypeError as e:
            return self._error_dict(request_id, INVALID_PARAMS, f"Invalid params: {e}")
        except Exception as e:
            return self._error_dict(request_id, SERVER_ERROR, str(e))

    def _success_dict(self, request_id: Any, result: Any) -> Dict:
        """Create a success response dict."""
        return {
            "jsonrpc": "2.0",
            "result": result,
            "id": request_id
        }

    def _error_dict(
        self,
        request_id: Any,
        code: int,
        message: str,
        data: Any = None
    ) -> Dict:
        """Create an error response dict."""
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {
            "jsonrpc": "2.0",
            "error": error,
            "id": request_id
        }

    def _error_response(
        self,
        request_id: Any,
        code: int,
        message: str,
        data: Any = None
    ) -> bytes:
        """Create an error response bytes."""
        return json.dumps(self._error_dict(request_id, code, message, data)).encode('utf-8')
