"""Native Music stays on the existing opaque Generation tool contracts."""

import base64
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.types import CallToolRequestParams, CallToolResult, TextContent
from test_upstream import FakeSession
from test_upstream import fake_transport as upstream_transport

from flamoris_mcp_hub.config import Catalog, load_upstreams
from flamoris_mcp_hub.server import on_call_tool
from flamoris_mcp_hub.upstream import UpstreamRegistry

fake_transport = upstream_transport
ROOT = Path(__file__).parents[1]
JOB_ID = "a" * 32


def generation_catalog(tmp_path, state):
    (tmp_path / "generation.yaml").write_text(
        (ROOT / "config/mcps/_generation.example.yaml").read_text()
    )
    catalog = Catalog(load_upstreams(tmp_path))
    state["tools"] = [
        SimpleNamespace(name=tool.name, input_schema=tool.input_schema)
        for tool in catalog.configs["generation"].tools
    ]
    return catalog


@pytest.mark.parametrize(
    "template,parameters",
    [
        (
            "music-generate",
            {
                "style": "instrumental",
                "lyrics": "",
                "seconds": 8,
                "steps": 4,
                "seed": 20261003,
                "lm_seed": 20261003,
            },
        ),
        ("music-transcribe", {"audio": "b" * 32, "max_seconds": 30, "melody_only": False}),
    ],
)
async def test_native_music_parameters_and_multiasset_results_cross_server_boundary(
    tmp_path, fake_transport, monkeypatch, template, parameters
):
    catalog = generation_catalog(tmp_path, fake_transport)
    assets = [
        {
            "asset_id": f"{JOB_ID}:{index:03d}",
            "job_id": JOB_ID,
            "output_index": index,
            "filename": filename,
            "media_kind": kind,
            "mime_type": mime,
        }
        for index, (filename, kind, mime) in enumerate(
            (
                ("score.mid", "midi", "audio/midi"),
                ("score.abc", "score", "text/vnd.abc"),
                ("annotations.json", "metadata", "application/json"),
                ("music.wav", "audio", "audio/wav"),
            )
        )
    ]
    result = CallToolResult(
        content=[],
        structured_content={
            "job_id": JOB_ID,
            "status": "completed",
            "assets": assets,
            "abc_error": "optional score unavailable",
        },
    )
    original = FakeSession.call_tool

    async def upstream_result(self, name, arguments):
        await original(self, name, arguments)
        return result

    monkeypatch.setattr(FakeSession, "call_tool", upstream_result)
    calls = [
        ("workflows.build", {"template": template, "parameters": parameters}),
        ("jobs.submit", {"workflow_id": "opaque-built-workflow"}),
        ("jobs.status", {"job_id": JOB_ID}),
        ("jobs.result", {"job_id": JOB_ID}),
    ]
    hub = UpstreamRegistry(catalog)
    ctx = SimpleNamespace(lifespan_context=hub)
    assert fake_transport["connections"] == 0
    async with hub.run():
        for name, arguments in calls:
            received = await on_call_tool(
                ctx, CallToolRequestParams(name="generation." + name, arguments=arguments)
            )
            assert received is result
    assert fake_transport["requests"] == calls
    assert fake_transport["connections"] == 1


@pytest.mark.parametrize(
    "kind,mime,prefix",
    [
        ("audio", "audio/wav", b"RIFF"),
        ("audio", "audio/mpeg", b"ID3"),
        ("midi", "audio/midi", b"MThd"),
        ("score", "text/vnd.abc", b"X:1\nK:C\n"),
        ("metadata", "application/json", b'{"annotations":'),
    ],
)
async def test_bounded_music_asset_metadata_bytes_and_digests_are_forwarded_unchanged(
    tmp_path, fake_transport, monkeypatch, kind, mime, prefix
):
    catalog = generation_catalog(tmp_path, fake_transport)
    payload = prefix + b"music fixture" * 25000
    digest = hashlib.sha256(payload).hexdigest()
    asset_id = f"{JOB_ID}:000"
    chunk_bytes = 256 * 1024
    prepared = {
        "asset_id": asset_id,
        "media_kind": kind,
        "mime_type": mime,
        "materialized": True,
        "size_bytes": len(payload),
        "sha256": digest,
        "chunk_bytes": chunk_bytes,
        "transfer_version": 1,
    }
    original = FakeSession.call_tool
    responses = []

    async def upstream_result(self, name, arguments):
        await original(self, name, arguments)
        if name == "assets.prepare":
            data = prepared
        else:
            assert name == "assets.read"
            assert arguments["sha256"] == digest
            offset = arguments["offset"]
            chunk = payload[offset : offset + arguments["length"]]
            data = {
                "asset_id": asset_id,
                "sha256": digest,
                "offset": offset,
                "size_bytes": len(payload),
                "data_base64": base64.b64encode(chunk).decode(),
                "chunk_sha256": hashlib.sha256(chunk).hexdigest(),
                "next_offset": offset + len(chunk),
                "eof": offset + len(chunk) == len(payload),
            }
        response = CallToolResult(content=[], structured_content=data)
        responses.append(response)
        return response

    monkeypatch.setattr(FakeSession, "call_tool", upstream_result)
    hub = UpstreamRegistry(catalog)
    ctx = SimpleNamespace(lifespan_context=hub)
    calls = [("assets.prepare", {"asset_id": asset_id})]
    received = bytearray()
    async with hub.run():
        manifest = await on_call_tool(
            ctx,
            CallToolRequestParams(name="generation.assets.prepare", arguments=calls[0][1]),
        )
        assert manifest is responses[-1]
        assert manifest.structured_content == prepared
        offset = 0
        while offset < len(payload):
            arguments = {
                "asset_id": asset_id,
                "sha256": digest,
                "offset": offset,
                "length": chunk_bytes,
            }
            calls.append(("assets.read", arguments))
            result = await on_call_tool(
                ctx,
                CallToolRequestParams(name="generation.assets.read", arguments=arguments),
            )
            assert result is responses[-1]
            data = result.structured_content
            chunk = base64.b64decode(data["data_base64"], validate=True)
            assert hashlib.sha256(chunk).hexdigest() == data["chunk_sha256"]
            received.extend(chunk)
            offset = data["next_offset"]
            assert data["eof"] == (offset == len(payload))
    assert bytes(received) == payload
    assert hashlib.sha256(received).hexdigest() == digest
    assert fake_transport["requests"] == calls
    assert fake_transport["calls"] == 3


async def test_native_music_ambiguous_submission_is_not_replayed(tmp_path, fake_transport):
    catalog = generation_catalog(tmp_path, fake_transport)
    fake_transport["fail_call"] = True
    hub = UpstreamRegistry(catalog)
    ctx = SimpleNamespace(lifespan_context=hub)
    args = {"workflow_id": "opaque-native-music-workflow"}
    async with hub.run():
        result = await on_call_tool(
            ctx, CallToolRequestParams(name="generation.jobs.submit", arguments=args)
        )
        assert result.is_error
        assert isinstance(result.content[0], TextContent)
        assert "not retried" in result.content[0].text
    assert fake_transport["requests"] == [("jobs.submit", args)]
