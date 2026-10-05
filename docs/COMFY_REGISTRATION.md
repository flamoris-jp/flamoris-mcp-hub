# Matched Generation reference-image catalog

Controller #6 and Generation MCP #72 add `generation.comfy.register` and
`generation.comfy.get`. The static catalog has 25 tools and its schemas and
annotations match the real facade export. The Hub forwards opaque bounded
arguments/results; Controller owns graph validation, definitions, images and jobs.
The existing namespace, lazy connection, provenance and no-replay policy remain.

Use the new catalog only with the matching Generation facade and Controller
artifact. An older 23-tool facade is deliberately blocked by the complete
catalog-parity check before forwarding even an unchanged mutation. Updating
source examples does not change any deployed Hub catalog or credential.

Registration accepts checkpoint core txt2img/img2img API graphs; reference images
are managed init images. It does not permit arbitrary graphs/custom nodes or
claim IPAdapter/ControlNet semantics. Follow the owning Controller/facade contract
for uploads, building, submitting and retrieving generated assets. Registration
is static validation, with live acceptance pending.
