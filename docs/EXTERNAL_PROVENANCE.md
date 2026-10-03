# Authenticated external provenance

Hub authenticates external clients, Generation records provenance, and Studio
links an exact `(issuer, subject)` to its own user and authorizes imported assets.
Neither Hub nor Generation assigns a Studio owner. Provenance does not grant
permission to read, mutate or import another user's assets.

## Ingress configuration

The mandatory `FLAMORIS_MCP_HUB_CLIENT_TOKEN` remains a shared, anonymous trust
group. It never becomes a user identity. An optional non-secret JSON file selected
by `FLAMORIS_MCP_HUB_CLIENTS_FILE` enables individual client credentials:

```json
{
  "issuer": "hub.example",
  "clients": [
    {"subject": "opaque-client-a", "token_env": "EXTERNAL_CLIENT_A_TOKEN"},
    {"subject": "opaque-client-b", "token_env": "EXTERNAL_CLIENT_B_TOKEN"}
  ]
}
```

Mount this file read-only in the Hub container and set its in-container absolute
path in the mounted `.env`. Put random 32–512 character Bearer credentials only
in the referenced environment variables, separate from the shared token. Do not
put secrets in JSON, YAML, URLs or source control. Config is read at startup;
restarting with unchanged issuer/subject preserves identity, including after a
tunnel reconnect. Credential rotation preserves the configured subject but
requires a new authenticated MCP session.

The file is limited to 16 KiB and 64 clients. Issuer and subject match
`[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`; use opaque identifiers rather than emails or
human names. Duplicate subjects, credentials or environment references fail
startup. An unknown credential fails authentication. A session established by
one credential cannot be reused by another, including by the anonymous token.
The binding table allows at most 10,000 sessions and fails closed at capacity;
it does not discard live bindings to admit an attacker. Bindings stay live while
an authenticated HTTP request, including GET/SSE, is in flight. The 30-minute idle
deadline starts after request completion, matching the SDK's default idle limit.

No incoming HTTP identity header, tool argument or caller `_meta` is trusted or
forwarded as provenance. Only the credential selected by Hub's middleware can
produce a downstream identity. The credentials themselves are never forwarded.

## Approved Generation route

Enable only on the reviewed Generation Streamable HTTP route:

```yaml
id: generation
namespace: generation
transport: streamable-http
url: https://generation.example.com/mcp
external_provenance_secret_env: GENERATION_PROVENANCE_SECRET
# Keep the exact tools from the matching tracked Generation catalog.
```

Configure the same independent random secret in Generation's
`FLAMORIS_PROVENANCE_SECRET` and its expected issuer in
`FLAMORIS_PROVENANCE_ISSUER`. The signing secret must differ from every Hub client
token. A missing or invalid secret fails startup. Only the Generation HTTP
namespace can opt in; other HTTP and desktop routes receive no identity context.
Legacy anonymous calls omit provenance and retain their existing behavior.

The key is frozen when the registry starts. Rotate Hub and Generation together
under paused submission ingress, then reconnect and verify the pair. Keep the
upstream network/proxy authentication boundary: provenance verification does
not make Generation's entire MCP API authenticated and does not restrict its
existing anonymous/internal calls.

## Per-request wire contract

Hub attaches a fresh MCP request `_meta` extension under
`flamoris.dev/external-provenance`. The exact envelope is:

```json
{
  "version": 1,
  "issuer": "hub.example",
  "subject": "opaque-client-a",
  "issued_at": 1790985600,
  "nonce": "0123456789abcdef0123456789abcdef",
  "signature": "64-lowercase-hex-characters"
}
```

`issued_at` is integer UTC seconds, the nonce is a fresh UUID4 encoded as 32
lowercase hexadecimal characters, and the signature is HMAC-SHA256 in lowercase
hexadecimal. The signed object contains all five unsigned envelope fields plus
`tool` (the unprefixed upstream tool name) and `arguments` (the original argument
dictionary). Its bytes use Python JSON canonicalization:

```python
json.dumps(
    payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
).encode("ascii")
```

Signed canonical requests are bounded to 256 KiB, including escaped argument
strings and envelope fields; oversized calls fail before downstream dispatch.
Generation verifies the expected issuer,
strict fields, signature, ±30 second freshness and nonce before tool effects.
Its bounded durable replay journal retains live nonces for 61 seconds across
restarts, has a 4,096-entry capacity, and commits each nonce before effects.
Capacity, clock rollback, corrupt persistence or ambiguous journal writes fail
closed. Replay rejection does not
provide an idempotency key: Hub never retries an ambiguous tool call. Signatures,
nonces and secrets are not public job/asset metadata. Only the optional
`external_provenance: {issuer, subject}` is retained by Generation.

Each queued Hub call holds its own immutable authenticated identity. Signing
happens immediately before that call is sent through the existing lazy session;
there is no mutable session-level identity/header or session per user. Calls
from clients A, B and the anonymous trust group can reuse one upstream transport
without carrying the preceding client's identity into the next call.

Public tool schemas and exact catalog comparison remain unchanged. A real SDK
loopback test covers authentication, reconnects, spoofed caller metadata,
cross-credential session rejection, signatures on a reused upstream connection
and clean transport teardown. Real tunnel/provider/Studio two-user validation
still requires the matched deployed revisions and operator credential/link
configuration.
