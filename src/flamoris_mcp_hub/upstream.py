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


def _http_client(*, headers: dict[str, str]) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(30.0, read=300.0))


async def _close_stack(stack: contextlib.AsyncExitStack) -> None:
    # A broken transport may also fail during cleanup. Do not let its cleanup
    # exception terminate the task group and take the entire Hub down.
    with anyio.CancelScope(shield=True):
        try:
            await stack.aclose()
        except Exception as exc:
            logger.warning("Upstream cleanup failed (%s)", type(exc).__name__)


@dataclass
class _Request:
    name: str
    arguments: dict[str, Any]
    reply: anyio.Event = field(default_factory=anyio.Event)
    result: CallToolResult | None = None
    error: Exception | None = None
    cancelled: bool = False


class LazyConnection:
    """One owner task enters and exits all long-lived upstream contexts."""

    def __init__(self, config: UpstreamConfig) -> None:
        self.config = config
        self.connected = False
        self.last_error: str | None = None
        self.catalog_mismatch: str | None = None
        self._send, self._receive = anyio.create_memory_object_stream[_Request](16)
        self._started = False
        self._closing = False
        self._start_lock = anyio.Lock()

    async def call_tool(
        self, task_group: anyio.abc.TaskGroup, name: str, arguments: dict[str, Any]
    ) -> CallToolResult:
        async with self._start_lock:
            if self._closing:
                raise RuntimeError("upstream connection is shutting down")
            if not self._started:
                task_group.start_soon(self._owner)
                self._started = True
        request = _Request(name, arguments)
        try:
            await self._send.send(request)
            await request.reply.wait()
        except anyio.get_cancelled_exc_class():
            # The owner checks this immediately before dispatch, without an await
            # between the check and sending the real tools/call request.
            request.cancelled = True
            raise
        except anyio.ClosedResourceError as exc:
            raise RuntimeError("upstream connection is shutting down") from exc
        if request.error is not None:
            raise request.error
        assert request.result is not None
        return request.result

    async def close(self) -> None:
        self._closing = True
        await self._send.aclose()

    def _check_catalog(self, listed: Any) -> None:
        try:
            upstream = {tool.name: tool for tool in listed.tools}
        except (AttributeError, TypeError) as exc:
            raise LookupError(
                f"catalog mismatch: {self.config.id} returned invalid tools/list"
            ) from exc
        for configured in self.config.tools:
            actual = upstream.get(configured.name)
            if actual is None:
                raise LookupError(
                    f"catalog mismatch: {self.config.id}.{configured.name} is missing"
                )
            if configured.input_schema != actual.input_schema:
                raise LookupError(
                    f"catalog mismatch: {self.config.id}.{configured.name} input schema changed"
                )
        self.catalog_mismatch = None

    async def _owner(self) -> None:
        # Every context in this stack is entered and closed in this one task.
        stack = contextlib.AsyncExitStack()
        session: ClientSession | None = None
        try:
            async with self._receive:
                async for request in self._receive:
                    try:
                        if self._closing:
                            raise RuntimeError("upstream connection is shutting down")
                        if request.cancelled:
                            continue
                        if session is not None:
                            try:
                                listed = await session.list_tools()
                            except Exception:
                                self.connected = False
                                await _close_stack(stack)
                                stack = contextlib.AsyncExitStack()
                                session = None
                        if session is None:
                            try:
                                client = await stack.enter_async_context(
                                    _http_client(headers=self.config.headers())
                                )
                                streams = await stack.enter_async_context(
                                    streamable_http_client(str(self.config.url), http_client=client)
                                )
                                session = await stack.enter_async_context(ClientSession(*streams))
                                await session.initialize()
                                listed = await session.list_tools()
                                self.connected = True
                                logger.info("Connected upstream %s", self.config.id)
                            except Exception:
                                self.connected = False
                                await _close_stack(stack)
                                stack = contextlib.AsyncExitStack()
                                session = None
                                raise ConnectionError(
                                    f"upstream {self.config.id!r} is unavailable"
                                ) from None
                        try:
                            self._check_catalog(listed)
                        except LookupError as exc:
                            self.catalog_mismatch = str(exc)
                            raise
                        if self._closing:
                            raise RuntimeError("upstream connection is shutting down")
                        if request.cancelled:
                            continue
                        # Never replay a call whose outcome may be ambiguous.
                        try:
                            request.result = await session.call_tool(
                                request.name, request.arguments
                            )
                            if not isinstance(request.result, CallToolResult):
                                raise TypeError(
                                    "upstream returned an unsupported tools/call result"
                                )
                        except Exception:
                            self.connected = False
                            await _close_stack(stack)
                            stack = contextlib.AsyncExitStack()
                            session = None
                            raise ConnectionError(
                                f"upstream {self.config.id!r} call failed; not retried"
                            ) from None
                        self.last_error = None
                    except (ConnectionError, LookupError, ValueError, RuntimeError) as exc:
                        self.last_error = str(exc)
                        request.error = exc
                    finally:
                        request.reply.set()
        finally:
            self.connected = False
            await _close_stack(stack)


class UpstreamRegistry:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self._connections = {c.id: LazyConnection(c) for c in catalog.configs.values()}
        self._group: anyio.abc.TaskGroup | None = None

    @contextlib.asynccontextmanager
    async def run(self):
        async with anyio.create_task_group() as group:
            self._group = group
            try:
                yield self
            finally:
                for connection in self._connections.values():
                    await connection.close()
                self._group = None

    def status(self) -> list[dict[str, object]]:
        return [
            {
                "id": c.config.id,
                "namespace": c.config.namespace,
                "url": str(c.config.url),
                "configured_tools": len(c.config.tools),
                "connected": c.connected,
                "last_error": c.last_error,
                "catalog_mismatch": c.catalog_mismatch,
            }
            for c in self._connections.values()
        ]

    async def call_public_tool(self, public_name: str, arguments: dict[str, Any]) -> CallToolResult:
        if self._group is None:
            raise RuntimeError("Hub registry is not running")
        config, tool = self.catalog.tools[public_name]
        return await self._connections[config.id].call_tool(self._group, tool.name, arguments)
