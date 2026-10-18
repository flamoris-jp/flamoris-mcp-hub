# Kachinco caption style catalog

Companion to flamoris-jp/flamoris-kachinco#95 and ADR 0022.

The existing `edit_batch` descriptor now includes `PatchCaptionStyles` and
`SetCaptionStyle`. Both inactive clips/titles templates and the producer fixture
contain the same complete replacement descriptor. Tool names/count and routing
are unchanged. Kachinco remains the sole caption, style, revision/history,
font-fallback and rendering authority.

`PatchCaptionStyles` takes explicit caption IDs and a partial patch: omitted/null
fields preserve each caption's current effective value. A font-only patch must
not overwrite individual colors/positions. `SetCaptionStyle` replaces one full
style, or resets to the inherited default with null. Existing runtime/document/
expectedRevision guards and Edit permissions apply.

After both PRs are reviewed, update the desktop and replace **only** edit_batch
in the existing deployed Kachinco catalog using this producer descriptor.
Preserve every other tool, namespace, credentials and connection setting.
Reconnect the updated desktop, verify its actual descriptor and edit permission,
then refresh client tools. Old desktop/new catalog (or new desktop/old catalog)
will be rejected by the existing descriptor-mismatch checks; update them together.

Source changes do not deploy or restart the production Hub. Real external-client
acceptance remains a separate check: patch two captions, get_project, undo/redo,
and obtain preview frames after the desktop/catalog rollout.

Validation: the fixture is exported from the actual MCP Core producer descriptor;
`python -m unittest discover -s tests -p test_kachinco_caption_styles.py` compares
both templates, partial/null schemas, guards and retained existing commands.
