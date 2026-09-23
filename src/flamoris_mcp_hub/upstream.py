from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

import anyio
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult

from .config import Catalog, UpstreamConfig

logger = logging.getLogger(__name__)


@dataclass
class LazyConnection:
    config: UpstreamConfig
    _stack: contextlib.AsyncExitStack | None = None
    _session: ClientSession | None = None
    _known_tools: set[str] = field(default_factory=set)
    _last_error: str | None = None
    _lock: anyio.Lock = field(default_factory=anyio.Lock)

    @property
    def connected(self) -> bool:
        return self._session is not None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def close(self) -> None:
        stack, self._stack = self._stack, None
        self._session = None
        self._known_tools.clear()
        if stack is not None:
            await stack.aclose()

    async def _connect(self) -> ClientSession:
        stack = contextlib.AsyncExitStack()
        try:
            client = await stack.enter_async_context(
                httpx2.AsyncClient(headers=self.config.headers())
            )
            read_stream, write_stream = await stack.enter_async_context(
                streamable_http_client(str(self.config.url), http_client=client)
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()
            listed = await session.list_tools()
        except Exception:
            await stack.aclose()
            raise

        old_stack = self._stack
        self._stack = stack
        self._session = session
        self._known_tools = {tool.name for tool in listed.tools}
        self._last_error = None

        if old_stack is not None:
            await old_stack.aclose()

        logger.info("Connected upstream %s at %s", self.config.id, self.config.url)
        return session

    async def _ensure_connected_locked(self, required_tool: str) -> ClientSession:
        if self._session is not None:
            try:
                # tools/list is a read-only liveness probe. Never probe by replaying
                # the actual tool call because some upstream tools are non-idempotent.
                listed = await self._session.list_tools()
                self._known_tools = {tool.name for tool in listed.tools}
            except Exception as exc:
                logger.info("Upstream %s connection is stale: %s", self.config.id, exc)
                await self.close()

        if self._session is None:
            try:
                await self._connect()
            except Exception as exc:
                self._last_error = str(exc)
                raise ConnectionError(
                    f"upstream {self.config.id!r} is unavailable: {exc}"
                ) from exc

        if required_tool not in self._known_tools:
            raise LookupError(
                f"upstream {self.config.id!r} does not expose configured tool "
                f"{required_tool!r}"
            )

        assert self._session is not None
        return self._session

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> CallToolResult:
        async with self._lock:
            session = await self._ensure_connected_locked(tool_name)
            try:
                # Exactly one tools/call attempt. If the connection fails after the
                # upstream may have accepted the request, do not replay automatically.
                return await session.call_tool(tool_name, arguments)
            except Exception as exc:
                self._last_error = str(exc)
                await self.close()
                raise ConnectionError(
                    f"call to upstream {self.config.id!r} failed; request was not retried: {exc}"
                ) from exc


class UpstreamRegistry:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self._connections = {
            config.id: LazyConnection(config)
            for config in catalog.configs.values()
        }

    def status(self) -> list[dict[str, object]]:
        return [
            {
                "id": connection.config.id,
                "namespace": connection.config.namespace,
                "url": str(connection.config.url),
                "configured_tools": len(connection.config.tools),
                "connected": connection.connected,
                "last_error": connection.last_error,
            }
            for connection in self._connections.values()
        ]

    async def call_public_tool(
        self, public_name: str, arguments: dict[str, Any]
    ) -> CallToolResult:
        config, tool = self.catalog.tools[public_name]
        return await self._connections[config.id].call_tool(tool.name, arguments)

    async def close(self) -> None:
        for connection in self._connections.values():
            await connection.close()
