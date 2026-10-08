from pathlib import Path

from flamoris_update_core.resources import TreeBinding, TreeResource

from flamoris_mcp_hub.updater import inspect_domain


def tree(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    return TreeResource(TreeBinding(id=name, path=str(path), max_files=20, max_bytes=128 * 1024))


def test_owner_catalogue_needs_no_upstream_and_is_read_only(tmp_path):
    resource = tree(tmp_path, "configuration")
    template = Path(__file__).parents[1] / "config/mcps/_generation.example.yaml"
    (resource.root / "generation.yaml").write_bytes(template.read_bytes())
    before = resource.inventory()
    state = inspect_domain(None, {"configuration": resource})
    assert not state.active_work and not state.unknown_work
    assert resource.inventory() == before
