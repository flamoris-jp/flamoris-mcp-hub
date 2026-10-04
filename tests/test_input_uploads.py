import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult
from test_upstream import FakeSession
from test_upstream import fake_transport as upstream_transport

from flamoris_mcp_hub.auth import ExternalIdentity
from flamoris_mcp_hub.config import Catalog, load_upstreams
from flamoris_mcp_hub.provenance import META_KEY
from flamoris_mcp_hub.upstream import UpstreamRegistry

fake_transport = upstream_transport
ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("profile", ["generation"])
async def test_uploaded_image_contract_and_opaque_forwarding(
    tmp_path, fake_transport, monkeypatch, profile
):
    (tmp_path / "generation.yaml").write_text(
        (ROOT / "config/mcps" / f"_{profile}.example.yaml").read_text()
    )
    catalog = Catalog(load_upstreams(tmp_path))
    exported = json.loads((ROOT / "tests/fixtures" / f"{profile}-tools.json").read_text())
    fake_transport["tools"] = [
        SimpleNamespace(
            name=t.name, input_schema=t.input_schema, annotations=t.annotations.to_mcp()
        )
        for t in catalog.configs["generation"].tools
    ]
    for name in ("begin", "write", "finish"):
        tool = exported["inputs.upload." + name]
        assert tool["annotations"] == {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    schema = exported["inputs.upload.write"]["input_schema"]["properties"]
    assert schema["data_base64"]["maxLength"] == 349528
    assert (
        exported["inputs.upload.begin"]["input_schema"]["properties"]["size_bytes"]["maximum"]
        == 8 * 1024**2
    )
    expected = CallToolResult(content=[], structured_content={"opaque": "receipt"})
    original = FakeSession.call_tool

    async def call(self, name, args):
        await original(self, name, args)
        return expected

    monkeypatch.setattr(FakeSession, "call_tool", call)
    data, key = b"private image fixture", "a" * 32
    digest = hashlib.sha256(data).hexdigest()
    calls = [
        (
            "inputs.upload.begin",
            dict(upload_id=key, mime_type="image/png", size_bytes=len(data), sha256=digest),
        ),
        (
            "inputs.upload.write",
            dict(
                upload_id=key,
                offset=0,
                data_base64=base64.b64encode(data).decode(),
                chunk_sha256=digest,
            ),
        ),
        ("inputs.upload.finish", dict(upload_id=key)),
    ]
    async with UpstreamRegistry(catalog).run() as hub:
        for name, args in calls:
            assert await hub.call_public_tool("generation." + name, args) is expected
    assert fake_transport["requests"] == calls


async def test_upload_schema_drift_blocks_before_private_bytes_forward(tmp_path, fake_transport):
    (tmp_path / "generation.yaml").write_text(
        (ROOT / "config/mcps/_generation.example.yaml").read_text()
    )
    catalog = Catalog(load_upstreams(tmp_path))
    exported = json.loads((ROOT / "tests/fixtures/generation-tools.json").read_text())
    exported["inputs.upload.write"]["input_schema"]["properties"]["data_base64"]["maxLength"] += 1
    fake_transport["tools"] = [
        SimpleNamespace(
            name=k,
            input_schema=v["input_schema"],
            annotations=next(
                t.annotations.to_mcp() for t in catalog.configs["generation"].tools if t.name == k
            ),
        )
        for k, v in exported.items()
    ]
    async with UpstreamRegistry(catalog).run() as hub:
        with pytest.raises(LookupError, match="catalog mismatch"):
            await hub.call_public_tool(
                "generation.inputs.upload.write", {"data_base64": "private payload"}
            )
    assert fake_transport["calls"] == 0


async def test_external_upload_chunk_fits_real_signed_hub_context(
    tmp_path, fake_transport, monkeypatch
):
    template = (ROOT / "config/mcps/_generation.example.yaml").read_text()
    (tmp_path / "generation.yaml").write_text(
        template + "\nexternal_provenance_secret_env: TEST_UPLOAD_SIGNING_SECRET\n"
    )
    monkeypatch.setenv(
        "TEST_UPLOAD_SIGNING_SECRET",
        "independent-test-upload-signing-secret-at-least-32-characters",
    )
    catalog = Catalog(load_upstreams(tmp_path))
    fake_transport["tools"] = [
        SimpleNamespace(
            name=t.name, input_schema=t.input_schema, annotations=t.annotations.to_mcp()
        )
        for t in catalog.configs["generation"].tools
    ]
    receipts = []
    expected = CallToolResult(
        content=[], structured_content={"upload_id": "a" * 32, "offset": 128 * 1024}
    )
    original = FakeSession.call_tool

    async def call(self, name, arguments, *, meta):
        await original(self, name, arguments)
        receipts.append(meta)
        return expected

    monkeypatch.setattr(FakeSession, "call_tool", call)
    data = b"x" * (128 * 1024)
    args = dict(
        upload_id="a" * 32,
        offset=0,
        data_base64=base64.b64encode(data).decode(),
        chunk_sha256=hashlib.sha256(data).hexdigest(),
    )
    async with UpstreamRegistry(catalog).run() as hub:
        assert (
            await hub.call_public_tool(
                "generation.inputs.upload.write",
                args,
                identity=ExternalIdentity("hub.example", "external-group"),
            )
            is expected
        )
    assert receipts[0][META_KEY]["subject"] == "external-group"
    assert len(receipts[0][META_KEY]["signature"]) == 64
    assert "data_base64" not in json.dumps(receipts[0])
    assert fake_transport["requests"] == [("inputs.upload.write", args)]
