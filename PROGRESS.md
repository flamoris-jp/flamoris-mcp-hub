# Progress

## Updater adoption — 2026-10-08

Entry release target: **1.0.0**. Independent mTLS Owner and durable admission
source are implemented; source review/fixes and CI integration are complete.
PR [#41](https://github.com/flamoris-jp/flamoris-mcp-hub/pull/41) is prepared for human
review. Release publication and real-host adoption remain pending.

## Verification

Local full suite: **160 passed**. All seven application wheel-from-sdist builds and
declared Owner entrypoint/module checks passed. The operator made Updater public,
resolving the initial SDK download 404. That adoption checkpoint used SDK source
pinned to
`d9f010a92ff6e8a1e7a3b7fad8817850bdfb72cd` (Updater PR #6).

[CI run 37766172019](https://github.com/flamoris-jp/flamoris-mcp-hub/actions/runs/37766172019):
160 passed; lint/format succeeded. Owner validation loads the local catalogue without connecting to upstream providers; forwarding uses durable admission.
These results precede this progress-only commit; package/source dependency pins
are unchanged. Cross-repository findings and exact evidence are recorded in
Updater [ADOPTION_REVIEW.md](https://github.com/flamoris-jp/flamoris-updater/blob/feat/application-entry-v1/docs/ADOPTION_REVIEW.md).

## Operational boundary

The entry path preserves already current application schemas and retained data;
unsupported schemas/resources and unknown outcomes remain blocked. No data/schema
initialization, private profile/trust provisioning, release publication, live
provider call, real-host update, enrollment or automatic merge occurred. Native
deployment overlays and matched dependencies remain deployment-owned.
See [Updater contract](docs/UPDATER.md).

## Pre-deployment dependency refresh

The SDK pin now targets merged Updater correction
`797d6f4e7bd4089e7c162fa50c10a0afae68370a`. Review and CI at this exact
revision are pending. No runtime, trust, release, data or host state was changed.
