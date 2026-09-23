# AGENTS.md

This repository contains the FLAMORIS MCP Hub.

AI agents and human contributors should treat the Hub as a small MCP aggregation and routing boundary. It must not become a second source of truth for the applications and services behind it.

## Core principles

1. **Keep the Hub thin**
   - The Hub aggregates MCP capabilities and routes calls.
   - Do not move application-specific business logic, workflows, project state, or editing state into the Hub.
   - Prefer delegation to the owning upstream MCP server.

2. **Preserve upstream authority**
   - Each upstream FLAMORIS MCP server remains authoritative for its own tools, state, validation, permissions, and domain behavior.
   - The Hub must not create shadow copies of upstream state.
   - Do not introduce a second `EditorSession`, job authority, media authority, or similar domain authority here.

3. **Use explicit namespacing and static API catalogs**
   - Exposed tools should use a stable namespace identifying the owning upstream MCP server.
   - Example: `generation.jobs.submit`.
   - Each MCP YAML file declares the API/tool surface that the Hub advertises even while the upstream is offline.
   - Tool schemas in YAML are part of the Hub's public contract and must match the owning upstream MCP implementation.
   - Namespace collisions must fail explicitly rather than silently overriding another tool.

4. **Preserve MCP semantics**
   - Forward tool schemas and results without unnecessary transformation.
   - Keep errors attributable to the correct upstream server.
   - Do not invent success when an upstream request failed or became unreachable.

5. **Connection lifecycle is lazy**
   - Hub startup loads configuration and the static API catalog only. It must not require upstream MCP servers to be running.
   - Do not add eager startup connection or discovery as a hidden prerequisite.
   - On tool invocation, reuse a healthy session when possible; if the session is stale or absent, connect before forwarding the call.
   - Never automatically replay a tool call after an ambiguous transport failure. Some tools are non-idempotent.
   - One unhealthy upstream should not corrupt Hub state or silently affect unrelated upstreams.

6. **Security and privacy are part of architecture**
   - Never log secrets, tokens, API keys, private keys, or sensitive payloads.
   - Prefer least-privilege access and bounded resource use.
   - Do not add credential storage to the Hub unless a reviewed design explicitly requires it.

7. **Avoid speculative framework-building**
   - Implement the smallest abstraction required by real upstream MCP servers.
   - Do not generalize hypothetical future transports, capabilities, or orchestration needs without a concrete use case.

8. **AI-native, human-authoritative**
   - AI-assisted development is welcome.
   - Humans remain responsible for reviewing behavior, security, licensing, compatibility, and operational impact.
   - Agents must inspect repository documentation, issues, tests, and current code before proposing substantial changes.

## Change workflow

Before implementing a substantial change:

- read this file;
- read README.md, CONTRIBUTING.md, SECURITY.md, and relevant docs;
- inspect the current implementation and tests;
- inspect the upstream MCP server contracts affected by the change;
- inspect FLAMORIS MCP Core when the change overlaps shared MCP infrastructure;
- identify which component remains authoritative for every piece of state introduced or touched.

For architectural changes, prefer an Issue that records:

- the problem being solved;
- affected upstream MCP servers;
- proposed boundary;
- tool namespace and routing behavior;
- connection lifecycle implications;
- compatibility and failure-mode risks;
- migration plan where relevant.

## Testing

Changes should include deterministic tests where practical.

At minimum, routing and aggregation behavior should cover relevant cases such as:

- tool discovery;
- namespace mapping;
- duplicate or conflicting tool names;
- correct upstream routing;
- upstream unavailability;
- malformed upstream responses;
- cancellation and shutdown;
- reconnection or discovery refresh when supported.

Do not require live production services for ordinary unit tests.

## Licensing

Unless stated otherwise, code in this repository is licensed under Apache License 2.0.

Do not add third-party code, models, model weights, datasets, fonts, media, or generated assets unless their licenses are compatible and clearly documented.

## Support

FLAMORIS does not provide guaranteed individual support.

When diagnosing problems, use the repository, documentation, tests, logs, upstream MCP contracts, and source code as the primary source of truth. AI-assisted self-support is encouraged.
