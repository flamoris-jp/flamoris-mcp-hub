import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from mcp.types import CallToolResult
from test_upstream import FakeSession
from test_upstream import fake_transport as upstream_transport

from flamoris_mcp_hub.config import Catalog, load_upstreams
from flamoris_mcp_hub.server import on_list_tools
from flamoris_mcp_hub.upstream import UpstreamRegistry

fake_transport = upstream_transport
ROOT = Path(__file__).parents[1]
V3_NAMES = {"workflows.v3." + name for name in ("register", "list", "build", "verify", "revoke")}
EXPORTED = json.loads((ROOT / "tests/fixtures/generation-v3-tools.json").read_text())


def catalog(tmp_path, *, v3=True):
    template = "_generation-v3.example.yaml" if v3 else "_generation.example.yaml"
    (tmp_path / "generation.yaml").write_text((ROOT / "config/mcps" / template).read_text())
    return Catalog(load_upstreams(tmp_path))


def tools(exported):
    return [SimpleNamespace(name=k, input_schema=v["input_schema"]) for k, v in exported.items()]


async def test_exact_opt_in_catalog_offline_discovery_and_legacy_parity(tmp_path, fake_transport):
    legacy = json.loads((ROOT / "tests/fixtures/generation-tools.json").read_text())
    assert set(EXPORTED) == set(legacy) | V3_NAMES
    assert all(EXPORTED[name] == spec for name, spec in legacy.items())
    raw = yaml.safe_load((ROOT / "config/mcps/_generation-v3.example.yaml").read_text())
    assert {t["name"] for t in raw["tools"]} == set(EXPORTED)
    for tool in raw["tools"]:
        assert {k: tool[k] for k in ("input_schema", "annotations")} == EXPORTED[tool["name"]]
    assert EXPORTED["workflows.v3.build"]["input_schema"]["properties"]["require_ready"]["default"]
    hub = UpstreamRegistry(catalog(tmp_path))
    async with hub.run():
        listed = await on_list_tools(SimpleNamespace(lifespan_context=hub), None)
        assert {t.name for t in listed.tools} == {
            "hub.upstreams.list",
            *("generation." + n for n in EXPORTED),
        }
    assert fake_transport["connections"] == fake_transport["calls"] == 0
    # Tracked optional templates remain ignored by normal startup.
    assert not load_upstreams(ROOT / "config/mcps")


@pytest.mark.parametrize("outcome", ["ready", "verification_failed", "submission_unknown"])
async def test_pinned_arguments_and_opaque_authority_results(
    tmp_path, fake_transport, monkeypatch, outcome
):
    configured = catalog(tmp_path)
    fake_transport["tools"] = tools(EXPORTED)
    expected = CallToolResult(
        content=[], structured_content={"state": outcome}, is_error=outcome != "ready"
    )
    original = FakeSession.call_tool

    async def call(self, name, arguments):
        await original(self, name, arguments)
        return expected

    monkeypatch.setattr(FakeSession, "call_tool", call)
    pin = {
        "workflow_id": "image-parent",
        "definition_version": 1,
        "definition_digest": "sha256:" + "a" * 64,
    }
    calls = [
        ("workflows.v3.register", {"definition": {"schema_version": 3}}),
        ("workflows.v3.list", {}),
        (
            "workflows.v3.build",
            pin | {"parameters": {"positive_prompt": "explicit"}, "require_ready": True},
        ),
        ("workflows.v3.verify", pin | {"parameters": {"positive_prompt": "explicit"}}),
        ("workflows.v3.revoke", pin),
        ("jobs.submit", {"workflow_id": "opaque-handle"}),
    ]
    hub = UpstreamRegistry(configured)
    async with hub.run():
        for name, args in calls:
            assert await hub.call_public_tool("generation." + name, args) is expected
    assert fake_transport["requests"] == calls


async def test_v3_catalog_blocks_old_upstream_then_recovers(tmp_path, fake_transport):
    fake_transport["tools"] = tools({k: v for k, v in EXPORTED.items() if k not in V3_NAMES})
    hub = UpstreamRegistry(catalog(tmp_path))
    async with hub.run():
        with pytest.raises(LookupError, match="catalog mismatch"):
            await hub.call_public_tool("generation.system.health", {})
        assert fake_transport["calls"] == 0
        fake_transport["tools"] = tools(EXPORTED)
        await hub.call_public_tool("generation.system.health", {})
    assert fake_transport["calls"] == 1


async def test_legacy_catalog_accepts_upgraded_upstream_without_exposing_v3(
    tmp_path, fake_transport
):
    fake_transport["tools"] = tools(EXPORTED)
    hub = UpstreamRegistry(catalog(tmp_path, v3=False))
    async with hub.run():
        await hub.call_public_tool("generation.system.health", {})
        with pytest.raises(LookupError):
            await hub.call_public_tool("generation.workflows.v3.list", {})
    assert fake_transport["calls"] == 1


async def test_ambiguous_v3_verify_is_never_replayed(tmp_path, fake_transport):
    fake_transport.update(tools=tools(EXPORTED), fail_call=True)
    hub = UpstreamRegistry(catalog(tmp_path))
    args = {
        "workflow_id": "parent",
        "definition_version": 1,
        "definition_digest": "sha256:" + "a" * 64,
        "parameters": {},
    }
    async with hub.run():
        with pytest.raises(ConnectionError, match="not retried"):
            await hub.call_public_tool("generation.workflows.v3.verify", args)
    assert fake_transport["requests"] == [("workflows.v3.verify", args)]
