from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ToolConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    description: str = ""
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )


class UpstreamConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    namespace: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    enabled: bool = True
    transport: Literal["streamable-http"] = "streamable-http"
    url: HttpUrl
    api_key_env: str | None = None
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer "
    tools: list[ToolConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_config(self) -> "UpstreamConfig":
        if self.api_key_env is not None and not self.api_key_env.strip():
            raise ValueError("api_key_env must be a non-empty environment variable name")

        seen: set[str] = set()
        for tool in self.tools:
            if tool.name in seen:
                raise ValueError(f"duplicate tool name in {self.id}: {tool.name}")
            seen.add(tool.name)
        return self

    def headers(self) -> dict[str, str]:
        if self.api_key_env is None:
            return {}

        value = os.environ.get(self.api_key_env)
        if not value:
            raise ValueError(
                f"required environment variable {self.api_key_env!r} is not set "
                f"for upstream {self.id!r}"
            )
        return {self.api_key_header: f"{self.api_key_prefix}{value}"}


class Catalog:
    def __init__(self, configs: list[UpstreamConfig]) -> None:
        self.configs = {config.id: config for config in configs}
        self.tools: dict[str, tuple[UpstreamConfig, ToolConfig]] = {}

        for config in configs:
            for tool in config.tools:
                public_name = f"{config.namespace}.{tool.name}"
                if public_name in self.tools:
                    raise ValueError(f"duplicate public tool name: {public_name}")
                self.tools[public_name] = (config, tool)


def load_upstreams(config_dir: Path) -> list[UpstreamConfig]:
    if not config_dir.exists():
        raise FileNotFoundError(f"config directory does not exist: {config_dir}")

    configs: list[UpstreamConfig] = []
    ids: set[str] = set()
    namespaces: set[str] = set()

    for path in sorted(config_dir.glob("*.yaml")):
        if path.name.startswith("_"):
            continue

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            continue

        config = UpstreamConfig.model_validate(raw)
        if not config.enabled:
            continue

        if config.id in ids:
            raise ValueError(f"duplicate upstream id: {config.id}")
        if config.namespace in namespaces:
            raise ValueError(f"duplicate upstream namespace: {config.namespace}")

        ids.add(config.id)
        namespaces.add(config.namespace)
        configs.append(config)

    return configs


def config_dir() -> Path:
    return Path(os.environ.get("FLAMORIS_MCP_HUB_CONFIG_DIR", "config/mcps"))


def load_catalog() -> Catalog:
    return Catalog(load_upstreams(config_dir()))
