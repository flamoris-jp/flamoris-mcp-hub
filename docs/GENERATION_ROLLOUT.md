# Generation / Hub paired rollout acceptance

The source catalogs already cover legacy Workflow readiness (22 tools) and the
optional Image v3 profile (27 tools). Updating a tracked underscore template does
not update the deployment-local `generation.yaml` or the running Hub process.
Generation remains the workflow, verification, readiness, JobStore and asset
authority. Hub supplies schema-compatible discovery and forwarding only.

## Record the pair before changing it

Use the deployment's private operations records to capture the actually deployed
Generation and Hub revisions, Generation's v3 enablement, and the mounted runtime
catalog. Save the current `config/mcps/generation.yaml` outside the checkout in the
deployment's private backup directory. Retain the existing JobStore and asset
volumes. A rollback target must include JobStore uncertain-submit hardening;
rolling back to code that releases an ambiguous submission's reservation is not a
safe recovery plan.

Choose `_generation.example.yaml` for the legacy profile, or
`_generation-v3.example.yaml` when the deployed Generation has
`FLAMORIS_WORKFLOW_V3_ENABLED=true`. The v3 catalog requires the compatible enabled
upstream. Update the two services in one maintenance window and admit no new
generation or verification work while the pair is being changed.

## Refresh the runtime catalog without replacing deployment settings

From the Hub checkout, after backing up the runtime file, replace only its tool
definitions. This preserves the URL, credential environment references, namespace,
enabled flag and any external provenance configuration:

```sh
python - <<'PY'
from pathlib import Path
import yaml

runtime_path = Path("config/mcps/generation.yaml")
template_path = Path("config/mcps/_generation.example.yaml")
# Use _generation-v3.example.yaml only for the enabled v3 deployment profile.
runtime = yaml.safe_load(runtime_path.read_text())
template = yaml.safe_load(template_path.read_text())
if runtime["id"] != template["id"] or runtime["namespace"] != template["namespace"]:
    raise SystemExit("Review the deployment route identity before updating")
runtime["tools"] = template["tools"]
runtime_path.write_text(yaml.safe_dump(runtime, sort_keys=False))
PY
```

Deploy the reviewed Generation revision and Hub revision using their existing
deployment procedures. Restart the Hub after refreshing its mounted YAML. For
the supplied Compose deployment, that command is `docker compose restart
mcp-hub`. Changes to Compose environment values or the container image require
the documented recreation/build procedure instead. Hub startup remains offline;
it never registers a workflow, activates a runtime or runs verification.

HTTP forwarding now compares the reviewed tool annotations as well
as input schemas before dispatch. Missing annotation hints use the same MCP
conservative defaults as legacy catalogs; changed/invalid annotations block calls
until the reviewed catalog matches again. Refresh other deployment-local HTTP
catalogs from the matching upstream export when upgrading this Hub revision. The
GPU Node Manager template now includes its exported `idempotentHint` on activate
and stop. For read-only observations, its omitted `destructiveHint` conservatively
defaults to true; MCP ignores that hint when `readOnlyHint` is true.

## Obtain a fresh pair receipt

Run this explicit read-only check from the deployed Hub image. Set the endpoint
variable to the deployment's Hub MCP endpoint before running it. The mounted
`.env` supplies the existing Hub token and any referenced upstream credentials;
the checker does not print them:

```sh
docker compose exec -T mcp-hub python -m flamoris_mcp_hub.catalog_check \
  /app/config/mcps/generation.yaml \
  --env-file /app/.env \
  --hub-url "$FLAMORIS_HUB_MCP_URL" > generation-hub-catalog-receipt.json
```

The check opens a new MCP session to Generation and a separate new session to
Hub, initializes them, and requests `tools/list` once from each. It makes no
`tools/call`, verification, submission, runtime activation or readiness mutation.
It compares every tool name, input schema and annotation against the runtime
YAML. The Hub comparison includes the selected namespace only, so unrelated
upstreams may remain configured. The direct upstream comparison requires the
whole selected profile: an additional v3 surface is reported when checking a
legacy catalog, even though ordinary legacy forwarding remains compatible.

Success exits zero with `status: matched` and matching contract digests for the
configured, direct and Hub catalogs. Mismatch/error exits one. Pagination,
duplicate names, invalid metadata, oversized catalogs and deadlines fail closed.
The total deadline defaults to 30 seconds (`--timeout` accepts 1-300); catalog and
contract and response sizes are limited to 1 MiB and discovery to 512 tools.
The HTTP checker requests identity encoding and rejects compressed responses
before decompression; its SSE event limit is also 1 MiB. SDK logging is suppressed
only during this standalone command to keep malformed payloads off stderr.
Receipts contain
digests, counts and changed tool names, without endpoints, filesystem paths,
credentials, schema bodies or provider payloads. Store receipts in the deployment
private operations records alongside the deployed revision evidence.

Catalog parity proves compatibility at the time of these fresh sessions. It does
not certify provider availability, a real JANKU graph, successful inference,
workflow readiness, user delegation or production completion. Complete the
Generation-owned real-runtime verification and exact-identity ready check after
the pair receipt succeeds; never replay an ambiguous call automatically.

## Roll back and verify the rollback

If acceptance fails, stop admitting new work, inspect live JobStore state through
Generation, and retain any unresolved submission's reservation. Restore the
saved deployment-local runtime YAML and the recorded compatible service pair
using the normal deployment procedures. Keep their durable data volumes. Do not
cancel or resubmit uncertain jobs merely to make acceptance pass.

Restart/recreate the restored Hub as required, then run the same checker into a
separate `generation-hub-rollback-receipt.json`. A rollback receipt must also exit
zero for the restored selected profile. Attach the recorded restored revisions
and both receipts to the private operations record. Report failed compatibility
or unavailable runtime evidence explicitly; do not mark #26's live pair and
rollback gates complete solely because source tests or a catalog receipt pass.
