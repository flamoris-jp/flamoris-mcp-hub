import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx2
import pytest
from mcp.types import CallToolRequestParams, CallToolResult
from starlette.responses import Response

from flamoris_mcp_hub.auth import (
    CLIENTS_FILE_ENV,
    IDENTITY_SCOPE_KEY,
    TOKEN_ENV,
    BearerAuth,
    ExternalIdentity,
    configured_clients,
)
from flamoris_mcp_hub.config import Catalog, ToolConfig, UpstreamConfig
from flamoris_mcp_hub.provenance import META_KEY, ProvenanceSigner
from flamoris_mcp_hub.server import create_app, on_call_tool
from flamoris_mcp_hub.upstream import UpstreamRegistry

TOKEN = "anonymous-credential-that-is-at-least-32-characters"
CLIENT_A = "client-a-credential-that-is-at-least-32-characters"
CLIENT_B = "client-b-credential-that-is-at-least-32-characters"
SECRET = "independent-downstream-signing-secret-at-least-32-characters"
A = ExternalIdentity("hub.example", "opaque-a")
B = ExternalIdentity("hub.example", "opaque-b")


def test_configured_clients_are_explicit_and_secret_free_errors(monkeypatch, tmp_path):
    path = tmp_path / "clients.json"
    monkeypatch.setenv(CLIENTS_FILE_ENV, str(path))
    monkeypatch.setenv("CLIENT_A", CLIENT_A)
    monkeypatch.setenv("CLIENT_B", CLIENT_B)
    raw = {
        "issuer": A.issuer,
        "clients": [
            {"subject": A.subject, "token_env": "CLIENT_A"},
            {"subject": B.subject, "token_env": "CLIENT_B"},
        ],
    }
    path.write_text(json.dumps(raw))
    assert configured_clients() == [(CLIENT_A, A), (CLIENT_B, B)]
    monkeypatch.setenv("CLIENT_B", CLIENT_A)
    with pytest.raises(ValueError) as error:
        configured_clients()
    assert CLIENT_A not in str(error.value)
    assert str(path) not in str(error.value)
    monkeypatch.setenv("CLIENT_B", CLIENT_B)
    raw["clients"][1]["subject"] = A.subject
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        configured_clients()


@pytest.mark.parametrize(
    "raw",
    [
        {"issuer": "hub", "clients": []},
        {"issuer": "bad issuer", "clients": [{"subject": "a", "token_env": "CLIENT_A"}]},
        {"issuer": "hub", "clients": [{"subject": "a", "token": CLIENT_A}]},
        {"issuer": "hub", "clients": [{"subject": "a", "token_env": "CLIENT_A"}] * 65},
        {"issuer": "hub", "clients": [{"subject": "../a", "token_env": "CLIENT_A"}]},
    ],
)
def test_invalid_client_configuration_fails_closed(monkeypatch, tmp_path, raw):
    path = tmp_path / "clients.json"
    path.write_text(json.dumps(raw))
    monkeypatch.setenv(CLIENTS_FILE_ENV, str(path))
    monkeypatch.setenv("CLIENT_A", CLIENT_A)
    with pytest.raises(ValueError, match=CLIENTS_FILE_ENV):
        configured_clients()


async def test_identity_and_session_binding_survive_reconnect_and_reject_takeover(monkeypatch):
    identities = []
    next_session = 0

    async def downstream(scope, receive, send):
        nonlocal next_session
        identities.append(scope[IDENTITY_SCOPE_KEY])
        next_session += 1
        await Response(status_code=204, headers={"Mcp-Session-Id": str(next_session)})(
            scope, receive, send
        )

    wrapped = BearerAuth(downstream, TOKEN, [(CLIENT_A, A), (CLIENT_B, B)])
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=wrapped), base_url="http://localhost"
    ) as client:
        first = await client.post("/mcp", headers={"Authorization": "Bearer " + CLIENT_A})
        session = first.headers["mcp-session-id"]
        assert (
            await client.post(
                "/mcp", headers={"Authorization": "Bearer " + CLIENT_B, "Mcp-Session-Id": session}
            )
        ).status_code == 403
        assert (
            await client.post(
                "/mcp",
                headers={
                    "Authorization": "Bearer " + CLIENT_A,
                    "Mcp-Session-Id": session,
                    "X-Flamoris-Provenance-Subject": "forged",
                },
            )
        ).status_code == 204
        await client.post("/mcp", headers={"Authorization": "Bearer " + CLIENT_A})
        await client.post("/mcp", headers={"Authorization": "Bearer " + CLIENT_B})
        await client.post("/mcp", headers={"Authorization": "Bearer " + TOKEN})
    assert identities == [A, A, A, B, None]
    # Recreating the boundary with the same credential config preserves stable identity.
    wrapped_again = BearerAuth(downstream, TOKEN, [(CLIENT_A, A), (CLIENT_B, B)])
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=wrapped_again), base_url="http://localhost"
    ) as client:
        await client.post("/mcp", headers={"Authorization": "Bearer " + CLIENT_A})
    assert identities[-1] == A


