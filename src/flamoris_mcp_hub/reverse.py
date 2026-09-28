"""Authenticated, outbound desktop connectors; no tool calls are replayed."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import uuid
from fnmatch import fnmatchcase
from typing import Any

from mcp.types import CallToolResult
from starlette.websockets import WebSocket

from .config import UpstreamConfig

MAX_BYTES = 4 * 1024 * 1024


class ReverseConnection:
    def __init__(self, config: UpstreamConfig) -> None:
        self.config = config
        self.connected = False
        self.last_error: str | None = None
        self.catalog_mismatch: str | None = None
        self._socket: WebSocket | None = None
        self._pending: tuple[str, asyncio.Future] | None = None
        self._available: set[str] = set()
        self._closing = False

    async def close(self) -> None:
        self._closing = True
        await self._disconnect()

    async def _disconnect(self) -> None:
        socket, self._socket = self._socket, None
        self.connected = False
        self._available.clear()
        if self._pending is not None:
            _, future = self._pending
            if not future.done():
                future.set_exception(
                    ConnectionError("desktop disconnected; outcome unknown, not retried")
                )
        if socket is not None:
            try:
                await asyncio.wait_for(socket.close(code=1011), 5)
            except Exception:
                pass

    async def call_tool(self, _group, name: str, arguments: dict[str, Any]) -> CallToolResult:
        socket = self._socket
        if not self.connected or socket is None or self._closing:
            raise ConnectionError(f"upstream {self.config.id!r} is offline")
        if name not in self._available:
            raise LookupError(
                f"upstream {self.config.id!r} tool is unavailable in current permission"
            )
        if self._pending is not None:
            raise ConnectionError(f"upstream {self.config.id!r} is busy")
        identifier = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending = identifier, future
        try:
            message = json.dumps(
                {"type": "call", "id": identifier, "name": name, "arguments": arguments}
            )
            if len(message.encode()) > MAX_BYTES:
                raise ValueError("desktop request is too large")
            await asyncio.wait_for(socket.send_text(message), 5)
            return await asyncio.wait_for(future, 125)
        except (Exception, asyncio.CancelledError) as exc:
            # A response may have been lost after commit. Close/cancel; never resend it.
            self.last_error = "desktop call failed; outcome unknown, not retried"
            await self._disconnect()
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # observe disconnect exception if sending failed first
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ConnectionError(self.last_error) from None
        finally:
            self._pending = None

    async def serve(self, socket: WebSocket) -> None:
        if self._closing or self._socket is not None:
            await socket.close(code=1008)  # no takeover of a live instance
            return
        self._socket = socket
        try:
            await socket.accept()
            hello = await asyncio.wait_for(self._receive(socket), 10)
            if (
                hello.get("type") != "register"
                or hello.get("version") != 1
                or hello.get("productId") != self.config.product_id
                or hello.get("permission") not in ("edit", "readOnly")
                or any(
                    not isinstance(hello.get(k), str) or not 1 <= len(hello[k]) <= 128
                    for k in ("runtimeId", "documentToken")
                )
            ):
                raise ValueError("invalid registration")
            tools = hello.get("tools")
            if not isinstance(tools, list) or not 1 <= len(tools) <= 513:
                raise ValueError("invalid catalog")
            actual: dict[str, dict] = {}
            for tool in tools:
                if (
                    not isinstance(tool, dict)
                    or not isinstance(tool.get("name"), str)
                    or not isinstance(tool.get("inputSchema"), dict)
                    or tool["name"] in actual
                ):
                    raise ValueError("invalid catalog")
                actual[tool["name"]] = tool["inputSchema"]
            available = set()
            for configured in self.config.tools:
                if configured.name in actual:
                    if actual[configured.name] != configured.input_schema:
                        self.catalog_mismatch = "desktop catalog schema mismatch"
                        raise ValueError("catalog mismatch")
                    available.add(configured.name)
                elif hello["permission"] == "edit":
                    self.catalog_mismatch = "desktop catalog tool missing"
                    raise ValueError("catalog mismatch")
            if "mcp.context" not in available:
                raise ValueError("catalog requires mcp.context")
            self._available = available
            self.catalog_mismatch = self.last_error = None
            await socket.send_json({"type": "ready", "version": 1})
            self.connected = True
            while not self._closing:
                response = await self._receive(socket)
                pending = self._pending
                if (
                    response.get("type") != "result"
                    or pending is None
                    or response.get("id") != pending[0]
                    or pending[1].done()
                ):
                    raise ValueError("invalid response correlation")
                result = CallToolResult.model_validate(response.get("result"))
                pending[1].set_result(result)
        except (Exception, asyncio.CancelledError):
            self.last_error = "desktop disconnected"
        finally:
            # No new connector can register until cleanup has detached this exact socket.
            if self._socket is socket:
                await self._disconnect()

    @staticmethod
    async def _receive(socket: WebSocket) -> dict:
        value = await socket.receive_text()
        if len(value.encode()) > MAX_BYTES:
            raise ValueError("desktop frame too large")
        result = json.loads(value)
        if not isinstance(result, dict):
            raise ValueError("invalid desktop message")
        return result


class DesktopGateway:
    """Route desktop WSS separately from client HTTP bearer authentication."""

    def __init__(self, app, registry_holder: dict, allowed_hosts: list[str]) -> None:
        self.app, self.holder, self.allowed_hosts = app, registry_holder, allowed_hosts

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "websocket":
            await self.app(scope, receive, send)
            return
        socket = WebSocket(scope, receive, send)
        registry = self.holder.get("registry")
        prefix = "/desktop/"
        path = scope.get("path", "")
        connection = (
            registry._connections.get(path[len(prefix) :])
            if (registry is not None and path.startswith(prefix))
            else None
        )
        headers = scope.get("headers", [])
        hosts = [v.decode("latin1") for k, v in headers if k.lower() == b"host"]
        auth = [v for k, v in headers if k.lower() == b"authorization"]
        # Native desktop connectors never need browser-origin WebSockets.
        valid = (
            isinstance(connection, ReverseConnection)
            and len(hosts) == 1
            and any(fnmatchcase(hosts[0], pattern) for pattern in self.allowed_hosts)
            and not any(k.lower() == b"origin" for k, _ in headers)
            and len(auth) == 1
            and len(auth[0]) <= 1024
        )
        expected = os.environ.get(connection.config.connector_token_env or "", "") if valid else ""
        supplied = auth[0][7:] if valid and auth[0].startswith(b"Bearer ") else b""
        valid = (
            valid
            and len(expected) >= 32
            and hmac.compare_digest(
                hashlib.sha256(expected.encode()).digest(), hashlib.sha256(supplied).digest()
            )
        )
        if not valid:
            await socket.close(code=1008)
            return
        await connection.serve(socket)
