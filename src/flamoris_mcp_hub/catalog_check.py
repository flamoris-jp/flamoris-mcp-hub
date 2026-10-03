"""Explicit, read-only fresh-connection acceptance check for a deployed route."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import httpx2
import yaml
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import HttpUrl, TypeAdapter

from .auth import _token
from .config import UpstreamConfig
from .upstream import _tool_annotations

MAX_CONTRACT_BYTES = 1024 * 1024
MAX_TOOLS = 512
TOOL_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class _BoundedStream(httpx2.AsyncByteStream):
    def __init__(self, stream: httpx2.AsyncByteStream) -> None:
        self.stream = stream

    async def __aiter__(self):
        size = 0
        async for chunk in self.stream:
            size += len(chunk)
            if size > MAX_CONTRACT_BYTES:
                raise ValueError("response too large")
            yield chunk

    async def aclose(self) -> None:
        await self.stream.aclose()


async def _bound_response(response: httpx2.Response) -> None:
    # Reject compression instead of allowing decompression to allocate an
    # unbounded decoded chunk before the JSON/SSE parser can enforce its limit.
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        await response.aclose()
        raise ValueError("compressed response is unsupported")
    if response.is_stream_consumed:
        if len(response.content) > MAX_CONTRACT_BYTES:
            raise ValueError("response too large")
    else:
        response.stream = _BoundedStream(response.stream)


def _http_client(*, headers: dict[str, str]) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        headers={**headers, "Accept-Encoding": "identity"},
        timeout=httpx2.Timeout(30.0, read=300.0),
        event_hooks={"response": [_bound_response]},
        trust_env=False,
    )


def _digest(contract: dict[str, Any]) -> str:
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_CONTRACT_BYTES:
        raise ValueError("contract too large")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _contract(listed: Any, namespace: str | None = None) -> dict[str, Any]:
    # Partial/duplicate discovery must never become evidence of compatibility.
    if getattr(listed, "next_cursor", None) is not None or len(listed.tools) > MAX_TOOLS:
        raise ValueError("invalid tools/list")
    all_names: set[str] = set()
    contract = {}
    prefix = namespace + "." if namespace is not None else ""
    for tool in listed.tools:
        if not TOOL_NAME.fullmatch(tool.name) or tool.name in all_names:
            raise ValueError("invalid tools/list")
        all_names.add(tool.name)
        if not tool.name.startswith(prefix):
            continue
        contract[tool.name[len(prefix) :]] = {
            "input_schema": tool.input_schema,
            "annotations": _tool_annotations(tool),
        }
    _digest(contract)
    return contract


def _comparison(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    changed = sorted(
        name for name in expected.keys() & actual.keys() if expected[name] != actual[name]
    )
    missing = sorted(expected.keys() - actual.keys())
    additional = sorted(actual.keys() - expected.keys())
    return {
        "status": "mismatch" if changed or missing or additional else "matched",
        "tool_count": len(actual),
        "contract_digest": _digest(actual),
        "changed_tools": changed,
        "missing_tools": missing,
        "additional_tools": additional,
    }


async def _list_tools(url: str, headers: dict[str, str]) -> Any:
    # New client/session per endpoint, with no cached Hub/upstream connection.
    async with _http_client(headers=headers) as client:
        async with streamable_http_client(
            url, http_client=client, max_sse_event_size=MAX_CONTRACT_BYTES
        ) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                return await session.list_tools()


async def check_pair(config: UpstreamConfig, hub_url: str, hub_token: str) -> dict[str, Any]:
    if not config.enabled or config.transport != "streamable-http" or not config.tools:
        raise ValueError("an enabled HTTP route is required")
    if len(config.tools) > MAX_TOOLS:
        raise ValueError("contract too large")
    expected = {
        tool.name: {
            "input_schema": tool.input_schema,
            "annotations": tool.annotations.to_mcp().model_dump(by_alias=True, exclude_none=True),
        }
        for tool in config.tools
    }
    expected_digest = _digest(expected)
    upstream = _contract(await _list_tools(str(config.url), config.headers()))
    hub = _contract(
        await _list_tools(hub_url, {"Authorization": "Bearer " + hub_token}), config.namespace
    )
    checks = {"upstream": _comparison(expected, upstream), "hub": _comparison(expected, hub)}
    return {
        "schema_version": 1,
        "checked_at": datetime.now(UTC).isoformat(),
        "status": "matched"
        if all(c["status"] == "matched" for c in checks.values())
        else "mismatch",
        "scope": "fresh_connection_catalog_parity",
        "namespace": config.namespace,
        "expected_tool_count": len(expected),
        "expected_contract_digest": expected_digest,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "catalog", type=Path, help="Deployment-local runtime YAML for one HTTP route"
    )
    parser.add_argument("--hub-url", required=True, help="Deployed Hub MCP endpoint")
    parser.add_argument("--hub-token-env", default="FLAMORIS_MCP_HUB_CLIENT_TOKEN")
    parser.add_argument("--env-file", type=Path, help="Optional deployment-local secrets file")
    parser.add_argument("--timeout", type=float, default=30, help="Total deadline, 1-300 seconds")
    args = parser.parse_args()

    async def run() -> dict[str, Any]:
        if args.env_file is not None:
            load_dotenv(args.env_file, override=False)
        token = _token(os.environ.get(args.hub_token_env, ""), "Hub token")
        if not 1 <= args.timeout <= 300:
            raise ValueError("invalid deadline")
        hub_url = str(TypeAdapter(HttpUrl).validate_python(args.hub_url))
        with args.catalog.open("rb") as source:
            raw = source.read(MAX_CONTRACT_BYTES + 1)
        if len(raw) > MAX_CONTRACT_BYTES:
            raise ValueError("catalog too large")
        config = UpstreamConfig.model_validate(yaml.safe_load(raw))
        with anyio.fail_after(args.timeout):
            return await check_pair(config, hub_url, token)

    # This standalone command must not let SDK exception/debug logging echo
    # malformed response payloads, credentials or deployment URLs on stderr.
    # Importing this module and the normal Hub server do not change logging.
    previous_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        try:
            receipt = anyio.run(run)
        except Exception:
            receipt = {"schema_version": 1, "status": "error", "error": "catalog_check_failed"}
    finally:
        logging.disable(previous_disable)
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "matched" else 1


if __name__ == "__main__":
    raise SystemExit(main())
