# FLAMORIS MCP Hub

Single-entry MCP hub for FLAMORIS, aggregating and routing namespaced tools across multiple MCP servers.

FLAMORIS MCP Hub provides one MCP-facing entry point for independently owned FLAMORIS MCP servers.
It reads a static tool catalog, exposes tools under explicit namespaces, and routes calls to the correct upstream server without taking ownership of application state.

The repository starts intentionally small. The Hub is a transport and aggregation boundary, not a replacement for the domain authority held by each FLAMORIS application or service.

## Goals

- expose multiple FLAMORIS MCP servers through a single MCP connection;
- preserve upstream MCP servers as the source of truth for their own tools and state;
- provide predictable namespaced tool names such as `generation.jobs.submit`;
- route calls without duplicating application behavior;
- keep connection lifecycle, failures, and diagnostics explicit;
- remain small enough to understand, test, and replace.

## Non-goals

The Hub should not become:

- a shared application database;
- a second `EditorSession` or domain-state authority;
- a workflow engine for application-specific behavior;
- a place to copy upstream tool implementations;
- an implicit authentication or secrets vault.

Those responsibilities belong to the owning application, service, or a deliberately separate infrastructure component.

## Tool naming

Upstream tools should be exposed with a stable namespace that identifies their owning MCP server.

Examples:

```text
generation.jobs.submit
generation.models.list
cutwork.parts.list
kachinco.timeline.get
```

The exact mapping and collision policy will be documented alongside the implementation.


## Runtime and deployment

FLAMORIS MCP Hub is a Python service intended to run in Docker.

The default container exposes one Streamable HTTP MCP endpoint on port `8765` at `/mcp`.

```sh
cp .env.example .env
cp config/mcps/_generation.example.yaml config/mcps/generation.yaml
# Edit .env and config/mcps/generation.yaml for your deployment.
# Set FLAMORIS_MCP_HUB_CLIENT_TOKEN to a random token (see below).
docker compose up -d --build
```

Both `config/mcps/` and `.env` are mounted read-only into the container. This is intentional: editing either file and restarting the Hub process is enough for the new configuration to be read.

Runtime MCP YAML files are deployment configuration and are intentionally ignored by Git. Tracked files whose names begin with `_` are templates only; the Hub ignores them. Copy a template to a non-underscore `.yaml` file and set the endpoint for your own environment.

For an external tunnel or reverse proxy, set `FLAMORIS_MCP_HUB_ALLOWED_HOSTS` in `.env` to its exact incoming Host value (for example `mcp.example.com`). If browser requests include an Origin, explicitly set `FLAMORIS_MCP_HUB_ALLOWED_ORIGINS` to that origin. Host/Origin validation remains enabled. Because Compose passes these listener settings as container environment variables, changing them requires `docker compose up -d --force-recreate mcp-hub`. A changed host port mapping also requires container recreation.

### Upgrading an existing deployment

Hub HTTP clients now require `Authorization: Bearer <client token>` for every
request, including initialization, GET/SSE and session deletion. Set
`FLAMORIS_MCP_HUB_CLIENT_TOKEN` in the mounted `.env` before starting/upgrading and
configure each client to send it. Missing/invalid token configuration stops
startup. Generate a secret locally with:

