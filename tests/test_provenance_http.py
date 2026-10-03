"""Real official SDK transport: two credentials share one upstream safely."""

import asyncio
import hashlib
import hmac
import json
import socket
from contextlib import asynccontextmanager

import anyio
import httpx2
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.types import CallToolResult, ListToolsResult, Tool

from flamoris_mcp_hub.auth import CLIENTS_FILE_ENV, TOKEN_ENV
from flamoris_mcp_hub.config import Catalog, ToolConfig, UpstreamConfig
from flamoris_mcp_hub.provenance import META_KEY
from flamoris_mcp_hub.server import create_app
from flamoris_mcp_hub.upstream import UpstreamRegistry

SECRET = "independent-signing-secret-with-at-least-32-characters"
ANONYMOUS = "shared-legacy-client-credential-with-at-least-32-characters"
TOKEN_A = "credential-for-client-a-with-at-least-32-characters"
TOKEN_B = "credential-for-client-b-with-at-least-32-characters"
SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


@asynccontextmanager
async def running(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    service = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    )
    task = asyncio.create_task(service.serve(sockets=[sock]))
    try:
        with anyio.fail_after(5):
            while not service.started:
                if task.done():
                    await task
                await anyio.sleep(0.01)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        service.should_exit = True
        with anyio.fail_after(5):
            await task
        sock.close()


async def test_actual_http_ingress_credentials_bind_signed_calls_without_session_leak(
    monkeypatch, tmp_path, caplog
):
    received = []
    connections = []
    from flamoris_mcp_hub import upstream

    original_client = upstream._http_client

    def counted_client(*, headers):
        connections.append(headers)
        return original_client(headers=headers)

    monkeypatch.setattr(upstream, "_http_client", counted_client)

    async def list_tools(ctx, params):
        return ListToolsResult(tools=[Tool(name="jobs.submit", input_schema=SCHEMA)])

    async def call_tool(ctx, params):
        envelope = (ctx.meta or {}).get(META_KEY)
        if envelope is not None:
            unsigned = {key: value for key, value in envelope.items() if key != "signature"}
            canonical = json.dumps(
                {**unsigned, "tool": params.name, "arguments": params.arguments or {}},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode()
            expected = hmac.new(SECRET.encode(), canonical, hashlib.sha256).hexdigest()
            assert hmac.compare_digest(expected, envelope["signature"])
        received.append(envelope)
        return CallToolResult(content=[])

    downstream = Server("test generation", on_list_tools=list_tools, on_call_tool=call_tool)
    async with running(downstream.streamable_http_app()) as downstream_url:
        monkeypatch.setenv(TOKEN_ENV, ANONYMOUS)
        monkeypatch.setenv("CLIENT_A", TOKEN_A)
        monkeypatch.setenv("CLIENT_B", TOKEN_B)
        monkeypatch.setenv("SIGNING_SECRET", SECRET)
        monkeypatch.setenv("FLAMORIS_MCP_HUB_ENV_FILE", str(tmp_path / "absent"))
        clients = tmp_path / "clients.json"
        clients.write_text(
            json.dumps(
                {
                    "issuer": "hub.example",
                    "clients": [
                        {"subject": "opaque-a", "token_env": "CLIENT_A"},
                        {"subject": "opaque-b", "token_env": "CLIENT_B"},
                    ],
                }
            )
        )
        monkeypatch.setenv(CLIENTS_FILE_ENV, str(clients))
        config = UpstreamConfig(
            id="generation",
            namespace="generation",
            url=downstream_url,
            external_provenance_secret_env="SIGNING_SECRET",
            tools=[ToolConfig(name="jobs.submit", input_schema=SCHEMA)],
        )
        catalog = Catalog([config])
        registry = UpstreamRegistry(catalog)
        monkeypatch.setattr("flamoris_mcp_hub.server.start_registry", lambda: (catalog, registry))
        async with running(create_app()) as hub_url:
            for credential in (TOKEN_A, TOKEN_B, ANONYMOUS, TOKEN_A):
                session_ids = []

                async def capture_response(response, session_ids=session_ids):
                    if "mcp-session-id" in response.headers:
                        session_ids.append(response.headers["mcp-session-id"])

                async with (
                    httpx2.AsyncClient(
                        headers={"Authorization": "Bearer " + credential},
                        trust_env=False,
                        event_hooks={"response": [capture_response]},
                    ) as client,
                    streamable_http_client(hub_url, http_client=client) as streams,
                    ClientSession(*streams) as session,
                ):
                    await session.initialize()
                    if credential == TOKEN_A:
                        assert (
                            await client.post(
                                hub_url,
                                headers={
                                    "Authorization": "Bearer " + TOKEN_B,
                                    "Mcp-Session-Id": session_ids[-1],
                                },
                                json={},
                            )
                        ).status_code == 403
                    result = await session.call_tool(
                        "generation.jobs.submit",
                        {},
                        meta={META_KEY: {"issuer": "forged", "subject": "forged"}},
                    )
                    assert not result.is_error
        assert [entry["subject"] if entry else None for entry in received] == [
            "opaque-a",
            "opaque-b",
            None,
            "opaque-a",
        ]
        assert len({entry["nonce"] for entry in received if entry}) == 3
        assert all(entry["issuer"] == "hub.example" for entry in received if entry)
        assert registry._connections["generation"]._started
        assert len(connections) == 1
        assert "Upstream cleanup failed" not in caplog.text
