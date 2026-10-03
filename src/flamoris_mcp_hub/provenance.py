"""One signed context per approved downstream call; never public ownership authority."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid

from mcp.types import RequestParamsMeta

from .auth import ExternalIdentity, _token

META_KEY = "flamoris.dev/external-provenance"


class ProvenanceSigner:
    def __init__(self, secret_env: str):
        self._key = _token(os.environ.get(secret_env, ""), "provenance signing secret").encode(
            "ascii"
        )

    def metadata(self, identity: ExternalIdentity, tool: str, arguments: dict) -> RequestParamsMeta:
        envelope = {
            "version": 1,
            "issuer": identity.issuer,
            "subject": identity.subject,
            "issued_at": int(time.time()),
            "nonce": uuid.uuid4().hex,
        }
        payload = {**envelope, "tool": tool, "arguments": arguments}
        try:
            canonical = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
            ).encode("ascii")
        except (ValueError, TypeError, RecursionError):
            raise ValueError("invalid provenance request") from None
        if len(canonical) > 4 * 1024 * 1024:
            raise ValueError("provenance request is too large")
        envelope["signature"] = hmac.new(self._key, canonical, hashlib.sha256).hexdigest()
        return {META_KEY: envelope}
