from pathlib import Path

import pytest

from flamoris_mcp_hub.config import load_upstreams


def test_loads_one_config_and_reads_secret_from_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TEST_MCP_KEY", "secret")
    (tmp_path / "test.yaml").write_text(
        """
id: test
namespace: test
enabled: true
transport: streamable-http
url: https://example.com/mcp
api_key_env: TEST_MCP_KEY
api_key_header: Authorization
api_key_prefix: "Bearer "
""".strip(),
        encoding="utf-8",
    )

    configs = load_upstreams(tmp_path)

    assert len(configs) == 1
    assert configs[0].headers() == {"Authorization": "Bearer secret"}


def test_disabled_config_is_ignored(tmp_path: Path):
    (tmp_path / "disabled.yaml").write_text(
        """
id: disabled
namespace: disabled
enabled: false
transport: streamable-http
url: https://example.com/mcp
""".strip(),
        encoding="utf-8",
    )

    assert load_upstreams(tmp_path) == []


def test_duplicate_namespace_is_rejected(tmp_path: Path):
    for name in ("one", "two"):
        (tmp_path / f"{name}.yaml").write_text(
            f"""
id: {name}
namespace: same
enabled: true
transport: streamable-http
url: https://example.com/{name}
""".strip(),
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="duplicate upstream namespace"):
        load_upstreams(tmp_path)
