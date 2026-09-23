from __future__ import annotations

from .config import Catalog, load_catalog
from .upstream import UpstreamRegistry


def start_registry() -> tuple[Catalog, UpstreamRegistry]:
    # Startup is catalog-only by design. Loading configuration must not perform
    # network I/O or require any upstream MCP server to be running.
    catalog = load_catalog()
    return catalog, UpstreamRegistry(catalog)
