from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import asdict

from mcp.server.mcpserver import MCPServer

from .runtime import start_registry

logger = logging.getLogger(__name__)

mcp = MCPServer("flamoris-mcp-hub")
_registry = None


@mcp.tool(name="hub.upstreams.list")
def list_upstreams() -> str:
    """List upstream MCP connection status known to this Hub process."""
    if _registry is None:
        return json.dumps({"status": "starting", "connected": [], "errors": {}})

    connected = [
        {
            "id": item.config.id,
            "namespace": item.config.namespace,
            "url": str(item.config.url),
            "tool_count": len(item.tools),
            "tools": list(item.tools),
        }
        for item in _registry.connected.values()
    ]
    return json.dumps(
        {
            "status": "running",
            "connected": connected,
            "errors": _registry.errors,
        }
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mcp-path", default="/mcp")
    return parser.parse_args()


async def _connect_upstreams() -> None:
    global _registry
    _registry = await start_registry()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO)

    asyncio.run(_connect_upstreams())

    if args.transport == "streamable-http":
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            path=args.mcp_path,
            stateless_http=True,
            json_response=True,
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
