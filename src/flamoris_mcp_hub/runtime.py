from __future__ import annotations

from flamoris_update_core.admission import register_boot

from .config import Catalog, load_catalog
from .upstream import UpstreamRegistry


def start_registry() -> tuple[Catalog, UpstreamRegistry]:
    # Startup is catalog-only by design. Loading configuration must not perform
    # network I/O or require any upstream MCP server to be running.
    register_boot("flamoris-mcp-hub")
    catalog = load_catalog()
    return catalog, UpstreamRegistry(catalog)
