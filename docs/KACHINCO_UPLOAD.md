# Kachinco media upload catalog

Kachinco #76 / Hub #51 add four guarded tools to the existing desktop reverse
connection: `kachinco.media_upload_begin`, `media_upload_write`,
`media_upload_finish`, and `media_upload_cancel` (all under `kachinco`).
Kachinco owns bytes, destinations, probing, assets and shared Undo/Redo. The Hub
does not download URLs, retain files, track offsets, or replay requests.

## Additive rollout

1. Install the reviewed Kachinco build containing these tools. Reconnect with an
   **Edit** grant and copy its Hub registration settings. Read-only connections
   intentionally omit these mutations.
2. Review the generated schemas against
   `config/mcps/_kachinco-media-upload.example.yaml`. Its JSON is valid YAML.
   **Merge the four tool entries into the deployment's existing Kachinco catalog**;
   preserve all existing editing tools, namespace, credentials and connection settings.
   The example alone advertises context and upload, not the editor's full surface.
3. Restart the Hub through its normal owner workflow. Check offline discovery,
   reconnect and `hub.upstreams.list` for catalog parity. An old desktop in Edit
   mode fails catalog parity until it has the matching tools. Do not switch a
   deployment catalog before upgrading the desktop.
4. Import a small WAV and MP4; verify them with the editor's `get_project` and
   shared Undo/Redo. Confirm read-only denial and disconnect cleanup.

The leading underscore keeps the example inactive. Source acceptance does not
deploy a catalog or change a desktop permission.

## Client sequence and recovery

Read current context and pass `input` plus the current runtime/document/revision
`guard` to every tool. Create an upload UUID and SHA-256 locally; begin with the
basename, total decimal-string byte count and lowercase digest. Send contiguous
base64 chunks of at most 131072 decoded bytes with decimal-string offsets and
each chunk's lowercase SHA-256. Finish verifies the whole digest and probes the
actual media before registering one asset. Refresh context after finish changes
revision. Placing the asset on a track remains a separate editor command.

Per file: 1–536870912 bytes; at most two unfinished uploads per desktop attachment.
PNG/JPEG/WebP, MOV/MP4 and WAV/MP3/M4A match ordinary import. Paths, URLs and
caller-supplied media metadata are not accepted. The 128 KiB chunk fits the
existing desktop and Hub message limits; no transport-limit increase is needed.

If a response is lost, Hub reports uncertainty and never retries automatically.
Before explicitly retrying finish, inspect `get_project` for the upload UUID,
which is also the resulting asset ID. Repeating begin with identical metadata
reports received bytes while that attachment remains live; an identical written
chunk can be explicitly resent. A new attachment does not resume old staged bytes.
Revocation removes unfinished transfers. Successfully imported files survive
Undo, reconnect and saved-project reopen. Cancellation only discards unfinished
transfers; it cannot undo a committed asset.

## Contract evidence

`tests/fixtures/kachinco-media-upload-tools.json` is copied from Kachinco's
`MediaUploadTests.CatalogMatchesMcpCoreWireContract` export. That upstream test
uses the actual MCP Core 1.3.1 wire descriptor and pins its result. Hub tests
compare the example with this producer fixture and exercise a maximum chunk
through an official HTTP MCP client and the reverse WebSocket. Update both
reviewed fixtures together whenever the producer contract changes.