```sh
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

The token must be 32-512 Bearer-token characters. Never put it in YAML, URLs,
source control or logs. Rotate it by changing `.env` and restarting the Hub;
existing sessions must also send the new token. This default is one shared trust
group without per-user identity. Do not share it with untrusted clients. Optional
individual credential-bound provenance is described in
[Authenticated external provenance](docs/EXTERNAL_PROVENANCE.md); Studio remains
the authority for account linking and asset authorization.

Compose publishes to `127.0.0.1` by default. An intentional non-loopback mapping
requires `FLAMORIS_MCP_HUB_BIND` and container recreation. Use TLS and an
authenticated front door for external access, retain the Hub token check and
restrict direct access to its port. Host/Origin allowlists are still enforced;
they do not authenticate clients. A proxy must preserve the Bearer header (or
inject a trusted token only after authenticating its own clients). If the client
cannot send a configured Bearer token, use that authenticated proxy boundary.

Hub client tokens are never forwarded as upstream credentials. Optional upstream
`api_key_env` variables remain separate. Both the CLI and `server:app` ASGI
entrypoint enforce the same check; there is no unauthenticated HTTP mode.

Older checkouts may have `config/mcps/generation.yaml` tracked by Git. Before updating such a checkout, save the deployment-specific YAML outside the repository. The public repository now tracks only underscore-prefixed templates, so Git may remove the previously tracked runtime file during the update.

After updating, copy `config/mcps/_generation.example.yaml` to `config/mcps/generation.yaml`, then restore the endpoint and authentication settings for that deployment. The resulting runtime YAML is intentionally ignored by Git.

The template includes `assets.prepare` and `assets.read` for bounded asset
delivery. Existing deployments must add these exact tool definitions to their
runtime YAML and restart the Hub after deploying a compatible Generation MCP.
Studio uses these tools for images above its small native-image threshold, so
leaving an older runtime catalog in place will prevent preview and download.
The Hub does not authorize individual Studio users; Studio checks ownership on
every transfer request before forwarding it through the authenticated Hub.

### MCP image display and download

`generation.assets.get` forwards MCP-native `ImageContent` unchanged. A client
must explicitly display that returned image using its own supported rendering
mechanism; returning base64 inside tool output alone does not guarantee a chat
attachment. For example, a client with an image-emission helper should pass the
individual image content block to that helper rather than printing its base64
data. Hub cannot choose or confirm the client application's display behavior.

Large assets use the bounded `generation.assets.prepare` / `generation.assets.read`
contract. Studio checks the logged-in user's ownership before each chunk and
serves its own authenticated preview/download. These tools do not return a
public URL or raw provider/server path. Client UI display and any future MCP
resource/download endpoint still require independent client acceptance (#8).

### Optional Generation v3 route

`config/mcps/_generation-v3.example.yaml` exports the 27-tool contract from
[Generation #51](https://github.com/flamoris-jp/flamoris-generation-mcp/pull/51),
exported from commit c967ede801a3878960bf8acffb545acfaf4f4ae1, including five separately named `workflows.v3.*` tools. Schema/annotation fixtures
preserve every legacy tool. The template is ignored until copied to the existing
runtime `generation.yaml`; replace that file rather than enabling both templates,
which would conflict on upstream id and namespace. Restore your own endpoint and
credential references when replacing it.

Deploy the compatible Generation revision with `FLAMORIS_WORKFLOW_V3_ENABLED=true`
before switching this catalog. A v3 catalog against an older/disabled upstream
blocks forwarding before a tool call. The legacy catalog continues to work with
an upgraded upstream but does not expose the new tools. No startup connection,
workflow registration, smoke, model selection or runtime activation is added.

Generation remains the sole version registry, verifier, JobStore and asset owner.
Use its exact id/version/digest and opaque built workflow handles; the Hub forwards
readiness, revocation, errors and unknown submission results unchanged and never
replays a verification/generation call. The first profile is one audited Image
leaf inside pinned pass-through wrappers. Multiple components, other media, real
GPU smoke and the Studio v3 route remain separate rollout gates. See Generation's
[execution guide](https://github.com/flamoris-jp/flamoris-generation-mcp/blob/main/docs/IMAGE_V3_EXECUTION.md).

### Intelligence route

`config/mcps/_intelligence.example.yaml` contains the exact six-tool raw
Intelligence contract exported from `flamoris-intelligence-mcp` commit
`043b39b064fbedf9ed9a3e9e9eb57c6856efbb5c`, with schema/annotation parity fixtures.
Copy it to `intelligence.yaml` only after reviewing the actual configured provider
and prompt/output data flow. Set the deployment endpoint and any authenticated
proxy credential reference; never copy a token into YAML. Replace the catalog and
upstream together if the contract changes. Startup/discovery remains offline and
does not load a model, probe a provider or run inference.

This route shares the Hub's existing trusted client group. It supplies no Studio
user identity, per-user result ownership, or Agent delegation. Studio's raw editor
uses its authenticated backend gateway; do not expose Agent sessions through this
shared token as if it authenticated individual users. Scoped Agent integration
remains under #25/#28. The Hub forwards raw structured/error results unchanged,
and never retries an ambiguous inference call.

Upstream discovery with duplicate tool names or a pagination cursor fails closed
before any call. Update/reconnect a matching full static catalog to recover;
partial discovery does not prove all configured tools are compatible.

## Upstream MCP configuration

The Hub uses **one YAML file per MCP** under:

```text
config/mcps/
```

A file describes both:

1. where the upstream MCP lives; and
2. which APIs/tools the Hub should advertise for it.

Example:

```yaml
id: generation
namespace: generation
enabled: true
transport: streamable-http
url: https://generation.example.com/mcp

