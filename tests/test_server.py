import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.types import CallToolRequestParams

from flamoris_mcp_hub.config import Catalog, ToolConfig, UpstreamConfig, load_upstreams
from flamoris_mcp_hub.server import on_call_tool, on_list_tools, transport_security
from flamoris_mcp_hub.upstream import UpstreamRegistry


@pytest.mark.asyncio
async def test_static_catalog_while_offline(monkeypatch):
    config = UpstreamConfig(
        id="offline",
        namespace="offline",
        url="https://example.invalid/mcp",
        tools=[ToolConfig(name="jobs.submit")],
    )
    registry = UpstreamRegistry(Catalog([config]))
    ctx = SimpleNamespace(lifespan_context=registry)
    async with registry.run():
        result = await on_list_tools(ctx, None)
        assert [t.name for t in result.tools] == ["hub.upstreams.list", "offline.jobs.submit"]
        status = await on_call_tool(
            ctx, CallToolRequestParams(name="hub.upstreams.list", arguments={})
        )
        assert json.loads(status.content[0].text)["upstreams"][0]["connected"] is False
        assert registry._connections["offline"]._started is False


@pytest.mark.asyncio
async def test_server_returns_upstream_error_without_dying(monkeypatch):
    config = UpstreamConfig(
        id="offline",
        namespace="offline",
        url="https://example.invalid/mcp",
        tools=[ToolConfig(name="jobs.submit")],
        api_key_env="MISSING_TEST_SECRET",
    )
    monkeypatch.delenv("MISSING_TEST_SECRET", raising=False)
    registry = UpstreamRegistry(Catalog([config]))
    ctx = SimpleNamespace(lifespan_context=registry)
    async with registry.run():
        result = await on_call_tool(
            ctx, CallToolRequestParams(name="offline.jobs.submit", arguments={})
        )
        assert result.is_error
        assert "unavailable" in result.content[0].text
        listed = await on_list_tools(ctx, None)
        assert len(listed.tools) == 2


def test_invalid_schema_fails_config_load(tmp_path: Path):
    (tmp_path / "bad.yaml").write_text(
        "id: bad\nnamespace: bad\nurl: https://example.invalid/mcp\n"
        "tools:\n  - name: tool\n    input_schema:\n      type: object\n"
        "      properties:\n        thing:\n          type: nonsense\n"
    )
    with pytest.raises(ValueError, match="invalid input_schema"):
        load_upstreams(tmp_path)


def test_explicit_proxy_host_allowlist(monkeypatch):
    monkeypatch.setenv("FLAMORIS_MCP_HUB_ALLOWED_HOSTS", "mcp.flamoris.net")
    monkeypatch.setenv("FLAMORIS_MCP_HUB_ALLOWED_ORIGINS", "https://chatgpt.com")
    settings = transport_security()
    assert settings.enable_dns_rebinding_protection
    assert "mcp.flamoris.net" in settings.allowed_hosts
    assert "https://chatgpt.com" in settings.allowed_origins
    monkeypatch.setenv("FLAMORIS_MCP_HUB_ALLOWED_HOSTS", "*")
    with pytest.raises(ValueError, match="wildcard"):
        transport_security()
