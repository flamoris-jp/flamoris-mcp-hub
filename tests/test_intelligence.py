import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from mcp.types import CallToolResult, TextContent
from test_upstream import FakeSession
from test_upstream import fake_transport as upstream_transport

from flamoris_mcp_hub.config import Catalog, load_upstreams
from flamoris_mcp_hub.server import on_list_tools
from flamoris_mcp_hub.upstream import UpstreamRegistry

fake_transport = upstream_transport
ROOT = Path(__file__).parents[1]


def catalog(tmp_path):
    (tmp_path / "intelligence.yaml").write_text(
        (ROOT / "config/mcps/_intelligence.example.yaml").read_text()
    )
    return Catalog(load_upstreams(tmp_path))


async def test_exact_exported_contract_and_offline_discovery(tmp_path, fake_transport):
    configured = catalog(tmp_path)
    exported = json.loads((ROOT / "tests/fixtures/intelligence-tools.json").read_text())
    raw = yaml.safe_load((ROOT / "config/mcps/_intelligence.example.yaml").read_text())
    assert {t["name"] for t in raw["tools"]} == set(exported)
    for tool in raw["tools"]:
        assert {
            "input_schema": tool["input_schema"],
            "annotations": tool["annotations"],
        } == exported[tool["name"]]
    assert exported["inference.execute"]["annotations"]["idempotentHint"] is False
    hub = UpstreamRegistry(configured)
    async with hub.run():
        listed = await on_list_tools(SimpleNamespace(lifespan_context=hub), None)
        names = {tool.name for tool in listed.tools}
        assert names == {"hub.upstreams.list", *("intelligence." + name for name in exported)}
    assert fake_transport["connections"] == 0 and fake_transport["calls"] == 0


@pytest.mark.parametrize("error", [False, True])
async def test_inference_arguments_results_and_errors_forward_unchanged(
    tmp_path, fake_transport, monkeypatch, error
):
    configured = catalog(tmp_path)
    fake_transport["tools"] = [
        SimpleNamespace(
            name=t.name, input_schema=t.input_schema, annotations=t.annotations.to_mcp()
        )
        for t in configured.configs["intelligence"].tools
    ]
    original = FakeSession.call_tool
    data = (
        {"ok": False, "error": {"code": "provider_timeout"}}
        if error
        else {"ok": True, "text": "bounded answer", "finish_reason": "length"}
    )
    expected = CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data))],
        structured_content=data,
        is_error=error,
    )

    async def call(self, name, arguments):
        await original(self, name, arguments)
        return expected

    monkeypatch.setattr(FakeSession, "call_tool", call)
    args = {"request": {"model_id": "local", "input": "explicit request", "temperature": 0}}
    hub = UpstreamRegistry(configured)
    async with hub.run():
        actual = await hub.call_public_tool("intelligence.inference.execute", args)
        assert actual is expected
    assert fake_transport["requests"] == [("inference.execute", args)]
    assert fake_transport["calls"] == 1


@pytest.mark.parametrize("mode", ["duplicate", "paginated"])
async def test_ambiguous_catalog_blocks_dispatch_then_recovers(tmp_path, fake_transport, mode):
    configured = catalog(tmp_path)
    tools = [
        SimpleNamespace(
            name=t.name, input_schema=t.input_schema, annotations=t.annotations.to_mcp()
        )
        for t in configured.configs["intelligence"].tools
    ]
    fake_transport["tools"] = tools + [tools[0]] if mode == "duplicate" else tools
    fake_transport["next_cursor"] = "another-page" if mode == "paginated" else None
    hub = UpstreamRegistry(configured)
    async with hub.run():
        with pytest.raises(LookupError, match="invalid tools/list"):
            await hub.call_public_tool("intelligence.system.health", {})
        assert fake_transport["calls"] == 0
        assert hub.status()[0]["catalog_mismatch"]
        fake_transport.update(tools=tools, next_cursor=None)
        await hub.call_public_tool("intelligence.system.health", {})
        assert hub.status()[0]["catalog_mismatch"] is None
    assert fake_transport["requests"] == [("system.health", {})]
