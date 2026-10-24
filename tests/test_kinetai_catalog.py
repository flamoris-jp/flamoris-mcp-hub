"""Kinetic text remains an upstream command inside the guarded edit batch."""

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from flamoris_mcp_hub.config import Catalog, UpstreamConfig

ROOT = Path(__file__).resolve().parents[1]


def test_kinetic_command_is_pinned_in_both_existing_catalogs():
    producer = json.loads((ROOT / "tests/fixtures/kachinco-clip-tools.json").read_text())
    descriptor = producer[0]["inputSchema"]
    commands = descriptor["properties"]["input"]["properties"]["commands"]["items"]["oneOf"]
    command = next(c for c in commands if c["properties"]["type"]["const"] == "SetTextComposition")
    assert set(command["required"]) == {"type", "mediaAssetId", "textComposition"}
    assert command["additionalProperties"] is False
    assert command["properties"]["textComposition"]["type"] == "string"
    for name in ("_kachinco-clips.example.yaml", "_kachinco-titles.example.yaml"):
        config = UpstreamConfig.model_validate(
            yaml.safe_load((ROOT / "config/mcps" / name).read_text())
        )
        edit = next(t for t in config.tools if t.name == "edit_batch")
        assert edit.input_schema == descriptor
        assert config.product_id == "flamoris.kachinco"
        assert Catalog([config]).tools


def test_text_edit_retains_revision_guard_and_rejects_untyped_payload():
    descriptor = json.loads((ROOT / "tests/fixtures/kachinco-clip-tools.json").read_text())[0][
        "inputSchema"
    ]
    Draft202012Validator.check_schema(descriptor)
    assert set(descriptor["required"]) == {"input", "guard"}
    assert "expectedRevision" in descriptor["properties"]["guard"]["required"]
    commands = descriptor["properties"]["input"]["properties"]["commands"]["items"]["oneOf"]
    command = next(c for c in commands if c["properties"]["type"]["const"] == "SetTextComposition")
    validator = Draft202012Validator(command)
    assert list(validator.iter_errors({"type": "SetTextComposition", "mediaAssetId": "test"}))
    assert list(
        validator.iter_errors(
            {
                "type": "SetTextComposition",
                "mediaAssetId": "test",
                "textComposition": {},
                "path": "evil",
            }
        )
    )
