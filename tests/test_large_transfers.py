"""Large opaque file blocks cross the authenticated MCP transport unchanged."""

import base64
import hashlib
import json

import httpx2

from flamoris_mcp_hub.auth import TOKEN_ENV
from flamoris_mcp_hub.server import MCP_REQUEST_BYTES, create_app
from flamoris_mcp_hub.upstream import UpstreamRegistry

TOKEN = "synthetic-large-transfer-token-" + "x" * 32


async def test_10mib_request_and_large_json_result(monkeypatch, tmp_path):
    encoded = base64.b64encode(b"x" * (10 * 1024**2)).decode()
    sha = "sha256:" + hashlib.sha256(b"x" * (10 * 1024**2)).hexdigest()
    (tmp_path / "files.yaml").write_text(
        json.dumps(
            {
                "id": "files",
                "namespace": "files_test",
                "url": "https://example.invalid/mcp",
                "tools": [
                    {
                        "name": "files_upload_write",
                        "input_schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "data_base64": {"type": "string", "maxLength": len(encoded)}
                            },
                            "required": ["data_base64"],
                        },
                    }
                ],
            }
        )
    )
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    monkeypatch.setenv("FLAMORIS_MCP_HUB_ENV_FILE", str(tmp_path / "absent"))
    monkeypatch.setenv("FLAMORIS_MCP_HUB_CONFIG_DIR", str(tmp_path))
    calls = []

    async def forward(_self, name, arguments, identity=None):
        from mcp.types import CallToolResult, TextContent

        assert arguments == {"data_base64": encoded}
        calls.append(name)
        # Files returns both text content and structured content. This response
        # exceeds common 1 MiB SSE defaults and must remain complete.
        value = {"data_base64": encoded, "chunk_sha256": sha}
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(value))],
            structured_content=value,
        )

    monkeypatch.setattr(UpstreamRegistry, "call_public_tool", forward)
    app = create_app()
    async with (
        app.app.app.router.lifespan_context(app.app.app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://localhost:8765"
        ) as client,
    ):
        headers = {
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/json, text/event-stream",
        }
        initialized = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "synthetic-transfer", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200
        headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        headers["MCP-Protocol-Version"] = initialized.json()["result"]["protocolVersion"]
        result = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "files_test.files_upload_write",
                    "arguments": {"data_base64": encoded},
                },
            },
        )
        assert result.status_code == 200
        assert result.headers["content-type"].startswith("application/json")
        value = result.json()["result"]
        assert not value["isError"]
        assert value["structuredContent"]["data_base64"] == encoded
        assert value["structuredContent"]["chunk_sha256"] == sha
        oversized = await client.post(
            "/mcp", headers=headers, content=b"x" * (MCP_REQUEST_BYTES + 1)
        )
        assert oversized.status_code == 413
    assert calls == ["files_test.files_upload_write"]
