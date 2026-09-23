from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .config import UpstreamConfig

logger = logging.getLogger(__name__)


@dataclass
class ConnectedUpstream:
    config: UpstreamConfig
    session: ClientSession
    tools: tuple[str, ...]


class UpstreamRegistry:
    def __init__(self) -> None:
        self._stack = contextlib.AsyncExitStack()
        self._connected: dict[str, ConnectedUpstream] = {}
        self._errors: dict[str, str] = {}

    @property
    def connected(self) -> dict[str, ConnectedUpstream]:
        return dict(self._connected)

    @property
    def errors(self) -> dict[str, str]:
        return dict(self._errors)

    async def __aenter__(self) -> "UpstreamRegistry":
        await self._stack.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._stack.__aexit__(exc_type, exc, tb)

    async def connect_all(self, configs: list[UpstreamConfig]) -> None:
        for config in configs:
            try:
                await self._connect(config)
            except Exception as exc:  # noqa: BLE001 - isolate one broken upstream
                logger.exception("Failed to connect upstream %s", config.id)
                self._errors[config.id] = str(exc)

    async def _connect(self, config: UpstreamConfig) -> None:
        headers = config.headers()

        http_client = await self._stack.enter_async_context(
            httpx2.AsyncClient(headers=headers)
        )
        read_stream, write_stream = await self._stack.enter_async_context(
            streamable_http_client(str(config.url), http_client=http_client)
        )
        session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        tool_result = await session.list_tools()
        tool_names = tuple(tool.name for tool in tool_result.tools)

        self._connected[config.id] = ConnectedUpstream(
            config=config,
            session=session,
            tools=tool_names,
        )
        self._errors.pop(config.id, None)
        logger.info(
            "Connected upstream %s at %s with %d tools",
            config.id,
            config.url,
            len(tool_names),
        )
