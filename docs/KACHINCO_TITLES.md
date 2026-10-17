# Kachinco creation workflow catalog

Companion to flamoris-jp/flamoris-kachinco#92 (Issues #84–#91).
Kachinco owns media, titles, rendering, files, revisions and Undo/Redo. Hub only
forwards the reviewed descriptors/results. No routing/runtime changes.

- Replace the existing edit_batch schema from the reviewed template. New typed
  commands: UnregisterMedia, SetTitleImage, ReserveTitleFrame, ReleaseTitleFrame,
  ApplyCrossfade. Their arguments remain under input with the existing guard.
- Add title_image_from_frame (Edit transaction) and title_image (ReadOnly image
  query). The producer owns canonical ticks, image capture/export and cleanup.
- _kachinco-clips.example.yaml also has the replacement edit_batch schema so it
  cannot accidentally restore an older editing contract during a later update.
- Title fixtures match Kachinco's TitleImageTests.TitleCatalogMatchesActualProducerDescriptor;
  clip fixtures match ClipDownloadTests.CatalogMatchesProducerWireDescriptor.
  Keep both repositories aligned with the accepted producer commit.

## Rollout after review

Upgrade the desktop producer first; merge tools by name into the existing
deployed Kachinco catalog. Preserve authentication, connector token and desktop
connection settings and every other tool. Do not load the inactive examples
together as separate upstreams. Reconnect Kachinco, verify the actual producer
descriptor and permission, then refresh ChatGPT tools. The complete previously
16-tool catalog gains two title tools (18 total when all prior tools are enabled).

Deploying this repository alone does not update a running catalog or desktop.
No production changes are implied by this source-only companion PR.
