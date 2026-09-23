from __future__ import annotations

import os
from pathlib import Path

from .config import load_upstreams
from .upstream import UpstreamRegistry


def config_dir() -> Path:
    return Path(os.environ.get("FLAMORIS_MCP_HUB_CONFIG_DIR", "config/mcps"))


async def start_registry() -> UpstreamRegistry:
    registry = UpstreamRegistry()
    await registry.__aenter__()
    try:
        await registry.connect_all(load_upstreams(config_dir()))
    except Exception:
        await registry.__aexit__(None, None, None)
        raise
    return registry
