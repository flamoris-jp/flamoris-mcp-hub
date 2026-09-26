from pathlib import Path

import httpx2
import pytest
import yaml
from starlette.responses import Response

from flamoris_mcp_hub.auth import TOKEN_ENV, BearerAuth, client_token
from flamoris_mcp_hub.server import create_app

TOKEN = "a-test-token-that-is-at-least-32-characters"


@pytest.mark.parametrize("token", [None, "", "short", "x" * 513, "é" * 40, "x" * 32 + "\n"])
def test_invalid_token_fails_without_disclosing_it(monkeypatch, token):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    if token is not None:
        monkeypatch.setenv(TOKEN_ENV, token)
    with pytest.raises(ValueError, match=TOKEN_ENV) as error:
        client_token()
    if token:
        assert token not in str(error.value)


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE", "OPTIONS"])
@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("Authorization", "Bearer wrong")],
        [("Authorization", "Basic " + TOKEN)],
        [("Authorization", "Bearer " + TOKEN), ("Authorization", "Bearer " + TOKEN)],
        [("Authorization", "Bearer " + "x" * 2048)],
    ],
)
async def test_unauthorized_never_enters_mcp(method, headers):
    async def downstream(scope, receive, send):
        raise AssertionError("unauthorized request reached MCP")

    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=BearerAuth(downstream, TOKEN)),
        base_url="http://localhost",
    ) as client:
        result = await client.request(method, "/mcp?access_token=" + TOKEN, headers=headers)
        assert result.status_code == 401
        assert result.json() == {"error": "Unauthorized"}
        assert result.headers["www-authenticate"] == "Bearer"
        assert TOKEN not in result.text


async def test_valid_bearer_and_lifespan_pass_through():
    calls = []

    async def downstream(scope, receive, send):
        calls.append(scope["type"])
        if scope["type"] == "http":
            await Response(status_code=204)(scope, receive, send)

    wrapped = BearerAuth(downstream, TOKEN)
    await wrapped({"type": "lifespan"}, None, None)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=wrapped), base_url="http://localhost"
    ) as client:
        result = await client.post("/mcp", headers={"Authorization": "bEaReR " + TOKEN})
        assert result.status_code == 204
    assert calls == ["lifespan", "http"]


async def test_auth_keeps_sdk_host_and_origin_protection(monkeypatch, tmp_path):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    monkeypatch.setenv("FLAMORIS_MCP_HUB_ENV_FILE", str(tmp_path / "absent"))
    monkeypatch.setenv("FLAMORIS_MCP_HUB_CONFIG_DIR", str(tmp_path))
    app = create_app()
    async with (
        app.app.router.lifespan_context(app.app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        for extra in ({"Host": "evil.invalid"}, {"Origin": "https://evil.invalid"}):
            result = await client.post(
                "/mcp", headers={"Authorization": "Bearer " + TOKEN, **extra}, json={}
            )
            assert result.status_code in (403, 421)


def test_mounted_env_loaded_before_security(monkeypatch, tmp_path):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    env = tmp_path / ".env"
    env.write_text(f"{TOKEN_ENV}={TOKEN}\n")
    monkeypatch.setenv("FLAMORIS_MCP_HUB_ENV_FILE", str(env))
    assert isinstance(create_app(), BearerAuth)
    monkeypatch.delenv(TOKEN_ENV)
    env.write_text("")
    with pytest.raises(ValueError, match=TOKEN_ENV):
        create_app()


def test_compose_default_is_loopback():
    compose = yaml.safe_load((Path(__file__).parents[1] / "compose.yaml").read_text())
    assert compose["services"]["mcp-hub"]["ports"] == [
        "${FLAMORIS_MCP_HUB_BIND:-127.0.0.1}:${FLAMORIS_MCP_HUB_PORT:-8765}:8765"
    ]