async def test_session_capacity_does_not_evict_a_known_binding(monkeypatch):
    monkeypatch.setattr("flamoris_mcp_hub.auth.MAX_SESSIONS", 1)
    calls = 0

    async def downstream(scope, receive, send):
        nonlocal calls
        calls += 1
        await Response(status_code=204, headers={"Mcp-Session-Id": "known"})(scope, receive, send)

    wrapped = BearerAuth(downstream, TOKEN, [(CLIENT_A, A), (CLIENT_B, B)])
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=wrapped), base_url="http://localhost"
    ) as client:
        assert (
            await client.post("/mcp", headers={"Authorization": "Bearer " + CLIENT_A})
        ).status_code == 204
        assert (
            await client.post("/mcp", headers={"Authorization": "Bearer " + CLIENT_B})
        ).status_code == 503
        assert (
            await client.post(
                "/mcp", headers={"Authorization": "Bearer " + CLIENT_A, "Mcp-Session-Id": "known"}
            )
        ).status_code == 204
    assert calls == 2


def test_signature_is_bound_to_raw_tool_arguments_and_new_nonce(monkeypatch):
    monkeypatch.setenv("SIGNING_KEY", SECRET)
    signer = ProvenanceSigner("SIGNING_KEY")
    arguments = {"parameters": {"prompt": "日本語", "seed": 2}, "template": "image"}
    meta = signer.metadata(A, "workflows.build", arguments)
    envelope = meta[META_KEY]
    signature = envelope.pop("signature")
    expected = hmac.new(
        SECRET.encode(),
        json.dumps(
            {**envelope, "tool": "workflows.build", "arguments": arguments},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert signature == expected
    assert signer.metadata(A, "workflows.build", arguments)[META_KEY]["nonce"] != envelope["nonce"]
    assert SECRET not in json.dumps(meta)
    assert CLIENT_A not in json.dumps(meta)
    with pytest.raises(ValueError, match="invalid provenance request"):
        signer.metadata(A, "tool", {"seed": float("nan")})


def test_shared_generation_canonical_signature_vector(monkeypatch):
    monkeypatch.setenv("SIGNING_KEY", "test-internal-signing-key-0000000000000000")
    monkeypatch.setattr("flamoris_mcp_hub.provenance.time.time", lambda: 2000000000)
    monkeypatch.setattr(
        "flamoris_mcp_hub.provenance.uuid.uuid4", lambda: SimpleNamespace(hex="0" * 32)
    )
    envelope = ProvenanceSigner("SIGNING_KEY").metadata(
        ExternalIdentity("configured-hub", "client-a"),
        "jobs.submit",
        {"workflow_id": "a" * 32},
    )[META_KEY]
    assert envelope["signature"] == (
        "470bfa0724cb50f32b226845940ce132711391ebab0fb5f7a29ec3a2d667b7e8"
    )


async def test_caller_metadata_and_headers_never_override_credential_identity(monkeypatch):
    config = UpstreamConfig(
        id="generation",
        namespace="generation",
        url="https://example.invalid/mcp",
        tools=[ToolConfig(name="jobs.submit")],
    )
    registry = UpstreamRegistry(Catalog([config]))
    captured = []

    async def call(name, arguments, *, identity=None):
        captured.append((name, arguments, identity))
        return CallToolResult(content=[])

    monkeypatch.setattr(registry, "call_public_tool", call)
    ctx = SimpleNamespace(
        lifespan_context=registry, request=SimpleNamespace(scope={IDENTITY_SCOPE_KEY: A})
    )
    params = CallToolRequestParams(
        name="generation.jobs.submit",
        arguments={},
        meta={META_KEY: {"issuer": B.issuer, "subject": B.subject}},
    )
    await on_call_tool(ctx, params)
    assert captured == [("generation.jobs.submit", {}, A)]


@pytest.mark.parametrize(
    "namespace,transport", [("agent", "streamable-http"), ("generation", "reverse-websocket")]
)
def test_unapproved_route_cannot_receive_provenance(namespace, transport):
    with pytest.raises(ValueError, match="restricted"):
        UpstreamConfig(
            id="sample",
            namespace=namespace,
            transport=transport,
            external_provenance_secret_env="SIGNING_KEY",
        )


async def test_signing_key_cannot_be_an_ingress_client_credential(monkeypatch, tmp_path):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    monkeypatch.delenv(CLIENTS_FILE_ENV, raising=False)
    monkeypatch.setenv("SIGNING_KEY", TOKEN)
    monkeypatch.setenv("FLAMORIS_MCP_HUB_ENV_FILE", str(tmp_path / "absent"))
    config = UpstreamConfig(
        id="generation",
        namespace="generation",
        url="https://example.invalid/mcp",
        external_provenance_secret_env="SIGNING_KEY",
    )
    catalog = Catalog([config])
    registry = UpstreamRegistry(catalog)
    monkeypatch.setattr("flamoris_mcp_hub.server.start_registry", lambda: (catalog, registry))
    app = create_app()
    with pytest.raises(ValueError, match="independent"):
        async with app.app.app.router.lifespan_context(app.app.app):
            raise AssertionError("unsafe configuration reached runtime")
