from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

import jsonschema
import uvicorn
from dotenv import load_dotenv
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
    ToolAnnotations,
)
from starlette.types import Receive, Scope, Send

from .auth import IDENTITY_SCOPE_KEY, BearerAuth, ExternalIdentity, client_token, configured_clients
from .config import env_file
from .reverse import DesktopGateway
from .runtime import start_registry
from .upstream import UpstreamRegistry

logger = logging.getLogger(__name__)

HUB_STATUS_TOOL = Tool(
    name="hub.upstreams.list",
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True
    ),
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
            annotations=tool.annotations.to_mcp(),
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
        request = getattr(ctx, "request", None)
        identity = request.scope.get(IDENTITY_SCOPE_KEY) if request is not None else None
        if not isinstance(identity, ExternalIdentity):
            identity = None
        # Public arguments, headers and caller-supplied _meta are never identity sources.
        return await registry.call_public_tool(params.name, arguments, identity=identity)
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


def create_app(*, host: str = "127.0.0.1", mcp_path: str = "/mcp") -> DesktopGateway:
    # Read mounted configuration before constructing either security boundary.
    load_dotenv(env_file(), override=False)
    token = client_token()  # Fail closed before starting a registry or listener.
    clients = configured_clients()
    holder = {}

    @asynccontextmanager
    async def runtime_lifespan(_server):
        _catalog, registry = start_registry()
        ingress_credentials = [token, *(credential for credential, _ in clients)]
        for config in _catalog.configs.values():
            if config.external_provenance_secret_env is not None:
                signing_secret = os.environ.get(config.external_provenance_secret_env, "")
                if any(
                    hmac.compare_digest(signing_secret, credential)
                    for credential in ingress_credentials
                ):
                    raise ValueError(
                        "provenance signing secret must be independent of client tokens"
                    )
        holder["registry"] = registry
        try:
            async with registry.run():
                yield registry
        finally:
            holder.pop("registry", None)

    runtime_server = Server(
        "FLAMORIS MCP Hub",
        version="0.1.0",
        lifespan=runtime_lifespan,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
    security = transport_security()
    http = BearerAuth(
        runtime_server.streamable_http_app(
            streamable_http_path=mcp_path, host=host, transport_security=security
        ),
        token,
        clients,
    )
    return DesktopGateway(http, holder, security.allowed_hosts)


@lru_cache(maxsize=1)
def _default_app() -> DesktopGateway:
    return create_app()


async def app(scope: Scope, receive: Receive, send: Send) -> None:
    """ASGI entrypoint uses the same mandatory authentication as the CLI."""
    await _default_app()(scope, receive, send)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FLAMORIS MCP Hub")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mcp-path", default="/mcp")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO)
    runtime_app = create_app(host=args.host, mcp_path=args.mcp_path)
    uvicorn.run(
        runtime_app,
        host=args.host,
        port=args.port,
        ws_max_size=4 * 1024 * 1024,
        ws_max_queue=4,
        ws_ping_interval=15,
        ws_ping_timeout=15,
    )


if __name__ == "__main__":
    main()
