import copy
import json
import logging
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx2
import pytest
from mcp.types import Tool, ToolAnnotations

from flamoris_mcp_hub import catalog_check
from flamoris_mcp_hub.config import ToolConfig, UpstreamConfig

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def configured():
    return UpstreamConfig(
        id="generation",
        namespace="generation",
        url="https://upstream.invalid/mcp",
        tools=[
            ToolConfig(
                name="workflows.verify",
                input_schema=SCHEMA,
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "openWorldHint": False,
                },
            )
        ],
    )


def listed(prefix=""):
    config = configured()
    return SimpleNamespace(
        tools=[
            Tool(
                name=prefix + tool.name,
                input_schema=tool.input_schema,
                annotations=tool.annotations.to_mcp(),
            )
            for tool in config.tools
        ],
        next_cursor=None,
    )


async def test_pair_receipt_checks_fresh_upstream_and_running_hub(monkeypatch):
    calls = []

    async def discover(url, headers):
        calls.append((url, headers))
        result = listed("generation." if "hub.invalid" in url else "")
        if "hub.invalid" in url:
            result.tools.append(Tool(name="unrelated.read", input_schema=SCHEMA))
        return result

    monkeypatch.setattr(catalog_check, "_list_tools", discover)
    receipt = await catalog_check.check_pair(configured(), "https://hub.invalid/mcp", "a" * 32)
    assert receipt["status"] == "matched"
    assert all(
        check["contract_digest"] == receipt["expected_contract_digest"]
        for check in receipt["checks"].values()
    )
    assert calls == [
        ("https://upstream.invalid/mcp", {}),
        ("https://hub.invalid/mcp", {"Authorization": "Bearer " + "a" * 32}),
    ]
    serialized = json.dumps(receipt)
    assert "https://" not in serialized and "a" * 32 not in serialized


@pytest.mark.parametrize("change", ["schema", "annotations", "missing", "additional"])
async def test_receipt_rejects_drift_on_running_hub(monkeypatch, change):
    hub = listed("generation.")
    if change == "schema":
        hub.tools[0].input_schema = {"type": "object"}
    elif change == "annotations":
        hub.tools[0].annotations = ToolAnnotations(read_only_hint=True)
    elif change == "missing":
        hub.tools = []
    else:
        hub.tools.append(Tool(name="generation.extra", input_schema=SCHEMA))

    async def discover(url, headers):
        return hub if "hub.invalid" in url else listed()

    monkeypatch.setattr(catalog_check, "_list_tools", discover)
    receipt = await catalog_check.check_pair(configured(), "https://hub.invalid/mcp", "a" * 32)
    assert receipt["status"] == "mismatch"
    assert receipt["checks"]["upstream"]["status"] == "matched"
    assert receipt["checks"]["hub"]["status"] == "mismatch"


@pytest.mark.parametrize("change", ["duplicate", "partial", "too_many", "invalid_name", "oversize"])
def test_ambiguous_or_unbounded_discovery_is_not_evidence(change):
    result = listed()
    if change == "duplicate":
        result.tools += copy.deepcopy(result.tools)
    elif change == "partial":
        result.next_cursor = "another-page"
    elif change == "too_many":
        result.tools *= catalog_check.MAX_TOOLS + 1
    elif change == "invalid_name":
        result.tools[0].name = "private payload\n"
    else:
        result.tools[0].input_schema["description"] = "x" * catalog_check.MAX_CONTRACT_BYTES
    with pytest.raises(ValueError):
        catalog_check._contract(result)


async def test_discovery_uses_one_fresh_session_and_never_calls_tools(monkeypatch):
    events = []

    @asynccontextmanager
    async def http_client(**kwargs):
        events.append("client")
        yield object()

    @asynccontextmanager
    async def transport(*args, **kwargs):
        assert kwargs["max_sse_event_size"] == catalog_check.MAX_CONTRACT_BYTES
        events.append("transport")
        yield (object(), object())

    class Session:
        async def initialize(self):
            events.append("initialize")

        async def list_tools(self):
            events.append("tools/list")
            return listed()

        async def call_tool(self, *args, **kwargs):
            pytest.fail("acceptance checker must never invoke a domain tool")

    @asynccontextmanager
    async def session(*args):
        events.append("session")
        yield Session()
        events.append("closed")

    monkeypatch.setattr(catalog_check, "_http_client", http_client)
    monkeypatch.setattr(catalog_check, "streamable_http_client", transport)
    monkeypatch.setattr(catalog_check, "ClientSession", session)
    await catalog_check._list_tools("https://example.invalid/mcp", {})
    await catalog_check._list_tools("https://example.invalid/mcp", {})
    assert events == ["client", "transport", "session", "initialize", "tools/list", "closed"] * 2


