# Kachinco timed editing notes catalog

Companion to Kachinco ADR 0032. The producer adds `EditNote` to AddTrack.kind;
notes reuse AddCaption/UpdateCaption/DeleteCaption and get_project. No tool,
namespace, routing, permission, authentication or connection lifecycle changes.
Kachinco owns native persistence, validation, history and editor-only display;
Hub does not interpret note text or turn it into editing commands.

The clip producer fixture and both inactive examples now pin the same complete
edit_batch descriptor as the producer. Existing caption styles and media tools
remain intact. Static schema tests cover both example catalogs.

After review, upgrade each Kachinco producer first and replace edit_batch by name
in its existing deployed catalog (Windows and/or kachinco_lime as applicable).
Preserve all other tools and connection settings. Refresh client tools after
verifying descriptor agreement. Loading an old producer against the new pinned
descriptor correctly fails agreement; this source change does not deploy either
application or modify a running catalog. v9 project files containing note tracks
require the new producer; ordinary projects retain their conditional old schema.
