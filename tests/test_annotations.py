from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.types import ListToolsResult
from pydantic import ValidationError

from flamoris_mcp_hub.config import Catalog, ToolConfig, UpstreamConfig, load_upstreams
from flamoris_mcp_hub.server import on_list_tools
from flamoris_mcp_hub.upstream import UpstreamRegistry

ROOT = Path(__file__).parents[1]


async def test_legacy_catalog_has_complete_conservative_wire_annotations():
    registry = UpstreamRegistry(
        Catalog(
            [
                UpstreamConfig(
                    id="legacy",
                    namespace="legacy",
                    url="https://example.invalid/mcp",
                    tools=[ToolConfig(name="looks.like.get")],
                )
            ]
        )
    )
    async with registry.run():
        result = await on_list_tools(SimpleNamespace(lifespan_context=registry), None)
        wire = result.model_dump(by_alias=True, exclude_none=True)
        assert wire["tools"][0]["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
            "idempotentHint": True,
        }
        assert wire["tools"][1]["annotations"] == {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": True,
        }
        assert registry._connections["legacy"]._started is False
        assert ListToolsResult.model_validate(wire).tools[1].annotations is not None


@pytest.mark.parametrize("template", sorted((ROOT / "config/mcps").glob("*.yaml")))
async def test_templates_preserve_explicit_annotations_offline(template, tmp_path):
    import yaml

    raw = yaml.safe_load(template.read_text())
    raw["enabled"] = True
    (tmp_path / "upstream.yaml").write_text(yaml.safe_dump(raw))
    configs = load_upstreams(tmp_path)
    registry = UpstreamRegistry(Catalog(configs))
    async with registry.run():
        listed = await on_list_tools(SimpleNamespace(lifespan_context=registry), None)
        wire = listed.model_dump(by_alias=True, exclude_none=True)
        exposed = {t["name"]: t for t in wire["tools"]}
        for tool in raw["tools"]:
            actual = exposed[f"{raw['namespace']}.{tool['name']}"]
            assert actual["annotations"] == tool["annotations"]
            assert actual["inputSchema"] == tool["input_schema"]
        assert all(not c.connected for c in registry._connections.values())
        if raw["transport"] == "streamable-http":
            assert all(not c._started for c in registry._connections.values())


@pytest.mark.parametrize(
    "field", ["readOnlyHint", "destructiveHint", "openWorldHint", "idempotentHint"]
)
@pytest.mark.parametrize("value", ["false", "true", 0, 1, [], {}])
def test_annotation_boolean_values_are_not_coerced(field, value):
    with pytest.raises(ValidationError):
        ToolConfig(name="tool", annotations={field: value})


@pytest.mark.parametrize("value", [None, [], "readonly", {"readOnlyHnit": True}])
def test_malformed_annotations_fail_config_load(tmp_path, value):
    import yaml

    (tmp_path / "bad.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "bad",
                "namespace": "bad",
                "url": "https://example.invalid/mcp",
                "tools": [{"name": "tool", "annotations": value}],
            }
        )
    )
    with pytest.raises(ValidationError):
        load_upstreams(tmp_path)


async def test_optional_mcp_annotation_fields_are_preserved():
    tool = ToolConfig(
        name="read",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
            "idempotentHint": True,
            "title": "Read current state",
        },
    )
    assert tool.annotations.to_mcp().model_dump(by_alias=True, exclude_none=True) == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "openWorldHint": False,
        "idempotentHint": True,
        "title": "Read current state",
    }


def test_partial_annotations_keep_conservative_missing_hints():
    wire = ToolConfig(name="tool", annotations={"readOnlyHint": True}).annotations.to_mcp()
    assert wire.read_only_hint is True
    assert wire.destructive_hint is True
    assert wire.open_world_hint is True


def test_generation_effects_are_not_misclassified(tmp_path):
    (tmp_path / "generation.yaml").write_text(
        (ROOT / "config/mcps/_generation.example.yaml").read_text()
    )
    tools = {t.name: t.annotations for t in load_upstreams(tmp_path)[0].tools}
    for name in [
        "workflows.build",
        "workflows.register",
        "workflows.save",
        "jobs.submit",
        "jobs.result",
        "assets.list",
        "assets.get",
        "assets.prepare",
        "inputs.create",
    ]:
        assert tools[name].read_only_hint is False
    for name in [
        "assets.delete",
        "inputs.delete",
        "jobs.cancel",
        "workflows.register",
        "workflows.save",
    ]:
        assert tools[name].destructive_hint is True
    for name in ["system.health", "models.list", "jobs.status", "inputs.get", "assets.read"]:
        assert tools[name].read_only_hint is True
        assert tools[name].destructive_hint is False
