"""Validate the local catalogue without connecting to upstream services."""

from flamoris_update_core.domain import check_resources, configuration_revision
from flamoris_update_core.owner import ApplicationOwner, DomainState
from flamoris_update_core.owner_cli import serve

from .config import Catalog, load_upstreams

SCHEMAS = {"configuration": "hub-catalog-1"}


def inspect_domain(config, resources):
    check_resources(resources, ["configuration"])
    Catalog(load_upstreams(resources["configuration"].root))
    return DomainState(
        schemas=SCHEMAS,
        active_work=False,
        unknown_work=False,
        configuration_digest=configuration_revision(resources),
    )


def factory(config):
    return ApplicationOwner(config, "flamoris-mcp-hub", "1.0.2", inspect_domain)


def main():
    serve(factory)
