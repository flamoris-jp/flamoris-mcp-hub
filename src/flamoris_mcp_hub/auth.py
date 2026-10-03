"""Credential-bound identities at the HTTP ingress; secrets never leave this boundary."""

import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

TOKEN_ENV = "FLAMORIS_MCP_HUB_CLIENT_TOKEN"
CLIENTS_FILE_ENV = "FLAMORIS_MCP_HUB_CLIENTS_FILE"
IDENTITY_SCOPE_KEY = "flamoris.hub.external_identity"
IDENTITY_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
MAX_CLIENTS = 64
MAX_SESSIONS = 10000
SESSION_IDLE_SECONDS = 1800


@dataclass(frozen=True)
class ExternalIdentity:
    issuer: str
    subject: str

    def __post_init__(self):
        if not all(
            isinstance(value, str) and re.fullmatch(IDENTITY_PATTERN, value)
            for value in (self.issuer, self.subject)
        ):
            raise ValueError("invalid external identity")


def _token(value: str, name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._~+/-]{32,512}=*", value) or len(value) > 512:
        raise ValueError(f"{name} must contain a 32-512 character Bearer token")
    return value


def client_token() -> str:
    token = os.environ.get(TOKEN_ENV, "")
    return _token(token, TOKEN_ENV)


def configured_clients() -> list[tuple[str, ExternalIdentity]]:
    """Optional non-secret map; an operator binds one credential to one opaque subject."""
    name = os.environ.get(CLIENTS_FILE_ENV, "")
    if not name:
        return []
    try:
        with Path(name).open("rb") as stream:
            raw_bytes = stream.read(16385)
        if len(raw_bytes) > 16384:
            raise ValueError
        raw = json.loads(raw_bytes)
        if not isinstance(raw, dict) or set(raw) != {"issuer", "clients"}:
            raise ValueError
        entries = raw["clients"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_CLIENTS:
            raise ValueError
        clients = []
        seen_subjects, seen_digests, seen_envs = set(), set(), set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"subject", "token_env"}:
                raise ValueError
            env = entry["token_env"]
            if not isinstance(env, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", env):
                raise ValueError
            identity = ExternalIdentity(raw["issuer"], entry["subject"])
            credential = _token(os.environ.get(env, ""), "configured client credential")
            digest = hashlib.sha256(credential.encode("ascii")).digest()
            if identity.subject in seen_subjects or digest in seen_digests or env in seen_envs:
                raise ValueError
            seen_subjects.add(identity.subject)
            seen_digests.add(digest)
            seen_envs.add(env)
            clients.append((credential, identity))
        return clients
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        raise ValueError(f"{CLIENTS_FILE_ENV} is invalid") from None


class BearerAuth:
    def __init__(
        self, app: ASGIApp, token: str, clients: list[tuple[str, ExternalIdentity]] | None = None
    ):
        self.app = app
        self._credentials = [(hashlib.sha256(token.encode("ascii")).digest(), None)]
        for credential, identity in clients or []:
            digest = hashlib.sha256(credential.encode("ascii")).digest()
            if any(hmac.compare_digest(digest, known) for known, _ in self._credentials):
                raise ValueError("duplicate Hub client credential")
            self._credentials.append((digest, identity))
        # Bound to the actual authenticated credential, including legacy anonymous clients.
        # Capacity fails closed; never evict a live binding to admit a new session.
        self._sessions: dict[bytes, tuple[bytes, float]] = {}
        self._pending_sessions = 0

    async def _reject(self, scope, receive, send, status=401):
        response = JSONResponse(
            {"error": "Unauthorized" if status == 401 else "Session unavailable"},
            status_code=status,
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        )
        await response(scope, receive, send)

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
            supplied_digest = hashlib.sha256(supplied).digest()
            matched = False
            identity = None
            for digest, candidate in self._credentials:
                if hmac.compare_digest(supplied_digest, digest):
                    matched, identity = True, candidate
            if not matched:
                await self._reject(scope, receive, send)
                return
            now = time.monotonic()
            self._sessions = {
                key: binding for key, binding in self._sessions.items() if binding[1] > now
            }
            session_values = [
                v for k, v in scope.get("headers", []) if k.lower() == b"mcp-session-id"
            ]
            session = session_values[0] if len(session_values) == 1 else None
            if session_values:
                binding = self._sessions.get(session) if session is not None else None
                if (
                    session is None
                    or not 1 <= len(session) <= 256
                    or binding is None
                    or not hmac.compare_digest(binding[0], supplied_digest)
                ):
                    await self._reject(scope, receive, send, 403)
                    return
                self._sessions[session] = (supplied_digest, now + SESSION_IDLE_SECONDS)
            elif len(self._sessions) + self._pending_sessions >= MAX_SESSIONS:
                await self._reject(scope, receive, send, 503)
                return
            creating = session is None
            if creating:
                self._pending_sessions += 1
            trusted_scope = dict(scope)
            trusted_scope[IDENTITY_SCOPE_KEY] = identity

            async def bound_send(message):
                if message["type"] == "http.response.start":
                    ids = [
                        v for k, v in message.get("headers", []) if k.lower() == b"mcp-session-id"
                    ]
                    if len(ids) == 1 and 1 <= len(ids[0]) <= 256:
                        current = self._sessions.get(ids[0])
                        if current is not None and not hmac.compare_digest(
                            current[0], supplied_digest
                        ):
                            raise RuntimeError("MCP session binding conflict")
                        if current is None and len(self._sessions) >= MAX_SESSIONS:
                            raise RuntimeError("MCP session binding capacity exhausted")
                        self._sessions[ids[0]] = (
                            supplied_digest,
                            time.monotonic() + SESSION_IDLE_SECONDS,
                        )
                    if scope.get("method") == "DELETE" and message["status"] < 400:
                        self._sessions.pop(session, None)
                await send(message)

            try:
                await self.app(trusted_scope, receive, bound_send)
            finally:
                if creating:
                    self._pending_sessions -= 1
            return
        await self.app(scope, receive, send)
