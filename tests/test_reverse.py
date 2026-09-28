import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

from flamoris_mcp_hub.config import Catalog, ToolConfig, UpstreamConfig
from flamoris_mcp_hub.reverse import DesktopGateway, ReverseConnection
from flamoris_mcp_hub.upstream import UpstreamRegistry

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def config():
    return UpstreamConfig(
        id="cutwork",
        namespace="cutwork",
        transport="reverse-websocket",
        product_id="flamoris.cutwork",
        connector_token_env="CONNECTOR_TOKEN",
        tools=[
            ToolConfig(name="mcp.context", input_schema=SCHEMA),
            ToolConfig(name="edit", input_schema=SCHEMA),
        ],
    )


def registration(permission="edit"):
    names = ["mcp.context", "edit"] if permission == "edit" else ["mcp.context"]
    return {
        "type": "register",
        "version": 1,
        "productId": "flamoris.cutwork",
        "runtimeId": "runtime",
        "documentToken": "document",
        "permission": permission,
        "tools": [{"name": n, "inputSchema": SCHEMA} for n in names],
    }


class Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.closed = False

    async def accept(self):
        pass

    async def receive_text(self):
        item = await self.incoming.get()
        if isinstance(item, Exception):
            raise item
        return json.dumps(item)

    async def send_text(self, value):
        await self.outgoing.put(json.loads(value))

    async def send_json(self, value):
        await self.outgoing.put(value)

    async def close(self, code):
        self.closed = True
        await self.incoming.put(WebSocketDisconnect(code))


async def attach(connection, permission="edit"):
    socket = Socket()
    await socket.incoming.put(registration(permission))
    serving = asyncio.create_task(connection.serve(socket))
    assert await asyncio.wait_for(socket.outgoing.get(), 1) == {"type": "ready", "version": 1}
    return socket, serving


@pytest.mark.asyncio
async def test_offline_catalog_and_readonly_grant_then_reconnect():
    registry = UpstreamRegistry(Catalog([config()]))
    async with registry.run():
        connection = registry._connections["cutwork"]
        assert not registry.status()[0]["connected"]
        with pytest.raises(ConnectionError, match="offline"):
            await registry.call_public_tool("cutwork.mcp.context", {})
        socket, task = await attach(connection, "readOnly")
        assert registry.status()[0]["connected"]
        with pytest.raises(LookupError, match="permission"):
            await registry.call_public_tool("cutwork.edit", {})
        call = asyncio.create_task(registry.call_public_tool("cutwork.mcp.context", {}))
        request = await socket.outgoing.get()
        await socket.incoming.put(
            {
                "type": "result",
                "id": request["id"],
                "result": {
                    "content": [{"type": "text", "text": "current document"}],
                    "isError": False,
                },
            }
        )
        assert (await call).content[0].text == "current document"
        await socket.close(1000)
        await task
        assert not registry.status()[0]["connected"]
        socket, task = await attach(connection)
        await socket.close(1000)
        await task


@pytest.mark.asyncio
async def test_ambiguous_edit_disconnect_never_replays():
    connection = ReverseConnection(config())
    socket, task = await attach(connection)
    call = asyncio.create_task(connection.call_tool(None, "edit", {}))
    request = await socket.outgoing.get()
    assert request["name"] == "edit"
    with pytest.raises(ConnectionError, match="busy"):
        await connection.call_tool(None, "edit", {})
    await socket.close(1000)
    with pytest.raises(ConnectionError, match="not retried"):
        await call
    await task
    fresh, serving = await attach(connection)
    assert fresh.outgoing.empty()
    await fresh.close(1000)
    await serving


@pytest.mark.asyncio
async def test_cancellation_closes_connector_and_propagates():
    connection = ReverseConnection(config())
    socket, task = await attach(connection)
    call = asyncio.create_task(connection.call_tool(None, "edit", {}))
    await socket.outgoing.get()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    await task
    assert not connection.connected and socket.closed


@pytest.mark.asyncio
async def test_reject_duplicate_instance_and_wrong_catalog():
    connection = ReverseConnection(config())
    socket, task = await attach(connection)
    duplicate = Socket()
    await connection.serve(duplicate)
    assert duplicate.closed and connection.connected
    await socket.close(1000)
    await task
    bad = Socket()
    hello = registration()
    hello["tools"][0]["inputSchema"] = {"type": "object"}
    await bad.incoming.put(hello)
    await connection.serve(bad)
    assert bad.closed and not connection.connected and connection.catalog_mismatch


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers,accepted",
    [
        ([(b"host", b"hub.test"), (b"authorization", b"Bearer " + b"x" * 32)], True),
        ([(b"host", b"hub.test"), (b"authorization", b"Bearer wrong")], False),
        ([(b"host", b"evil.test"), (b"authorization", b"Bearer " + b"x" * 32)], False),
        (
            [
                (b"host", b"hub.test"),
                (b"authorization", b"Bearer " + b"x" * 32),
                (b"origin", b"https://hub.test"),
            ],
            False,
        ),
        (
            [
                (b"host", b"hub.test"),
                (b"authorization", b"Bearer " + b"x" * 32),
                (b"authorization", b"Bearer " + b"x" * 32),
            ],
            False,
        ),
    ],
)
async def test_connector_auth_binds_upstream_and_rejects_browser(monkeypatch, headers, accepted):
    monkeypatch.setenv("CONNECTOR_TOKEN", "x" * 32)
    connection = ReverseConnection(config())
    calls = []

    async def serve(socket):
        calls.append(socket)

    connection.serve = serve
    gateway = DesktopGateway(
        None, {"registry": SimpleNamespace(_connections={"cutwork": connection})}, ["hub.test"]
    )
    sent = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        sent.append(message)

    await gateway(
        {"type": "websocket", "path": "/desktop/cutwork", "headers": headers}, receive, send
    )
    assert bool(calls) is accepted
    if not accepted:
        assert sent[-1]["type"] == "websocket.close"
