# Contributing to FLAMORIS MCP Hub

Thank you for your interest in FLAMORIS.

FLAMORIS MCP Hub exists to provide a small, explicit aggregation and routing boundary for independently owned FLAMORIS MCP servers. Please keep changes focused and avoid moving upstream application behavior into the Hub.

## Before contributing

Issues are welcome from everyone. Pull requests are accepted only from repository collaborators. Please open an Issue to propose fixes, features, or documentation changes.

For larger changes, new routing or discovery behavior, namespace changes, transport changes, or changes that affect multiple upstream MCP servers, please open an issue first so the intended boundary can be discussed before implementation.

Before proposing a shared behavior, confirm that it genuinely belongs in the Hub rather than in an upstream MCP server or FLAMORIS MCP Core.

## Pull requests

Please:

- keep changes focused;
- include or update tests where practical;
- explain routing, lifecycle, security, or compatibility impact;
- preserve existing public behavior unless the change intentionally modifies it;
- avoid introducing unnecessary dependencies;
- document externally visible tool naming or connection behavior;
- keep application-specific state and business logic in the owning upstream service.

AI-assisted contributions are welcome. The contributor remains responsible for reviewing, testing, and understanding the submitted change.

## Licensing

Unless explicitly stated otherwise, code contributions are submitted under the Apache License 2.0.

Do not add third-party code, models, datasets, media, or other assets unless their licenses are compatible and clearly documented.

## Support

FLAMORIS does not provide guaranteed individual support.

If you are working through a problem, please use the repository documentation, issues, tests, logs, upstream MCP documentation, and source code as primary references. AI-assisted self-support is encouraged.

---

# FLAMORIS MCP Hub へのコントリビューション

FLAMORISに興味を持っていただきありがとうございます。

FLAMORIS MCP Hubは、独立した複数のFLAMORIS MCPサーバーを、小さく明示的な集約・ルーティング境界でつなぐためのリポジトリです。Hubへ上流アプリケーション固有の挙動を移さず、変更範囲を明確に保ってください。

## 変更を始める前に

Issueはどなたでも歓迎します。Pull Requestはリポジトリのcollaboratorのみ受け付けています。修正、機能、ドキュメント変更などの提案はIssueからお願いします。

大きな変更、新しいrouting/discoveryの挙動、namespace変更、transport変更、複数の上流MCPに影響する変更は、実装前にIssueで意図や境界を相談してください。

共通化を提案する前に、その責務がHubではなく上流MCPサーバーやFLAMORIS MCP Coreに属するものではないか確認してください。

## Pull Request

以下を意識してください。

- 変更範囲を絞る
- 可能な範囲でテストを追加・更新する
- routing、lifecycle、security、compatibilityへの影響を書く
- 意図的な変更でない限り、既存の公開動作を壊さない
- 不要な依存関係を増やさない
- 外部から見えるtool名や接続挙動は文書化する
- アプリ固有のstateやbusiness logicは所有する上流サービス側に残す

AIを使ったコントリビューションも歓迎します。提出する変更の確認、テスト、内容の理解については、コントリビュータ自身が責任を持ってください。

## ライセンス

明記がない限り、コードへのコントリビューションはApache License 2.0の条件で提供されます。

第三者のコード、AIモデル、データセット、画像・音声などの素材を追加する場合は、互換性のあるライセンスであることを確認し、そのライセンスを明示してください。

## サポート

FLAMORISは個別サポートを保証しません。

困ったときは、README、ドキュメント、Issue、テスト、ログ、上流MCPのドキュメント、ソースコードを主な参照先として使ってください。AIによる自己サポートも歓迎します。
