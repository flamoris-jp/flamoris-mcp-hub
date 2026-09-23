from __future__ import annotations

import logging
from dataclasses import dataclass

from mcp import ClientSessionGroup
from mcp.client.session_group import StreamableHttpParameters

from .config import UpstreamConfig

logger = logging.getLogger(__name__)


@dataclass
class ConnectedUpstream:
    config: UpstreamConfig
    group: ClientSessionGroup
    tools: tuple[str, ...]


class UpstreamRegistry:
    def __init__(self) -> None:
        self._connected: dict[str, ConnectedUpstream] = {}
        self._errors: dict[str, str] = {}

    @property
    def connected(self) -> dict[str, ConnectedUpstream]:
        return dict(self._connected)

    @property
    def errors(self) -> dict[str, str]:
        return dict(self._errors)

    async def __aenter__(self) -> "UpstreamRegistry":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        for item in reversed(tuple(self._connected.values())):
            await item.group.__aexit__(exc_type, exc, tb)
        self._connected.clear()

    async def connect_all(self, configs: list[UpstreamConfig]) -> None:
        for config in configs:
            try:
                await self._connect(config)
            except Exception as exc:  # noqa: BLE001 - isolate one broken upstream
                logger.exception("Failed to connect upstream %s", config.id)
                self._errors[config.id] = str(exc)

    async def _connect(self, config: UpstreamConfig) -> None:
        namespace = config.namespace

        def namespaced(component_name: str, _server_info) -> str:
            return f"{namespace}.{component_name}"

        group = ClientSessionGroup(component_name_hook=namespaced)
        await group.__aenter__()
        try:
            await group.connect_to_server(
                StreamableHttpParameters(
                    url=str(config.url),
                    headers=config.headers(),
                )
            )
        except Exception:
            await group.__aexit__(None, None, None)
            raise

        tool_names = tuple(sorted(group.tools))
        self._connected[config.id] = ConnectedUpstream(
            config=config,
            group=group,
            tools=tool_names,
        )
        self._errors.pop(config.id, None)
        logger.info(
            "Connected upstream %s at %s with %d tools",
            config.id,
            config.url,
            len(tool_names),
        )
