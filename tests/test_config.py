from pathlib import Path

import pytest
import yaml

from flamoris_mcp_hub.config import Catalog, load_upstreams


def test_generation_template_exposes_workflow_and_delete_schema(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GENERATION_MCP_API_KEY", raising=False)
    template = Path(__file__).parents[1] / "config/mcps/_generation.example.yaml"
    raw = yaml.safe_load(template.read_text(encoding="utf-8"))
    schemas = {tool["name"]: tool["input_schema"] for tool in raw["tools"]}
    assert len(schemas) == 25
    assert {"comfy.register", "comfy.get"} <= set(schemas)
    assert not {"workflows.register", "workflows.verify"} & set(schemas)
    assert not any(name.startswith("workflows.v3.") for name in schemas)
    assert schemas["workflows.build"] == {
        "type": "object",
        "properties": {
            "template": {"title": "Template", "type": "string"},
            "parameters": {"additionalProperties": True, "title": "Parameters", "type": "object"},
            "definition_version": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Definition Version",
            },
            "definition_digest": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Definition Digest",
            },
            "require_ready": {"default": False, "title": "Require Ready", "type": "boolean"},
        },
        "required": ["template", "parameters"],
        "title": "build_workflowArguments",
    }
    assert schemas["assets.delete"] == {
        "properties": {"asset_id": {"title": "Asset Id", "type": "string"}},
        "required": ["asset_id"],
        "title": "delete_assetArguments",
        "type": "object",
    }
    assert schemas["assets.prepare"] == {
        "properties": {"asset_id": {"title": "Asset Id", "type": "string"}},
        "required": ["asset_id"],
        "title": "prepare_assetArguments",
        "type": "object",
    }
    assert schemas["assets.read"] == {
        "properties": {
            "asset_id": {"title": "Asset Id", "type": "string"},
            "sha256": {"title": "Sha256", "type": "string"},
            "offset": {"title": "Offset", "type": "integer"},
            "length": {"default": 262144, "title": "Length", "type": "integer"},
        },
        "required": ["asset_id", "sha256", "offset"],
        "title": "read_assetArguments",
        "type": "object",
    }
    assert schemas["inputs.create"] == {
        "properties": {"asset_id": {"title": "Asset Id", "type": "string"}},
        "required": ["asset_id"],
        "title": "create_inputArguments",
        "type": "object",
    }
    for name, title in (
        ("inputs.get", "get_inputArguments"),
        ("inputs.delete", "delete_inputArguments"),
    ):
        assert schemas[name] == {
            "properties": {"input_id": {"title": "Input Id", "type": "string"}},
            "required": ["input_id"],
            "title": title,
            "type": "object",
        }
    assert not list(tmp_path.iterdir())
    assert load_upstreams(template.parent) == []
    (tmp_path / "generation.yaml").write_text(template.read_text(encoding="utf-8"))
    catalog = Catalog(load_upstreams(tmp_path))
    assert "generation.workflows.register" not in catalog.tools
    assert "generation.workflows.build" in catalog.tools
    assert "generation.comfy.register" in catalog.tools
    assert "generation.comfy.get" in catalog.tools
    assert "generation.assets.delete" in catalog.tools
    assert "generation.assets.prepare" in catalog.tools
    assert "generation.assets.read" in catalog.tools
    assert {"generation.inputs.create", "generation.inputs.get", "generation.inputs.delete"} <= set(
        catalog.tools
    )
    assert catalog.configs["generation"].headers() == {}
    # An unrelated stale variable must not cause fabricated upstream credentials.
    monkeypatch.setenv("GENERATION_MCP_API_KEY", "unused")
    assert catalog.configs["generation"].headers() == {}


def test_loads_catalog_without_secret_or_network(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TEST_MCP_KEY", raising=False)
    (tmp_path / "test.yaml").write_text(
        """
id: test
namespace: test
enabled: true
transport: streamable-http
url: https://example.com/mcp
api_key_env: TEST_MCP_KEY
tools:
  - name: items.get
    description: Get one item.
    input_schema:
      type: object
      properties:
        item_id:
          type: string
      required: [item_id]
      additionalProperties: false
""".strip(),
        encoding="utf-8",
    )

    configs = load_upstreams(tmp_path)
    catalog = Catalog(configs)

    assert len(configs) == 1
    assert "test.items.get" in catalog.tools

    # Secret resolution is deliberately deferred until connection time.
    with pytest.raises(ValueError, match="TEST_MCP_KEY"):
        configs[0].headers()


def test_headers_read_secret_only_when_connection_needs_it(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TEST_MCP_KEY", "secret")
    (tmp_path / "test.yaml").write_text(
        """
id: test
namespace: test
enabled: true
transport: streamable-http
url: https://example.com/mcp
api_key_env: TEST_MCP_KEY
api_key_header: Authorization
api_key_prefix: "Bearer "
tools: []
""".strip(),
        encoding="utf-8",
    )

    config = load_upstreams(tmp_path)[0]

    assert config.headers() == {"Authorization": "Bearer secret"}


def test_disabled_config_is_ignored(tmp_path: Path):
    (tmp_path / "disabled.yaml").write_text(
        """
id: disabled
namespace: disabled
enabled: false
transport: streamable-http
url: https://example.com/mcp
tools: []
""".strip(),
        encoding="utf-8",
    )

    assert load_upstreams(tmp_path) == []


def test_duplicate_namespace_is_rejected(tmp_path: Path):
    for name in ("one", "two"):
        (tmp_path / f"{name}.yaml").write_text(
            f"""
id: {name}
namespace: same
enabled: true
transport: streamable-http
url: https://example.com/{name}
tools: []
""".strip(),
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="duplicate upstream namespace"):
        load_upstreams(tmp_path)


def test_duplicate_public_tool_name_is_rejected():
    from flamoris_mcp_hub.config import ToolConfig, UpstreamConfig

    tool = ToolConfig(name="system.health")
    one = UpstreamConfig(
        id="one",
        namespace="same",
        url="https://example.com/one",
        tools=[tool],
    )
    two = UpstreamConfig(
        id="two",
        namespace="same",
        url="https://example.com/two",
        tools=[tool],
    )

    with pytest.raises(ValueError, match="duplicate public tool name"):
        Catalog([one, two])
