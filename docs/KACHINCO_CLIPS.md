# Kachinco clip speed and download catalog

Companion to Kachinco #78–#79. The desktop owns timeline/source time, rendering,
job cancellation and temporary output. Hub routes ordinary JSON including bounded
base64 chunks and never stores or interprets media.

The inactive `_kachinco-clips.example.yaml` contains four new download tools and
the **complete replacement schema for `edit_batch`**, including `SetClipSpeed`.
`tests/fixtures/kachinco-clip-tools.json` is copied from the actual MCP Core wire
descriptor exported by Kachinco's `ClipDownloadTests.CatalogMatchesProducerWireDescriptor`.
Do not hand-recreate only the new command or replace a deployed catalog wholesale.

## Rollout

1. Upgrade Kachinco to the reviewed producer build. Download tools work with
   ReadOnly or Edit; speed changes require Edit.
2. Copy the desktop's registration settings. Merge `clip_download_begin/status/read/cancel`
   and replace only `edit_batch` in the existing Kachinco deployment catalog.
   Preserve upload/preview/query/history tools, credentials, transport and namespace.
3. Restart through the normal Hub owner workflow, reconnect and inspect catalog
   parity. An old desktop's Edit schema must fail parity against the new edit_batch.
   This source change does not deploy a catalog or change desktop permissions.
4. Through the external client, download an edited WAV and MP4, verify file
   digest/length and content, and check cancellation and stale revisions.

## Client flow

Read context and use the current `{input,guard}` envelope. Begin accepts sequence
and clip UUIDs, optional clip-relative decimal-string start/duration and quality
Full/Half/Quarter. It returns a job ID immediately; poll status until ready. WAV
is PCM16 stereo 48kHz; MP4 is silent H.264 on an opaque black sequence canvas.
Only the selected clip contributes, including trim, gain/curves, transforms and
speed. Disabled/muted results are black/silent unless inspectDisabled is explicit;
that flag does not override gain/opacity curves or change project state.

At most 30 seconds / 64 MiB per result. Read in chunks <=131072 decoded bytes;
verify each chunkSha256 and assemble offsets, then verify metadata.sizeBytes and
sha256 and save fileName. Cancel releases the job; ten idle minutes expire it.
Changes to project revision/document/source invalidate bytes. Lost responses are
never automatically replayed by Hub. Audio input or analysis after download
belongs to the client/model and is not implied by successful transfer.

Automated Hub tests cover producer schema parity, ReadOnly downloads / Edit denial,
old-schema rejection, offline discovery and actual 128KiB bytes plus errors through
an official HTTP MCP client and reverse WebSocket. These are boundary tests with a
controlled desktop peer; live Mango/tunnel acceptance remains separate.

## KineticTypo editable text (Kachinco #111)

The matched producer adds SetTextComposition to edit_batch. It replaces an embedded native text composition through the ordinary revision-checked command/history. No file/host lifecycle grant, renderer or project authority is added to Hub. Replace the existing edit_batch descriptor from the inactive example when adopting the matching Kachinco build; preserve every unrelated tool/connection setting. KineticTypo standalone publishes its own separate product descriptor (flamoris.kinetai) through the standard desktop connection UI. No live catalog/deployment is changed by this source update.
