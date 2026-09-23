# Security Policy

## Reporting a vulnerability

Please do not post suspected security vulnerabilities, credentials, tokens, API keys, private keys, personal data, MCP payloads containing sensitive information, or other secrets in a public issue.

If GitHub private vulnerability reporting is available for this repository, please use it.

If private reporting is not available, avoid publishing exploit details or secrets publicly. Contact the FLAMORIS maintainers through an appropriate private channel before disclosing sensitive details.

For non-sensitive security hardening, dependency updates, transport hardening, or general security discussions, a normal GitHub issue is welcome.

## Supported versions

FLAMORIS is developed as an open-source project without a guaranteed support window or security-response SLA.

Security fixes are generally applied to the current maintained codebase rather than to every historical version.

## Hub-specific scope

The Hub sits on a trust boundary between MCP clients and upstream MCP servers.

Security-sensitive changes include, but are not limited to:

- upstream endpoint configuration;
- authentication or authorization behavior;
- tool discovery and namespace mapping;
- request and result forwarding;
- logging and diagnostics;
- connection lifecycle and reconnection;
- limits on payload size, timeouts, and concurrent work.

Secrets and credentials must not be logged or exposed through MCP tool results.

Third-party dependencies, upstream MCP servers, AI models, services, and media assets may have their own security and support policies.

---

# セキュリティポリシー

## 脆弱性の報告

脆弱性の可能性がある情報、認証情報、トークン、APIキー、秘密鍵、個人情報、機密情報を含むMCP payload、その他の秘密情報を公開Issueへ投稿しないでください。

このリポジトリでGitHubのPrivate vulnerability reportingが利用できる場合は、そちらを使用してください。

Private reportingが利用できない場合も、攻撃手順や秘密情報を公開せず、機密情報を共有する前にFLAMORISのメンテナへ適切な非公開手段で連絡してください。

機密性のないセキュリティ改善、依存関係の更新、transport hardening、一般的なセキュリティ議論については、通常のGitHub Issueを利用して構いません。

## サポート対象

FLAMORISはオープンソースプロジェクトとして開発されており、サポート期間やセキュリティ対応時間を保証していません。

セキュリティ修正は、原則として現在保守しているコードベースへ適用します。

## Hub固有の対象

Hubは、MCP clientと上流MCP serverの間にあるtrust boundaryです。

以下のような変更はセキュリティ上重要です。

- 上流endpoint設定
- 認証・認可
- tool discoveryとnamespace mapping
- request/result forwarding
- loggingとdiagnostics
- connection lifecycleとreconnection
- payload size、timeout、concurrent workの制限

秘密情報や認証情報をログやMCP tool resultへ露出させてはいけません。

第三者の依存ライブラリ、上流MCPサーバー、AIモデル、外部サービス、メディア素材などには、それぞれ別のセキュリティ方針やサポート条件が適用される場合があります。
