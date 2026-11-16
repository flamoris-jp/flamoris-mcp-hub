# FLAMORIS MCP Hub 1.0.3

Accept 16 MiB MCP request envelopes and use standard JSON responses for tool
calls, enabling existing Files methods to carry 10 MiB binary blocks without a
small SSE event limit. Preserve opaque result forwarding, authentication,
Host/Origin checks, lazy connections, no replay after uncertain mutations and
independent desktop WebSocket bounds. No MCP tool is added or removed.

Deploy alongside Files 0.4.3, its exact refreshed binary schemas and sufficient
proxy request/response limits. Live Work/plugin acceptance is a separate pending
roundtrip, not implied by this release.

Updater compatibility is declared only from 1.0.2. CI performs an actual upgrade
from the published predecessor and checks retained runtime environment, catalog
directory and runtime bindings.

## Previous release notes

# flamoris-mcp-hub v1.0.2

このリポジトリ自身のUpdater配布物とカタログを公開するパッチ版です。amd64/arm64向け配布物はカタログから個別取得できます。初回設定、GPU/モデル動作、実機への導入は別の作業です。既存の集中配布は上書きしません。詳しくはdocs/UPDATER.mdを参照してください。

Docker images now declare the application/version labels required by the Updater installer. Fresh-install recipes remain owned by this repository.
