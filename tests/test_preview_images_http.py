"""External official MCP client -> HTTP Hub -> outbound desktop WebSocket image."""

import asyncio
import base64
import json

import anyio
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from test_provenance_http import running
from websockets.asyncio.client import connect

from flamoris_mcp_hub.auth import CLIENTS_FILE_ENV, TOKEN_ENV
from flamoris_mcp_hub.config import Catalog, ToolConfig, UpstreamConfig
from flamoris_mcp_hub.server import create_app
from flamoris_mcp_hub.upstream import UpstreamRegistry

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9xkAAAAASUVORK5CYII="


async def test_external_client_receives_desktop_image_through_hub(monkeypatch, tmp_path):
    ingress = "image-ingress-fixture-at-least-32-characters"
    connector = "image-desktop-fixture-at-least-32-characters"
    monkeypatch.setenv(TOKEN_ENV, ingress)
    monkeypatch.delenv(CLIENTS_FILE_ENV, raising=False)
    monkeypatch.setenv("PREVIEW_CONNECTOR", connector)
    monkeypatch.setenv("FLAMORIS_MCP_HUB_ENV_FILE", str(tmp_path / "absent"))
    config = UpstreamConfig(
        id="kachinco",
        namespace="kachinco",
        transport="reverse-websocket",
        product_id="flamoris.kachinco",
        connector_token_env="PREVIEW_CONNECTOR",
        tools=[
            ToolConfig(name="mcp.context", input_schema=SCHEMA),
            ToolConfig(name="preview_frame", input_schema=SCHEMA),
        ],
    )
    catalog = Catalog([config])
    registry = UpstreamRegistry(catalog)
    monkeypatch.setattr("flamoris_mcp_hub.server.start_registry", lambda: (catalog, registry))
    async with running(create_app()) as url:
        endpoint = url.replace("http://", "ws://").removesuffix("/mcp") + "/desktop/kachinco"
        async with connect(
            endpoint, additional_headers={"Authorization": "Bearer " + connector}
        ) as desktop:
            await desktop.send(
                json.dumps(
                    {
                        "type": "register",
                        "version": 1,
                        "productId": "flamoris.kachinco",
                        "runtimeId": "runtime",
                        "documentToken": "document",
                        "permission": "readOnly",
                        "tools": [
                            {"name": "mcp.context", "inputSchema": SCHEMA},
                            {"name": "preview_frame", "inputSchema": SCHEMA},
                        ],
                    }
                )
            )
            assert json.loads(await desktop.recv())["type"] == "ready"

            async def respond():
                request = json.loads(await desktop.recv())
                assert request["name"] == "preview_frame"
                await desktop.send(
                    json.dumps(
                        {
                            "type": "result",
                            "id": request["id"],
                            "result": {
                                "content": [
                                    {"type": "image", "mimeType": "image/png", "data": PNG}
                                ],
                                "structuredContent": {
                                    "projectRevision": "5",
                                    "width": 1,
                                    "height": 1,
                                },
                                "isError": False,
                            },
                        }
                    )
                )

            reply = asyncio.create_task(respond())
            try:
                with anyio.fail_after(10):
                    async with (
                        httpx2.AsyncClient(
                            headers={"Authorization": "Bearer " + ingress}, trust_env=False
                        ) as client,
                        streamable_http_client(url, http_client=client) as streams,
                        ClientSession(*streams) as session,
                    ):
                        await session.initialize()
                        result = await session.call_tool("kachinco.preview_frame", {})
                        assert not result.is_error
                        assert result.content[0].type == "image"
                        assert result.content[0].mime_type == "image/png"
                        assert base64.b64decode(result.content[0].data) == base64.b64decode(PNG)
                        assert result.structured_content == {
                            "projectRevision": "5",
                            "width": 1,
                            "height": 1,
                        }
                await reply
            finally:
                reply.cancel()
                await asyncio.gather(reply, return_exceptions=True)