def test_cli_error_receipt_never_echoes_sensitive_exception(tmp_path, monkeypatch, capsys):
    catalog = tmp_path / "runtime.yaml"
    catalog.write_text("url: https://private.invalid/?secret=secret-value")
    monkeypatch.setenv("FLAMORIS_MCP_HUB_CLIENT_TOKEN", "a" * 32)
    monkeypatch.setattr(
        sys, "argv", ["catalog-check", str(catalog), "--hub-url", "https://hub.invalid/mcp"]
    )
    assert catalog_check.main() == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "schema_version": 1,
        "status": "error",
        "error": "catalog_check_failed",
    }
    assert not output.err and "secret-value" not in output.out


def test_cli_has_total_deadline(tmp_path, monkeypatch, capsys):
    import anyio
    import yaml

    catalog = tmp_path / "runtime.yaml"
    catalog.write_text(yaml.safe_dump(configured().model_dump(mode="json")))
    monkeypatch.setenv("FLAMORIS_MCP_HUB_CLIENT_TOKEN", "a" * 32)
    monkeypatch.setattr(
        sys,
        "argv",
        ["catalog-check", str(catalog), "--hub-url", "https://hub.invalid/mcp", "--timeout", "1"],
    )

    async def blocked(*args, **kwargs):
        await anyio.sleep_forever()

    monkeypatch.setattr(catalog_check, "_list_tools", blocked)
    assert catalog_check.main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"


class Chunks(httpx2.AsyncByteStream):
    def __init__(self, data):
        self.data = data
        self.read = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.data:
            self.read += 1
            yield chunk

    async def aclose(self):
        self.closed = True


async def test_json_body_limit_is_enforced_during_network_read():
    source = Chunks([b"x" * (catalog_check.MAX_CONTRACT_BYTES // 2)] * 10)
    response = httpx2.Response(200, stream=source)
    await catalog_check._bound_response(response)
    try:
        with pytest.raises(ValueError, match="response too large"):
            await response.aread()
    finally:
        await response.aclose()
    assert source.read == 3 and source.closed


async def test_compressed_body_is_rejected_before_read_or_decompression():
    source = Chunks([b"untrusted compressed bytes"])
    response = httpx2.Response(200, headers={"Content-Encoding": "gzip"}, stream=source)
    with pytest.raises(ValueError, match="compressed response"):
        await catalog_check._bound_response(response)
    assert source.read == 0 and source.closed


def test_sdk_malformed_response_cannot_leak_payload_or_url(tmp_path, monkeypatch, capsys, caplog):
    import yaml

    catalog = tmp_path / "runtime.yaml"
    catalog.write_text(yaml.safe_dump(configured().model_dump(mode="json")))
    monkeypatch.setenv("FLAMORIS_MCP_HUB_CLIENT_TOKEN", "a" * 32)
    monkeypatch.setattr(
        sys,
        "argv",
        ["catalog-check", str(catalog), "--hub-url", "https://hub.invalid/mcp", "--timeout", "1"],
    )

    def broken(request):
        return httpx2.Response(
            200,
            json={"jsonrpc": "PRIVATE-SECRET-RESPONSE", "id": 0, "result": {}},
        )

    def client(**kwargs):
        return httpx2.AsyncClient(
            transport=httpx2.MockTransport(broken),
            event_hooks={"response": [catalog_check._bound_response]},
            headers={"Accept-Encoding": "identity"},
        )

    monkeypatch.setattr(catalog_check, "_http_client", client)
    previous_disable = logging.root.manager.disable
    with caplog.at_level(logging.DEBUG):
        assert catalog_check.main() == 1
    assert logging.root.manager.disable == previous_disable
    output = capsys.readouterr()
    assert not output.err and not caplog.records
    assert "PRIVATE-SECRET-RESPONSE" not in output.out
    assert "https://" not in output.out
    assert json.loads(output.out)["status"] == "error"
