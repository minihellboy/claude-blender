# SPDX-License-Identifier: MIT
"""
Transport integrity: large responses must arrive complete.

The addon's TCP server runs on a non-blocking socket; a bare send() would
silently truncate anything bigger than the kernel buffer (~500 KB was enough
to lose data on macOS). This drives the REAL BlenderServer over a real
socket pair - the asyncio-based protocol fake can never reproduce this.
"""

import asyncio
import json
import socket

from fake_bpy import load_module, make_bpy


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _run_roundtrip(payload_size: int) -> bytes:
    bpy = make_bpy()  # timers.register is a no-op; we pump _poll ourselves
    server_mod = load_module("server.py", bpy, name="_fake_core_server")

    big = b"x" * payload_size

    srv = server_mod.BlenderServer(port=_free_port())
    srv.set_request_handler(lambda message: big)
    assert srv.start()

    try:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", srv.port, limit=payload_size + 1024
        )
        writer.write(b'{"jsonrpc":"2.0","id":1,"method":"anything"}\n')
        await writer.drain()

        async def pump():
            while True:
                srv._poll()
                await asyncio.sleep(0.001)

        pump_task = asyncio.create_task(pump())
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=20)
        finally:
            pump_task.cancel()
        writer.close()
        return line
    finally:
        srv.stop()


async def test_large_response_arrives_complete():
    """4 MB response: the old bare send() lost ~75% of this."""
    size = 4 * 1024 * 1024
    line = await _run_roundtrip(size)
    assert len(line) == size + 1, f"received {len(line)} of {size + 1} bytes"
    assert line[-1:] == b"\n"


async def test_small_response_roundtrip():
    line = await _run_roundtrip(512)
    assert len(line) == 513


async def test_error_response_still_framed():
    """A handler crash must produce one framed JSON error, not a dead socket."""
    bpy = make_bpy()
    server_mod = load_module("server.py", bpy, name="_fake_core_server2")

    def broken_handler(message):
        raise ValueError("handler exploded")

    srv = server_mod.BlenderServer(port=_free_port())
    srv.set_request_handler(broken_handler)
    assert srv.start()

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", srv.port)
        writer.write(b'{"jsonrpc":"2.0","id":7,"method":"x"}\n')
        await writer.drain()

        async def pump():
            while True:
                srv._poll()
                await asyncio.sleep(0.001)

        pump_task = asyncio.create_task(pump())
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
        finally:
            pump_task.cancel()
        writer.close()

        body = json.loads(line)
        assert body["error"]["code"] == -32000
        assert "exploded" in body["error"]["message"]
    finally:
        srv.stop()
