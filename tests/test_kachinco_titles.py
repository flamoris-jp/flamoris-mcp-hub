"""Producer-pinned title capture/export and unchanged reverse routing."""

import asyncio
import base64
import json
from pathlib import Path

import pytest
import yaml

from flamoris_mcp_hub.config import Catalog, UpstreamConfig
from flamoris_mcp_hub.reverse import ReverseConnection
from test_reverse import Socket

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests/fixtures/kachinco-title-tools.json").read_text())


def config():
    return UpstreamConfig.model_validate(
        yaml.safe_load((ROOT / "config/mcps/_kachinco-titles.example.yaml").read_text())
    )


def registration(permission="readOnly"):
    tools = config().tools
    if permission == "readOnly":
        tools = [
            t for t in tools if t.name not in ("edit_batch", "title_image_from_frame")
        ]
    return {
        "type": "register",
        "version": 1,
        "productId": "flamoris.kachinco",
        "runtimeId": "runtime",
        "documentToken": "document",
        "permission": permission,
        "tools": [{"name": t.name, "inputSchema": t.input_schema} for t in tools],
    }


def test_creation_catalog_matches_pinned_producer_and_clip_edit_schema():
    current = config()
    assert [
        {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
        for t in current.tools
        if t.name.startswith("title_image")
    ] == FIXTURE
    assert len(Catalog([current]).tools) == 4
    clip = json.loads((ROOT / "tests/fixtures/kachinco-clip-tools.json").read_text())
    assert current.tools[1].input_schema == clip[0]["inputSchema"]
    inputs = current.tools[1].input_schema["properties"]["input"]["properties"]
    commands = inputs["commands"]["items"]["oneOf"]
    names = {c["properties"]["type"]["const"] for c in commands}
    expected = {
        "UnregisterMedia",
        "SetTitleImage",
        "ReserveTitleFrame",
        "ReleaseTitleFrame",
        "ApplyCrossfade",
    }
    assert expected <= names
    assert FIXTURE[0]["inputSchema"]["required"] == ["input", "guard"]
    guard = FIXTURE[0]["inputSchema"]["properties"]["guard"]
    assert "expectedRevision" in guard["required"]


async def test_readonly_export_forwards_image_and_rejects_capture():
    connection = ReverseConnection(config())
    socket = Socket()
    await socket.incoming.put(registration())
    serving = asyncio.create_task(connection.serve(socket))
    assert (await socket.outgoing.get())["type"] == "ready"
    try:
        with pytest.raises(LookupError, match="permission"):
            await connection.call_tool(None, "title_image_from_frame", {})
        assert socket.outgoing.empty()
        args = {"input": {"sequenceId": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"}}
        pending = asyncio.create_task(connection.call_tool(None, "title_image", args))
        request = await socket.outgoing.get()
        assert request["name"] == "title_image" and request["arguments"] == args
        encoded = base64.b64encode(b"producer-owned-image").decode()
        result = {
            "content": [{"type": "image", "data": encoded, "mimeType": "image/jpeg"}],
            "isError": False,
        }
        await socket.incoming.put(
            {"type": "result", "id": request["id"], "result": result}
        )
        reply = await pending
        assert not reply.is_error
        assert reply.content[0].data == encoded
        assert reply.content[0].mimeType == "image/jpeg"
    finally:
        await socket.close(1000)
        await serving
