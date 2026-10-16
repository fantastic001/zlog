from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

RunTree = Mapping[str, Mapping[int, str]]
RunTreeBuilder = Callable[[RunTree], Path]


@pytest.fixture
def build_run_tree(tmp_path: Path) -> RunTreeBuilder:
    def build(tree: RunTree) -> Path:
        root = tmp_path / "runs"
        root.mkdir(exist_ok=True)
        for directory_name, iterations in tree.items():
            run_directory = root / directory_name
            run_directory.mkdir(exist_ok=True)
            for iteration, content in iterations.items():
                (run_directory / f"{iteration}.out").write_text(content)
        return root

    return build


@pytest.fixture
def spec_file(tmp_path: Path) -> Path:
    path = tmp_path / "spec.yaml"
    path.write_text(
        "groups: [optimizer, size]\n"
        "patterns:\n"
        "  - regex: 'accuracy\\:\\s(\\f)'\n"
        "    names: [accuracy]\n"
        "  - regex: 'loss=(\\f)'\n"
        "    names: [loss]\n"
    )
    return path
