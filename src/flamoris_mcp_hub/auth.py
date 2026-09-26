"""Single trust-group HTTP authentication; upstream credentials stay independent."""

import hashlib
import hmac
import os
import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

TOKEN_ENV = "FLAMORIS_MCP_HUB_CLIENT_TOKEN"


def client_token() -> str:
    token = os.environ.get(TOKEN_ENV, "")
    if not re.fullmatch(r"[A-Za-z0-9._~+/-]{32,512}=*", token) or len(token) > 512:
        raise ValueError(f"{TOKEN_ENV} must contain a 32-512 character Bearer token")
    return token


class BearerAuth:
    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self._digest = hashlib.sha256(token.encode("ascii")).digest()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] == "http":
            values = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
            supplied = b""
            if len(values) == 1 and len(values[0]) <= 1024:
                scheme, separator, value = values[0].partition(b" ")
                if separator and scheme.lower() == b"bearer":
                    supplied = value
            if not hmac.compare_digest(hashlib.sha256(supplied).digest(), self._digest):
                response = JSONResponse(
                    {"error": "Unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
