from contextlib import asynccontextmanager
from types import SimpleNamespace

import anyio
import pytest
from mcp.types import CallToolResult, ImageContent

from flamoris_mcp_hub.config import Catalog, ToolConfig, UpstreamConfig
from flamoris_mcp_hub.upstream import UpstreamRegistry

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def registry():
    config = UpstreamConfig(
        id="sample",
        namespace="sample",
        url="https://example.invalid/mcp",
        tools=[ToolConfig(name="jobs.submit", input_schema=SCHEMA)],
    )
    return UpstreamRegistry(Catalog([config]))


class FakeSession:
    def __init__(self, state):
        self.state = state
        self.stale = False

    async def initialize(self):
        pass

    async def list_tools(self):
        if self.stale:
            raise ConnectionError("stale")
        if self.state.get("missing"):
            return SimpleNamespace(tools=[])
        return SimpleNamespace(
            tools=[
                SimpleNamespace(name="jobs.submit", input_schema=self.state.get("schema", SCHEMA))
            ]
        )

    async def call_tool(self, name, arguments):
        self.state["calls"] += 1
        if self.state.get("block_calls"):
            self.state["entered"].set()
            await self.state["release"].wait()
        if self.state.get("fail_call"):
            raise ConnectionError("ambiguous")
        return CallToolResult(
            content=[ImageContent(type="image", data="aGVsbG8=", mime_type="image/png")]
        )


@pytest.fixture
def fake_transport(monkeypatch):
    state = {"connections": 0, "calls": 0, "sessions": [], "closed": 0}

    @asynccontextmanager
    async def client(*, headers):
        owner = anyio.get_current_task().id
        try:
            yield object()
        finally:
            assert anyio.get_current_task().id == owner
            state["closed"] += 1

    @asynccontextmanager
    async def transport(*args, **kwargs):
        owner = anyio.get_current_task().id
        try:
            yield (object(), object())
        finally:
            assert anyio.get_current_task().id == owner

    @asynccontextmanager
    async def session_context():
        owner = anyio.get_current_task().id
        state["connections"] += 1
        session = FakeSession(state)
        state["sessions"].append(session)
        try:
            yield session
        finally:
            assert anyio.get_current_task().id == owner

    monkeypatch.setattr("flamoris_mcp_hub.upstream._http_client", client)
    monkeypatch.setattr("flamoris_mcp_hub.upstream.streamable_http_client", transport)
    monkeypatch.setattr("flamoris_mcp_hub.upstream.ClientSession", lambda *args: session_context())
    return state


@pytest.mark.asyncio
async def test_lazy_reuse_stale_reconnect_and_non_text_forwarding(fake_transport):
    hub = registry()
    assert hub.status()[0]["connected"] is False
    async with hub.run():
        first = await hub.call_public_tool("sample.jobs.submit", {})
        assert isinstance(first.content[0], ImageContent)
        await hub.call_public_tool("sample.jobs.submit", {})
        assert fake_transport["connections"] == 1
        fake_transport["sessions"][0].stale = True
        await hub.call_public_tool("sample.jobs.submit", {})
        assert fake_transport["connections"] == 2
        assert fake_transport["calls"] == 3
    assert fake_transport["closed"] == 2


@pytest.mark.asyncio
async def test_catalog_mismatch_blocks_call_and_reports_diagnostics(fake_transport):
    fake_transport["schema"] = {"type": "object", "properties": {"new": {"type": "string"}}}
    hub = registry()
    async with hub.run():
        with pytest.raises(LookupError, match="catalog mismatch"):
            await hub.call_public_tool("sample.jobs.submit", {})
        assert hub.status()[0]["catalog_mismatch"]
    assert fake_transport["calls"] == 0


@pytest.mark.asyncio
async def test_missing_configured_tool_blocks_call(fake_transport):
    fake_transport["missing"] = True
    hub = registry()
    async with hub.run():
        with pytest.raises(LookupError, match="catalog mismatch"):
            await hub.call_public_tool("sample.jobs.submit", {})
    assert fake_transport["calls"] == 0


@pytest.mark.asyncio
async def test_ambiguous_call_never_replays(fake_transport):
    fake_transport["fail_call"] = True
    hub = registry()
    async with hub.run():
        with pytest.raises(ConnectionError, match="not retried"):
            await hub.call_public_tool("sample.jobs.submit", {})
        assert fake_transport["calls"] == 1


@pytest.mark.asyncio
async def test_unavailable_does_not_stop_other_upstreams(monkeypatch, fake_transport):
    from flamoris_mcp_hub import upstream

    original_transport = upstream.streamable_http_client

    @asynccontextmanager
    async def selective_transport(url, **kwargs):
        if "offline" in url:
            raise OSError("offline")
        async with original_transport(url, **kwargs) as streams:
            yield streams

    good = next(iter(registry().catalog.configs.values()))
    bad = UpstreamConfig(
        id="bad",
        namespace="bad",
        url="https://offline.invalid/mcp",
        tools=[ToolConfig(name="jobs.submit", input_schema=SCHEMA)],
    )
    hub = UpstreamRegistry(Catalog([good, bad]))
    monkeypatch.setattr("flamoris_mcp_hub.upstream.streamable_http_client", selective_transport)
    async with hub.run():
        with pytest.raises(ConnectionError, match="unavailable"):
            await hub.call_public_tool("bad.jobs.submit", {})
        result = await hub.call_public_tool("sample.jobs.submit", {})
        assert isinstance(result.content[0], ImageContent)


def test_sdk_http_timeouts(monkeypatch):
    from flamoris_mcp_hub.upstream import _http_client

    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    client = _http_client(headers={"Authorization": "example"})
    assert client.timeout.connect == 30
    assert client.timeout.read == 300
    assert client.timeout.write == 30
    assert client.timeout.pool == 30


@pytest.mark.asyncio
async def test_cancelled_queued_call_is_never_dispatched(fake_transport):
    fake_transport.update(block_calls=True, entered=anyio.Event(), release=anyio.Event())
    hub = registry()
    queued = anyio.Event()
    scopes = []

    async def first():
        await hub.call_public_tool("sample.jobs.submit", {})

    async def cancelled_second():
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            queued.set()
            await hub.call_public_tool("sample.jobs.submit", {})

    async with hub.run():
        async with anyio.create_task_group() as group:
            group.start_soon(first)
            await fake_transport["entered"].wait()
            group.start_soon(cancelled_second)
            await queued.wait()
            with anyio.fail_after(2):
                while hub._connections["sample"]._send.statistics().current_buffer_used == 0:
                    await anyio.sleep(0)
            scopes[0].cancel()
            await anyio.sleep(0)
            fake_transport["release"].set()
    assert fake_transport["calls"] == 1


@pytest.mark.asyncio
async def test_shutdown_discards_pending_calls(fake_transport):
    fake_transport.update(block_calls=True, entered=anyio.Event(), release=anyio.Event())
    hub = registry()
    errors = []

    async def call():
        try:
            await hub.call_public_tool("sample.jobs.submit", {})
        except RuntimeError as exc:
            errors.append(str(exc))

    async with anyio.create_task_group() as callers:
        async with hub.run():
            callers.start_soon(call)
            await fake_transport["entered"].wait()
            callers.start_soon(call)
            with anyio.fail_after(2):
                while hub._connections["sample"]._send.statistics().current_buffer_used == 0:
                    await anyio.sleep(0)
            await hub._connections["sample"].close()
            fake_transport["release"].set()
    assert fake_transport["calls"] == 1
    assert errors == ["upstream connection is shutting down"]
