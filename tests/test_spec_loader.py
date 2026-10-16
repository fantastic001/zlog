from pathlib import Path

import pytest

from zlog.domain import PatternSpec
from zlog.errors import SpecError
from zlog.spec_loader import SpecLoader, SpecParser


def load_spec_text(tmp_path: Path, name: str, content: str) -> object:
    path = tmp_path / name
    path.write_text(content)
    return SpecLoader(SpecParser()).load(path)


def test_loads_yaml_spec(spec_file: Path) -> None:
    spec = SpecLoader(SpecParser()).load(spec_file)

    assert spec.groups == ("optimizer", "size")
    assert spec.patterns[0] == PatternSpec(r"accuracy\:\s(\f)", ("accuracy",))
    assert dict(spec.macros) == {}
    assert spec.iteration_separator is None


def test_loads_iteration_separator(tmp_path: Path) -> None:
    spec = load_spec_text(
        tmp_path, "spec.yaml", "iteration_separator: '^=+ run \\d+ =+$'\n"
    )

    assert spec.iteration_separator == r"^=+ run \d+ =+$"  # type: ignore[attr-defined]


def test_loads_json_spec_with_macros(tmp_path: Path) -> None:
    spec = load_spec_text(
        tmp_path,
        "spec.json",
        '{"groups": ["a"], "patterns": [], "macros": {"\\\\i": "\\\\d+"}}',
    )

    assert dict(spec.macros) == {r"\i": r"\d+"}  # type: ignore[attr-defined]


def test_unknown_suffix_falls_back_to_yaml(tmp_path: Path) -> None:
    spec = load_spec_text(tmp_path, "spec.txt", "groups: [a]\n")

    assert spec.groups == ("a",)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "content",
    [
        "- just\n- a list\n",
        "",
        "groups: a\n",
        "groups: [1, 2]\n",
        "patterns: {}\n",
        "patterns: [{regex: '', names: [a]}]\n",
        "patterns: [{regex: 'x'}]\n",
        "patterns: [{regex: 'x', names: [1]}]\n",
        "macros: [a]\n",
        "iteration_separator: ''\n",
        "iteration_separator: [a]\n",
        "groups: [a\n",
    ],
)
def test_invalid_specs_are_rejected(tmp_path: Path, content: str) -> None:
    with pytest.raises(SpecError):
        load_spec_text(tmp_path, "spec.yaml", content)


def test_missing_spec_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="cannot read"):
        SpecLoader(SpecParser()).load(tmp_path / "missing.yaml")


def test_oversized_spec_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text("groups: [a]\n")

    with pytest.raises(SpecError, match="limit"):
        SpecLoader(SpecParser(), max_spec_bytes=4).load(path)