# Optional when the upstream deployment requires bearer authentication:
# api_key_env: GENERATION_MCP_API_KEY
# api_key_header: Authorization
# api_key_prefix: "Bearer "

tools:
  - name: jobs.submit
    description: Submit one generation workflow.
    annotations:
      readOnlyHint: false
      destructiveHint: false
      openWorldHint: false
    input_schema:
      type: object
      properties:
        workflow_id:
          type: string
      required: [workflow_id]
      additionalProperties: false
```

Generation MCP currently has no application-level Bearer authentication. The
shipped template therefore sends no Authorization header and requires no
`GENERATION_MCP_API_KEY`. Do not create a dummy credential: protect that upstream
at its network/proxy boundary. Enable the optional fields only when the selected
upstream or an authenticated proxy actually validates them.

When another upstream requires a secret, the secret itself lives only in `.env`:

```dotenv
OTHER_MCP_API_KEY=replace-with-your-secret
```

### Tool annotations and existing catalogs

The Hub advertises `annotations` on every tool, including `hub.upstreams.list`.
Configure `readOnlyHint`, `destructiveHint`, and `openWorldHint` as YAML booleans
for each reviewed tool. Optional `idempotentHint` and `title` are preserved.
These hints describe effects; they do not grant permission or replace upstream
authorization. Strings such as `"false"`, numbers, null annotations, and unknown
annotation keys are rejected at configuration load.

Existing catalogs without annotations still load. Missing hints use conservative
MCP defaults: `readOnlyHint: false`, `destructiveHint: true`, `openWorldHint: true`.
The Hub does not guess effects from names or contact upstreams at discovery time.
Explicit partial annotations retain the same defaults for omitted hints.

When upgrading, add reviewed annotations to **each deployment-local YAML** using
the templates as references and restart the Hub. Preserve the deployment endpoint,
authentication references and exact schemas. Updating underscore templates alone
never changes a mounted runtime catalog. Desktop registration exports may also
omit annotations; add them after reviewing the exposed editing APIs.

The shipped Generation template treats result/asset materialization and workflow
building as mutations, and cancellation/deletion/recipe replacement as destructive.
Its endpoints are bounded configured providers, so `openWorldHint` is false. Revisit
that hint if a deployment permits workflows accessing arbitrary external entities.
GPU runtime activation/stop are disruptive mutations, not read-only observations.
Unknown tools retain conservative defaults until their actual behavior is reviewed.

OpenAI's current [annotation reference](https://developers.openai.com/plugins/reference#annotations)
requires the three boolean hints. After deployment, refresh/scan the tool catalog
and retry plugin creation. Missing annotations were a confirmed metadata defect;
resolution of a particular registration error requires that live acceptance test.

### Startup behavior: recognize, do not connect

Hub startup is deliberately **catalog-only**.

On process startup the Hub:

- reloads the mounted `.env`;
- reads every enabled `config/mcps/*.yaml` file;
- validates IDs, namespaces, endpoints, and static tool schemas;
- builds the public namespaced tool catalog.

It performs **no upstream MCP network connection** during startup.

Therefore the Hub can start normally when Generation MCP, Cutwork, Kachinco, or every upstream MCP is offline.

A configured tool such as:

```text
jobs.submit
```

under namespace:

```text
generation
```

is advertised to clients as:

```text
generation.jobs.submit
```

The tool remains visible in `tools/list` even while Generation MCP is stopped.

### Call-time connection behavior

An upstream connection is needed only when a client actually invokes one of its tools.

For each tool call the Hub:

1. locates the owning MCP from the static catalog;
2. reuses the existing session when it is still usable;
3. uses a read-only `tools/list` request to detect a stale session;
4. if no usable session exists, connects to the configured upstream endpoint using the API key resolved from `.env`;
5. verifies that every configured tool still exists and its input schema matches the upstream catalog;
6. forwards the tool call exactly once.

If the connection cannot be established, the Hub returns a tool error to the caller. The Hub itself remains running and other MCPs are unaffected.

If transport fails **after the real tool call may have been sent**, the Hub does not automatically replay that call. This avoids accidental duplicate execution of non-idempotent APIs such as generation submission.

Each upstream has a dedicated task that owns its session from connection through shutdown. Calls to one upstream are queued (up to 16 waiting requests) and serialized. Cancelled requests and requests still waiting when shutdown begins are skipped before dispatch; a call already sent to the upstream is not retried. The Hub configures HTTP timeouts of 30 seconds for connect/write/pool and 300 seconds for read. A catalog mismatch stops forwarding and appears in `hub.upstreams.list`; update the YAML from the reviewed upstream contract and restart the Hub. The tracked `config/mcps/_generation.example.yaml` template reflects the current Generation MCP tool schemas, including nested workflow arguments and `generation.inputs.create/get/delete`. It is not an enabled deployment target until you copy it to a runtime YAML file. Existing deployments must update their runtime `generation.yaml` and restart the Hub to expose the new tools; the template is never activated automatically.

### Adding an MCP

Adding an MCP is intentionally file-based:

1. copy a tracked template such as `config/mcps/_generation.example.yaml`, or create `config/mcps/<mcp-id>.yaml`;
2. register the endpoint and API/tool schemas for your deployment;
3. add any referenced API key to `.env`;
4. restart the Hub:

```sh
docker compose restart mcp-hub
```

After restart, the MCP's configured APIs are visible to clients immediately. The upstream MCP itself does not need to be running until one of those APIs is called.

Changes to the mounted `.env` secrets and YAML are read on Hub process restart. Compose environment values and port mappings require container recreation.

Files beginning with `_` are ignored by the Hub, so tracked templates such as `config/mcps/_example.yaml` and `config/mcps/_generation.example.yaml` are safe to keep in the repository. Non-underscore runtime YAML files are ignored by Git so deployment-specific endpoints do not become public defaults.

### GPU Node Manager upstream (LIME deployment)

Copy `config/mcps/_lime.example.yaml` to a deployment-local `lime.yaml` and set its
endpoint. The namespace remains `lime` as a deployment-facing name, while the
owning public service is
[`flamoris-gpu-node-manager`](https://github.com/flamoris-jp/flamoris-gpu-node-manager).
The template stays disabled by its underscore prefix. Its five-tool surface matches
the current GPU Node Manager MCP contract. The pinned fixture was originally
exported from the former LIME Manager revision recorded in
`tests/fixtures/lime-tools.json`; future schema changes should be reviewed and
repinned deliberately. The usual exact schema check runs before forwarding a call.

The upstream currently requires no application Bearer token. Protect its
endpoint at the deployment boundary; do not fabricate credentials. Container
loopback refers to the container, so choose a reachable, restricted deployment
endpoint rather than assuming the template URL reaches the host.

Clients explicitly invoke:

```text
lime.system.status()
lime.runtime.activate(runtime_id="comfyui")
generation.workflows.build(...)
generation.jobs.submit(...)
```

The other tools are `lime.runtime.list`, `lime.runtime.status` and
`lime.runtime.stop`. This sequence is a client decision, not Hub automation.
GPU Node Manager alone owns runtime transitions, GPU handoff and readiness. Startup
remains catalog-only even when the GPU Node Manager upstream is offline; ambiguous activate/stop
calls are never replayed. Later calls may reconnect through the existing lazy
session lifecycle. No systemd or runtime-selection logic lives in the Hub.

### Diagnostics

The Hub exposes:

```text
hub.upstreams.list
```

This reports configured upstreams, whether a live session currently exists, configured tool counts, the last connection error, and any catalog mismatch. It never exposes API key values.

### Credential handling

API keys, access tokens, tunnel credentials, and private keys must never be committed.

When authentication is configured, YAML files contain only the **name of the environment variable** that holds a secret. The actual value lives in the mounted `.env` file and is resolved only when the Hub needs to establish an upstream connection. Upstreams that are already protected by an appropriate deployment boundary may omit the API-key fields.

## Philosophy

FLAMORIS is open-source software for creative work and AI-native production.

Use it however you like.

Commercial use is welcome and does not require permission.  
If you'd like, we'd be happy to hear what you used FLAMORIS for.  
This is completely optional.

FLAMORIS software is provided as-is.
We do not provide individual support or guaranteed assistance.

If you run into trouble, we encourage you to let your AI assistant read the repository, documentation, issues, and source code and help you solve it.

If FLAMORIS helps you or you find it interesting,
your support helps fund development and keeps the project growing. 🌱  
<sub>Mostly GPU bills.</sub>

---

## 方針

FLAMORISは、クリエイティブ制作とAIネイティブな制作環境のためのオープンソースソフトウェアです。

勝手に使ってください。  
改造しても、組み込んでも、面白いものや変なものを作ってもOKです。

商用作品や製品で使う場合も、許可は不要です。  
もしよければ「こんなのに使ったよ」と教えてもらえるとうれしいです。  
もちろん強制ではありません。

FLAMORISのソフトウェアは現状のまま提供されます。  
個別サポートや動作保証はありません。

困ったときは、README、ドキュメント、Issue、ソースコードをあなたのAIに読ませて、自己サポートしてもらってください。

もし、あなたのお役に立てたり、面白いと思っていただけたなら、  
開発費用をご支援いただけるとうれしいです。  
FLAMORISは元気になって育ちます。🌱  
<sub>主にGPU代とか。</sub>

## License

Code in this repository is licensed under the [Apache License 2.0](LICENSE), unless otherwise noted.

Third-party code, services, models, model weights, datasets, media, and other non-code assets may use separate licenses. Their applicable licenses must be stated alongside those assets.

## Related repositories

- [FLAMORIS Commons](https://github.com/flamoris-jp/flamoris-commons) — shared foundations and architecture
- [FLAMORIS MCP Core](https://github.com/flamoris-jp/flamoris-mcp-core) — shared MCP infrastructure for FLAMORIS applications and tools
- [FLAMORIS Generation MCP](https://github.com/flamoris-jp/flamoris-generation-mcp) — provider-neutral generation MCP server
- [FLAMORIS organization configuration](https://github.com/flamoris-jp/.github) — shared GitHub profile and community health files

## Desktop connectors (Core/Wpf 1.2.0)

`transport: reverse-websocket` accepts an outbound connection from the desktop at
`wss://<hub-host>/desktop/<upstream-id>`. Keep HTTPS/WSS termination and the explicit
Host allowlist at your reverse proxy; forward WebSocket Upgrade/Connection headers.
Do not expose a desktop listener. Existing Streamable HTTP upstreams are unchanged.

Start with `config/mcps/_desktop.example.yaml`, copy it to a non-underscore YAML name,
and set `connector_token_env` to a separate random secret of at least 32 characters.
Generate each connector secret locally with
`python -c 'import secrets; print(secrets.token_urlsafe(32))'` and configure the
same value in that desktop application's Windows Credential Manager. Connector
credentials authenticate Desktop -> Hub; optional `*_MCP_API_KEY` values
authenticate Hub -> upstream and are separate from the Hub client token.
This credential is independent of the Hub's client token and is scoped to one logical
upstream. Enter the same secret through the desktop's Settings (Windows Credential
Manager). `product_id` must match the application: `flamoris.cutwork`, `flamoris.2d`,
`flamoris.kachinco`. An occupied upstream rejects takeover.

The starter example advertises only `mcp.context`. To expose editing APIs, start the
connection and use **Copy Hub registration settings** in the shared Hub settings.
Review the resulting JSON (also valid YAML), including the exact schemas, namespace
and credential environment variable, before replacing the Hub catalog and restarting.
This is an explicit administrator action; a connector cannot add unreviewed tools to
the public catalog. Read-only connections omit mutations and reject direct attempts.

The Hub remains healthy while desktops are offline. `hub.upstreams.list` reports the
connection and catalog mismatch. One call is in flight per desktop; excess calls fail
as busy. A call whose delivery is ambiguous is never retried. Disconnect, shutdown or
client cancellation cancels uncommitted work, but cannot undo an already committed edit.
Connector and client authentication are separate. Browser-origin WebSockets, duplicate
authorization headers, bad hosts, unknown IDs and missing credentials are rejected.

Deployment to a live Hub and physical Windows UI acceptance are separate from source
integration. No production secrets or deployment-specific paths are supplied here.


## Generation Workflow rollout

The Generation template includes workflows.verify and version/digest/require_ready
build preconditions. It is exported from the Generation MCP protocol; the fixture
records exact schemas and annotations. Update the deployed catalog together with
Generation during a maintenance window: pause ingress, drain/reconcile work, replace
the singleton/catalog pair, restart Hub, check parity on a fresh connection, then
deploy Studio and reopen. Mixed schemas reject the entire connection, even health.
Roll back the matching pair with compatible Studio/DB and persistence; preserve data.
Hub forwards outcomes unchanged and never retries unknown submissions or certifies ready.
