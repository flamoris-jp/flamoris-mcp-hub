from __future__ import annotations

import argparse
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import jsonschema
import uvicorn
from jsonschema import ValidationError
from mcp.server import Server, ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from .runtime import start_registry
from .upstream import UpstreamRegistry

logger = logging.getLogger(__name__)

HUB_STATUS_TOOL = Tool(
    name="hub.upstreams.list",
    description="List configured upstream MCPs and their current lazy connection state.",
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
)


@asynccontextmanager
async def lifespan(_server):
    _catalog, registry = start_registry()
    async with registry.run():
        yield registry


async def on_list_tools(
    ctx: ServerRequestContext[UpstreamRegistry],
    _params: PaginatedRequestParams | None,
) -> ListToolsResult:
    registry = ctx.lifespan_context
    configured = [
        Tool(
            name=public_name,
            description=tool.description,
            input_schema=tool.input_schema,
        )
        for public_name, (_config, tool) in sorted(registry.catalog.tools.items())
    ]
    return ListToolsResult(tools=[HUB_STATUS_TOOL, *configured])


def error_result(message: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        is_error=True,
    )


async def on_call_tool(
    ctx: ServerRequestContext[UpstreamRegistry],
    params: CallToolRequestParams,
) -> CallToolResult:
    registry = ctx.lifespan_context
    arguments: dict[str, Any] = params.arguments or {}

    if params.name == HUB_STATUS_TOOL.name:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"upstreams": registry.status()},
                        ensure_ascii=False,
                    ),
                )
            ]
        )

    entry = registry.catalog.tools.get(params.name)
    if entry is None:
        return error_result(f"Unknown tool: {params.name}")

    _config, tool = entry
    try:
        jsonschema.validate(instance=arguments, schema=tool.input_schema)
    except ValidationError as exc:
        return error_result(f"Invalid arguments for {params.name}: {exc.message}")

    try:
        return await registry.call_public_tool(params.name, arguments)
    except (ConnectionError, LookupError) as exc:
        logger.info("Tool %s unavailable: %s", params.name, exc)
        return error_result(str(exc))


server = Server(
    "FLAMORIS MCP Hub",
    version="0.1.0",
    lifespan=lifespan,
    on_list_tools=on_list_tools,
    on_call_tool=on_call_tool,
)


def transport_security() -> TransportSecuritySettings:
    # An external reverse proxy Host must be listed explicitly; never allow '*'.
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    hosts.extend(
        x.strip() for x in os.getenv("FLAMORIS_MCP_HUB_ALLOWED_HOSTS", "").split(",") if x.strip()
    )
    origins.extend(
        x.strip() for x in os.getenv("FLAMORIS_MCP_HUB_ALLOWED_ORIGINS", "").split(",") if x.strip()
    )
    if "*" in hosts or "*" in origins:
        raise ValueError("wildcard Host/Origin is not allowed")
    return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)


# Conventional ASGI entry point for tests and external ASGI runners.
app = server.streamable_http_app(
    streamable_http_path="/mcp",
    host="0.0.0.0",
    transport_security=transport_security(),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FLAMORIS MCP Hub")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mcp-path", default="/mcp")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO)
    runtime_app = server.streamable_http_app(
        streamable_http_path=args.mcp_path,
        host=args.host,
        transport_security=transport_security(),
    )
    uvicorn.run(runtime_app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
