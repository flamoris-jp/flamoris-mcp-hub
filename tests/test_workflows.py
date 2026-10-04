import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from mcp.types import CallToolResult
from test_upstream import FakeSession
from test_upstream import fake_transport as upstream_transport

from flamoris_mcp_hub.config import Catalog, load_upstreams
from flamoris_mcp_hub.upstream import UpstreamRegistry

fake_transport = upstream_transport
ROOT = Path(__file__).parents[1]


def test_exported_generation_schema_and_annotation_parity():
    actual = json.loads((ROOT / "tests/fixtures/generation-tools.json").read_text())
    tools = yaml.safe_load((ROOT / "config/mcps/_generation.example.yaml").read_text())["tools"]
    assert {t["name"] for t in tools} == set(actual)
    for tool in tools:
        assert {"input_schema": tool["input_schema"], "annotations": tool["annotations"]} == actual[
            tool["name"]
        ]


@pytest.mark.parametrize("outcome", ["queued", "completed", "failed", "outcome_unknown"])
async def test_opaque_generation_forwarding_no_replay(
    tmp_path, fake_transport, monkeypatch, outcome
):
    (tmp_path / "generation.yaml").write_text(
        (ROOT / "config/mcps/_generation.example.yaml").read_text()
    )
    catalog = Catalog(load_upstreams(tmp_path))
    fake_transport["tools"] = [
        SimpleNamespace(
            name=t.name, input_schema=t.input_schema, annotations=t.annotations.to_mcp()
        )
        for t in catalog.configs["generation"].tools
    ]
    original = FakeSession.call_tool

    async def result(self, name, arguments):
        await original(self, name, arguments)
        return CallToolResult(content=[], structured_content={"job": {"state": outcome}})

    monkeypatch.setattr(FakeSession, "call_tool", result)
    calls = [
        ("workflows.build", {"template": "text-to-image", "parameters": {}}),
        ("workflows.save", {"workflow_id": "opaque-built-recipe"}),
        ("jobs.submit", {"workflow_id": "opaque-built-recipe"}),
        ("jobs.status", {"job_id": "job"}),
        ("jobs.result", {"job_id": "job"}),
    ]
    hub = UpstreamRegistry(catalog)
    async with hub.run():
        for name, args in calls:
            received = await hub.call_public_tool("generation." + name, args)
            assert received.structured_content == {"job": {"state": outcome}}
    assert fake_transport["requests"] == calls


async def test_old_catalog_blocks_unchanged_health_before_forward(tmp_path, fake_transport):
    (tmp_path / "generation.yaml").write_text(
        (ROOT / "config/mcps/_generation.example.yaml").read_text()
    )
    catalog = Catalog(load_upstreams(tmp_path))
    fake_transport["tools"] = [
        SimpleNamespace(
            name=t.name, input_schema=t.input_schema, annotations=t.annotations.to_mcp()
        )
        for t in catalog.configs["generation"].tools
    ]
    build = next(t for t in fake_transport["tools"] if t.name == "workflows.build")
    build.input_schema = {"type": "object", "properties": {}}
    hub = UpstreamRegistry(catalog)
    async with hub.run():
        with pytest.raises(LookupError, match="catalog mismatch"):
            await hub.call_public_tool("generation.system.health", {})
        assert fake_transport["calls"] == 0
        build.input_schema = next(
            t.input_schema for t in catalog.configs["generation"].tools if t.name == build.name
        )
        assert not (await hub.call_public_tool("generation.system.health", {})).is_error
        assert fake_transport["calls"] == 1
