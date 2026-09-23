# FLAMORIS MCP Hub

Single-entry MCP hub for FLAMORIS, aggregating and routing namespaced tools across multiple MCP servers.

FLAMORIS MCP Hub provides one MCP-facing entry point for independently owned FLAMORIS MCP servers.
It discovers upstream tools, exposes them under explicit namespaces, and routes tool calls to the correct upstream server without taking ownership of application state.

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
