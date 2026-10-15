"""Producer-pinned clip schemas and opaque, bounded download forwarding."""

import asyncio
import base64
import hashlib
import json
from pathlib import Path

import anyio
import httpx2
import pytest
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from test_provenance_http import running
from test_reverse import Socket
from websockets.asyncio.client import connect

from flamoris_mcp_hub.auth import CLIENTS_FILE_ENV, TOKEN_ENV
from flamoris_mcp_hub.config import Catalog, UpstreamConfig
from flamoris_mcp_hub.reverse import ReverseConnection
from flamoris_mcp_hub.server import create_app
from flamoris_mcp_hub.upstream import UpstreamRegistry

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests/fixtures/kachinco-clip-tools.json").read_text())
GUARD = {"runtimeId": "runtime", "documentToken": "document", "expectedRevision": "7"}
DOWNLOAD = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def config():
    return UpstreamConfig.model_validate(
        yaml.safe_load((ROOT / "config/mcps/_kachinco-clips.example.yaml").read_text())
    )


def registration(permission="readOnly"):
    tools = config().tools
    if permission == "readOnly":
        tools = [t for t in tools if t.name != "edit_batch"]
    return {
        "type": "register",
        "version": 1,
        "productId": "flamoris.kachinco",
        "runtimeId": "runtime",
        "documentToken": "document",
        "permission": permission,
        "tools": [{"name": t.name, "inputSchema": t.input_schema} for t in tools],
    }


def test_catalog_matches_producer_and_speed_is_in_shared_edit_batch():
    actual = config()
    assert [
        {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
        for t in actual.tools
        if t.name != "mcp.context"
    ] == FIXTURE
    assert len(Catalog([actual]).tools) == 6
    commands = actual.tools[1].input_schema["properties"]["input"]["properties"]["commands"]
    speed = next(
        c for c in commands["items"]["oneOf"]
        if c["properties"]["type"]["const"] == "SetClipSpeed"
    )
    assert speed["properties"]["playbackRate"]["enum"] == [1, 2, 4, 8]


async def test_readonly_download_allowed_but_editing_denied_and_old_schema_rejected():
    connection = ReverseConnection(config())
    socket = Socket()
    await socket.incoming.put(registration())
    serving = asyncio.create_task(connection.serve(socket))
    assert (await socket.outgoing.get())["type"] == "ready"
    with pytest.raises(LookupError, match="permission"):
        await connection.call_tool(None, "edit_batch", {})
    assert socket.outgoing.empty()
    call = asyncio.create_task(connection.call_tool(None, "clip_download_status", {}))
    request = await socket.outgoing.get()
    assert request["name"] == "clip_download_status"
    await socket.incoming.put({"type": "result", "id": request["id"], "result": {
        "content": [{"type": "text", "text": "ready"}], "isError": False,
    }})
    assert not (await call).is_error
    await socket.close(1000)
    await serving
    wrong = Socket()
    hello = registration("edit")
    hello["tools"][1]["inputSchema"] = {"type": "object"}
    await wrong.incoming.put(hello)
    await connection.serve(wrong)
    assert wrong.closed and connection.catalog_mismatch == "desktop catalog schema mismatch"


async def test_official_http_client_receives_maximum_chunk_and_errors(monkeypatch, tmp_path):
    ingress = "clip-ingress-fixture-at-least-32-characters"
    connector = "clip-desktop-fixture-at-least-32-characters"
    monkeypatch.setenv(TOKEN_ENV, ingress)
    monkeypatch.delenv(CLIENTS_FILE_ENV, raising=False)
    monkeypatch.setenv("KACHINCO_CONNECTOR_TOKEN", connector)
    monkeypatch.setenv("FLAMORIS_MCP_HUB_ENV_FILE", str(tmp_path / "absent"))
    catalog = Catalog([config()])
    registry = UpstreamRegistry(catalog)
    monkeypatch.setattr("flamoris_mcp_hub.server.start_registry", lambda: (catalog, registry))
    chunk = bytes(range(256)) * 512
    receipt = {
        "downloadId": DOWNLOAD, "offset": "0", "count": len(chunk),
        "dataBase64": base64.b64encode(chunk).decode(),
        "chunkSha256": hashlib.sha256(chunk).hexdigest(), "eof": True,
    }
    with anyio.fail_after(20):
        async with running(create_app()) as url:
            endpoint = url.replace("http://", "ws://").removesuffix("/mcp") + "/desktop/kachinco"
            async with (
                httpx2.AsyncClient(headers={"Authorization": "Bearer " + ingress},
                                  trust_env=False) as client,
                streamable_http_client(url, http_client=client) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                assert "kachinco.clip_download_read" in {
                    t.name for t in (await session.list_tools()).tools
                }
                async with connect(endpoint, additional_headers={
                    "Authorization": "Bearer " + connector,
                }) as desktop:
                    await desktop.send(json.dumps(registration()))
                    assert json.loads(await desktop.recv())["type"] == "ready"

                    async def respond():
                        for name, value, error in (
                            ("clip_download_read", receipt, False),
                            ("clip_download_status", {"error": {"code": "stale_revision"}}, True),
                        ):
                            request = json.loads(await desktop.recv())
                            assert request["name"] == name
                            assert request["arguments"]["guard"] == GUARD
                            await desktop.send(json.dumps({
                                "type": "result", "id": request["id"], "result": {
                                    "content": [{"type": "text", "text": json.dumps(value)}],
                                    "structuredContent": value, "isError": error,
                                },
                            }))

                    reply = asyncio.create_task(respond())
                    try:
                        result = await session.call_tool("kachinco.clip_download_read", {
                            "input": {"downloadId": DOWNLOAD, "offset": "0", "count": 131072},
                            "guard": GUARD,
                        })
                        assert not result.is_error and result.structured_content == receipt
                        assert base64.b64decode(result.structured_content["dataBase64"]) == chunk
                        result = await session.call_tool("kachinco.clip_download_status", {
                            "input": {"downloadId": DOWNLOAD}, "guard": GUARD,
                        })
                        assert result.is_error
                        assert result.structured_content == {"error": {"code": "stale_revision"}}
                        await reply
                    finally:
                        reply.cancel()
                        await asyncio.gather(reply, return_exceptions=True)
