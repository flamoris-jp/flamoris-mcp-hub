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
docker compose up -d --build
```

Both `config/mcps/` and `.env` are mounted read-only into the container. This is intentional: editing either file and restarting the Hub process is enough for the new configuration to be read.

For an external tunnel or reverse proxy, set `FLAMORIS_MCP_HUB_ALLOWED_HOSTS` in `.env` to its exact incoming Host value (for example `mcp.flamoris.net`). If browser requests include an Origin, explicitly set `FLAMORIS_MCP_HUB_ALLOWED_ORIGINS` to that origin. Host/Origin validation remains enabled. Because Compose passes these listener settings as container environment variables, changing them requires `docker compose up -d --force-recreate mcp-hub`. A changed host port mapping also requires container recreation.

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
url: https://lime.flamoris.net/generation-mcp/mcp

api_key_env: GENERATION_MCP_API_KEY
api_key_header: Authorization
api_key_prefix: "Bearer "

tools:
  - name: jobs.submit
    description: Submit one generation workflow.
    input_schema:
      type: object
      properties:
        workflow_id:
          type: string
      required: [workflow_id]
      additionalProperties: false
```

The secret itself lives only in `.env`:

```dotenv
GENERATION_MCP_API_KEY=replace-with-your-secret
```

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

Each upstream has a dedicated task that owns its session from connection through shutdown. Calls to one upstream are queued (up to 16 waiting requests) and serialized. The SDK's HTTP defaults are 30 seconds for connect/write/pool and 300 seconds for read. A catalog mismatch stops forwarding and appears in `hub.upstreams.list`; update the YAML from the reviewed upstream contract and restart the Hub. The included Generation YAML reflects the current Generation MCP tool schemas, including nested workflow arguments.

### Adding an MCP

Adding an MCP is intentionally file-based:

1. create `config/mcps/<mcp-id>.yaml`;
2. register its endpoint and API/tool schemas;
3. add any referenced API key to `.env`;
4. restart the Hub:

```sh
docker compose restart mcp-hub
```

After restart, the MCP's configured APIs are visible to clients immediately. The upstream MCP itself does not need to be running until one of those APIs is called.

Changes to the mounted `.env` secrets and YAML are read on Hub process restart. Compose environment values and port mappings require container recreation.

Files beginning with `_` are ignored, so `config/mcps/_example.yaml` can remain as a template.

### Diagnostics

The Hub exposes:

```text
hub.upstreams.list
```

This reports configured upstreams, whether a live session currently exists, configured tool counts, the last connection error, and any catalog mismatch. It never exposes API key values.

### Credential handling

API keys, access tokens, tunnel credentials, and private keys must never be committed.

YAML files contain only the **name of the environment variable** that holds a secret. The actual value lives in the mounted `.env` file and is resolved only when the Hub needs to establish an upstream connection.

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
