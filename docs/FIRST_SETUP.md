# MCP Hub：Updaterの入力値と導入後の設定

対象は公開済み1.0.2のインストール定義です。別の版では選定Releaseのカタログと[インストール定義](../release/install-recipe.json)を照合します。
Updaterの画面には短い項目名が表示されます。本書で用途・取得元・空欄時の動作を確認してください。
既定値は入力欄の初期値で、generate=true以外の欄を空にしても自動生成されません。
共通のDB・秘密値の扱い、配置の調べ方、作業の順番は[共通設定ガイド](https://github.com/flamoris-jp/flamoris-updater/blob/main/docs/APPLICATION_SETUP.md)にあります。

## 導入前に決めるもの

外部クライアントに公開する入口、接続するupstream MCPを決めます。
空のmcps directoryでも起動でき、upstreamの接続はtoolを呼ぶまで開始しません。

## Updaterに入力する値

| 項目（キー） | 用途・値の用意 | 初期表示／空欄の動作 |
| --- | --- | --- |
| 待受ポート（PORT） | Hubの入口。未使用のポートを選ぶ | 8769 |
| Hub接続トークン（HUB_TOKEN） | 外部クライアント→HubのBearer認証に使う共有秘密値。Hub側で作り、接続するクライアント側に同じ値を設定 | 空欄でUpdaterが生成。GitHubやOpenAIから取得しない |
| 許可するHost（ALLOWED_HOSTS） | proxy／トンネルで使う実際の入口URLのHostを確認して指定。カンマ区切り | 空欄は外部入口を追加しない。外部URLを選んだら設定を確認 |

HUB_TOKENはruntime.envのFLAMORIS_MCP_HUB_CLIENT_TOKENへ保存されます。
値の所在は[共通設定ガイド](https://github.com/flamoris-jp/flamoris-updater/blob/main/docs/APPLICATION_SETUP.md#自動生成された値はどこにあるか)を参照してください。
Hub入口tokenはupstreamへ転送するtokenではありません。upstreamに認証がある場合は、そのアプリが発行／設定した別の値を使います。

## 導入後にユーザー／AIが行うこと

1. Updaterで起動する。
2. Updaterの配置情報からmanaged mcps directoryを確認し、[READMEのupstream設定](../README.md#upstream-mcp-configuration)に従って各MCPのYAMLを配置する。underscoreで始まるtemplateは有効な接続設定ではない。
3. 各YAMLに実際のendpoint・namespace・現行upstreamと一致するtool schemaを設定する。必要なupstream secretは環境側で解決し、YAMLへ値を埋め込まない。
4. proxy／トンネルを使う場合は入口のHost／必要なOriginと認証境界を設定する。接続clientにHub tokenを設定する。
5. 設定変更の種類に応じてHubを再起動／再作成し、外部からtool一覧と対象upstreamへの接続を確認する。[README](../README.md)の環境変数・mount・再作成の区別を参照する。
6. 必要な場合だけ[個別クライアントprovenance](EXTERNAL_PROVENANCE.md)を設定する。

Studio→Controller、Studio→Agent、内部推論はHubを経由しません。
Hubが起動できたことと、全upstream／外部clientが接続できたことを別に記録します。
