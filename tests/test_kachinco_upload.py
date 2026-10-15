"""Producer-pinned schemas and opaque upload forwarding; no Hub media state."""

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
FIXTURE = json.loads((ROOT / "tests/fixtures/kachinco-media-upload-tools.json").read_text())
GUARD = {"runtimeId": "runtime", "documentToken": "document", "expectedRevision": "7"}
UPLOAD = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def config():
    return UpstreamConfig.model_validate(
        yaml.safe_load((ROOT / "config/mcps/_kachinco-media-upload.example.yaml").read_text())
    )


def registration(permission="edit"):
    configured = config().tools
    if permission == "readOnly":
        configured = [t for t in configured if t.name == "mcp.context"]
    return {
        "type": "register",
        "version": 1,
        "productId": "flamoris.kachinco",
        "runtimeId": "runtime",
        "documentToken": "document",
        "permission": permission,
        "tools": [{"name": t.name, "inputSchema": t.input_schema} for t in configured],
    }


def test_catalog_matches_producer_and_is_additive_only():
    actual = config()
    assert [
        {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
        for t in actual.tools
        if t.name != "mcp.context"
    ] == FIXTURE
    assert len(Catalog([actual]).tools) == 5


async def test_readonly_upload_denied_and_schema_mismatch_rejected():
    connection = ReverseConnection(config())
    socket = Socket()
    await socket.incoming.put(registration("readOnly"))
    serving = asyncio.create_task(connection.serve(socket))
    assert (await socket.outgoing.get())["type"] == "ready"
    with pytest.raises(LookupError, match="permission"):
        await connection.call_tool(None, "media_upload_begin", {})
    assert socket.outgoing.empty()
    await socket.close(1000)
    await serving

    wrong = Socket()
    hello = registration()
    hello["tools"][-1]["inputSchema"] = {"type": "object"}
    await wrong.incoming.put(hello)
    await connection.serve(wrong)
    assert wrong.closed and not connection.connected
    assert connection.catalog_mismatch == "desktop catalog schema mismatch"


async def test_official_http_client_forwards_maximum_chunk_and_never_replays(monkeypatch, tmp_path):
    ingress = "upload-ingress-fixture-at-least-32-characters"
    connector = "upload-desktop-fixture-at-least-32-characters"
    monkeypatch.setenv(TOKEN_ENV, ingress)
    monkeypatch.delenv(CLIENTS_FILE_ENV, raising=False)
    monkeypatch.setenv("KACHINCO_CONNECTOR_TOKEN", connector)
    monkeypatch.setenv("FLAMORIS_MCP_HUB_ENV_FILE", str(tmp_path / "absent"))
    catalog = Catalog([config()])
    registry = UpstreamRegistry(catalog)
    monkeypatch.setattr("flamoris_mcp_hub.server.start_registry", lambda: (catalog, registry))
    chunk = bytes(range(256)) * 512
    digest = hashlib.sha256(chunk).hexdigest()
    arguments = [
        (
            "media_upload_begin",
            {
                "uploadId": UPLOAD,
                "fileName": "voice.wav",
                "sizeBytes": str(len(chunk)),
                "sha256": digest,
            },
        ),
        (
            "media_upload_write",
            {
                "uploadId": UPLOAD,
                "offset": "0",
                "dataBase64": base64.b64encode(chunk).decode(),
                "chunkSha256": digest,
            },
        ),
        ("media_upload_finish", {"uploadId": UPLOAD}),
        ("media_upload_cancel", {"uploadId": UPLOAD}),
    ]
    receipts = [
        {
            "uploadId": UPLOAD,
            "receivedBytes": "0",
            "sizeBytes": str(len(chunk)),
            "chunkBytes": 131072,
        },
        {
            "uploadId": UPLOAD,
            "receivedBytes": str(len(chunk)),
            "sizeBytes": str(len(chunk)),
            "chunkBytes": 131072,
        },
        {"success": True, "revision": "8", "mediaAssetId": UPLOAD},
        {"error": {"code": "stale_revision"}},
    ]

    with anyio.fail_after(20):
        async with running(create_app()) as url:
            endpoint = url.replace("http://", "ws://").removesuffix("/mcp") + "/desktop/kachinco"
            async with (
                httpx2.AsyncClient(
                    headers={"Authorization": "Bearer " + ingress}, trust_env=False
                ) as client,
                streamable_http_client(url, http_client=client) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                advertised = {t.name for t in (await session.list_tools()).tools}
                assert "kachinco.media_upload_write" in advertised
                offline = await session.call_tool(
                    "kachinco.media_upload_finish", {"input": {"uploadId": UPLOAD}, "guard": GUARD}
                )
                assert offline.is_error
                async with connect(
                    endpoint, additional_headers={"Authorization": "Bearer " + connector}
                ) as desktop:
                    await desktop.send(json.dumps(registration()))
                    assert json.loads(await desktop.recv())["type"] == "ready"

                    async def respond():
                        for i, (name, payload) in enumerate(arguments):
                            request = json.loads(await desktop.recv())
                            assert request["name"] == name
                            assert request["arguments"] == {"input": payload, "guard": GUARD}
                            if name == "media_upload_write":
                                assert (
                                    base64.b64decode(request["arguments"]["input"]["dataBase64"])
                                    == chunk
                                )
                            receipt = receipts[i]
                            await desktop.send(
                                json.dumps(
                                    {
                                        "type": "result",
                                        "id": request["id"],
                                        "result": {
                                            "content": [
                                                {"type": "text", "text": json.dumps(receipt)}
                                            ],
                                            "structuredContent": receipt,
                                            "isError": i == 3,
                                        },
                                    }
                                )
                            )
                        uncertain = json.loads(await desktop.recv())
                        assert uncertain["name"] == "media_upload_finish"
                        await desktop.close()

                    reply = asyncio.create_task(respond())
                    try:
                        for i, (name, payload) in enumerate(arguments):
                            result = await session.call_tool(
                                "kachinco." + name, {"input": payload, "guard": GUARD}
                            )
                            assert result.structured_content == receipts[i]
                            assert result.is_error == (i == 3)
                        result = await session.call_tool(
                            "kachinco.media_upload_finish",
                            {"input": {"uploadId": UPLOAD}, "guard": GUARD},
                        )
                        assert result.is_error
                        assert "not retried" in result.content[0].text
                        await reply
                    finally:
                        reply.cancel()
                        await asyncio.gather(reply, return_exceptions=True)
                async with connect(
                    endpoint, additional_headers={"Authorization": "Bearer " + connector}
                ) as fresh:
                    await fresh.send(json.dumps(registration()))
                    assert json.loads(await fresh.recv())["type"] == "ready"
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(fresh.recv(), 0.05)
