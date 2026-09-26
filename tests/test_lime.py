import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, TextContent

from flamoris_mcp_hub.config import Catalog, load_upstreams
from flamoris_mcp_hub.server import on_list_tools
from flamoris_mcp_hub.upstream import UpstreamRegistry

ROOT = Path(__file__).parents[1]
FIXTURE = json.loads((ROOT / "tests/fixtures/lime-tools.json").read_text())


def catalog(tmp_path):
    (tmp_path / "lime.yaml").write_text((ROOT / "config/mcps/_lime.example.yaml").read_text())
    return Catalog(load_upstreams(tmp_path))


def test_lime_catalog_matches_pinned_upstream(tmp_path):
    assert load_upstreams(ROOT / "config/mcps") == []
    configs = catalog(tmp_path)
    assert {name for name in configs.tools} == {
        "lime.runtime.list",
        "lime.runtime.status",
        "lime.runtime.activate",
        "lime.runtime.stop",
        "lime.system.status",
    }
    assert [t.model_dump() for t in configs.configs["lime"].tools] == FIXTURE["tools"]
    assert configs.configs["lime"].headers() == {}


@pytest.mark.parametrize("mismatch,fail_call", [(False, False), (True, False), (False, True)])
async def test_lime_lazy_schema_gate_and_no_replay(tmp_path, monkeypatch, mismatch, fail_call):
    state = {"connects": 0, "calls": []}

    @asynccontextmanager
    async def http_client(**kwargs):
        assert kwargs["headers"] == {}
        yield object()

    @asynccontextmanager
    async def transport(*args, **kwargs):
        state["connects"] += 1
        yield object(), object()

    class Session:
        async def initialize(self):
            pass

        async def list_tools(self):
            tools = [SimpleNamespace(**t) for t in FIXTURE["tools"]]
            if mismatch:
                tools[2].input_schema = {"type": "object"}
            return SimpleNamespace(tools=tools)

        async def call_tool(self, name, arguments):
            state["calls"].append((name, arguments))
            if fail_call:
                raise ConnectionError("ambiguous activation")
            return CallToolResult(content=[TextContent(type="text", text="ready")])

    @asynccontextmanager
    async def session(*args):
        yield Session()

    monkeypatch.setattr("flamoris_mcp_hub.upstream._http_client", http_client)
    monkeypatch.setattr("flamoris_mcp_hub.upstream.streamable_http_client", transport)
    monkeypatch.setattr("flamoris_mcp_hub.upstream.ClientSession", session)
    hub = UpstreamRegistry(catalog(tmp_path))
    async with hub.run():
        listed = await on_list_tools(SimpleNamespace(lifespan_context=hub), None)
        assert len(listed.tools) == 6
        assert state["connects"] == 0
        if mismatch or fail_call:
            with pytest.raises((LookupError, ConnectionError)):
                await hub.call_public_tool("lime.runtime.activate", {"runtime_id": "comfyui"})
            assert len(state["calls"]) == (0 if mismatch else 1)
        else:
            await hub.call_public_tool("lime.runtime.activate", {"runtime_id": "comfyui"})
            await hub.call_public_tool("lime.runtime.status", {"runtime_id": "comfyui"})
            assert state["calls"] == [
                ("runtime.activate", {"runtime_id": "comfyui"}),
                ("runtime.status", {"runtime_id": "comfyui"}),
            ]
        assert state["connects"] == 1
