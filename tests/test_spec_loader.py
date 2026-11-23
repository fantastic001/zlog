from pathlib import Path

import pytest

from tests.conftest import EXAMPLES_DIRECTORY, FileWriter, create_rule_factory
from zlog.errors import SpecError
from zlog.spec_loader import (
    SpecLoader,
    describe_decode_hints,
    find_duplicate_keys,
)
from zlog.spec_parser import SpecParser

SIMPLE_YAML = "matches:\n  - pattern: 'x=(\\d+)'\n    record: {x: 1}\n"


def create_loader(max_spec_bytes: int = 1024 * 1024) -> SpecLoader:
    return SpecLoader(
        SpecParser(create_rule_factory()), max_spec_bytes=max_spec_bytes
    )


@pytest.mark.parametrize("name", ["spec.yaml", "spec.yml", "spec.txt"])
def test_loads_yaml(write_file: FileWriter, name: str) -> None:
    spec = create_loader().load(write_file(name, SIMPLE_YAML))

    assert spec.record_names == ("x",)


def test_loads_json(write_file: FileWriter) -> None:
    path = write_file(
        "spec.json", '{"matches": [{"pattern": "a", "record": {"x": 0}}]}'
    )

    assert create_loader().load(path).record_names == ("x",)


def test_loads_the_bundled_example() -> None:
    spec = create_loader().load(EXAMPLES_DIRECTORY / "train.yaml")

    assert spec.context_names == (
        "run",
        "run_index",
        "epoch",
        "samples",
        "warnings",
    )


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("spec.yaml", "matches: [{pattern: a, pattern: b}]"),
        ("spec.yaml", "matches:\n  - pattern: a\n    record: {x: 0, x: 1}\n"),
        ("spec.json", '{"matches": [{"pattern": "a", "pattern": "b"}]}'),
    ],
)
def test_duplicate_keys_are_rejected(
    write_file: FileWriter, name: str, content: str
) -> None:
    with pytest.raises(SpecError, match="duplicate"):
        create_loader().load(write_file(name, content))


def test_yaml_merge_keys_may_be_overridden(write_file: FileWriter) -> None:
    content = (
        "base: &base {pattern: a, record: {x: 0}}\n"
        "matches:\n  - <<: *base\n    pattern: b\n"
    )

    with pytest.raises(SpecError, match="unknown keys base"):
        create_loader().load(write_file("spec.yaml", content))


def test_unhashable_yaml_keys_are_rejected(write_file: FileWriter) -> None:
    with pytest.raises(SpecError, match="unhashable"):
        create_loader().load(write_file("spec.yaml", "? [a]\n: 1\n"))


def test_unquoted_at_sign_gets_a_hint(write_file: FileWriter) -> None:
    path = write_file(
        "spec.yaml", "matches:\n  - pattern: a\n    context: {@w: 1}\n"
    )

    with pytest.raises(SpecError, match="hint: quote names that start with @"):
        create_loader().load(path)


def test_oversized_spec_is_rejected(write_file: FileWriter) -> None:
    with pytest.raises(SpecError, match="limit is 10"):
        create_loader(max_spec_bytes=10).load(
            write_file("spec.yaml", SIMPLE_YAML)
        )


def test_missing_spec_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="cannot read"):
        create_loader().load(tmp_path / "absent.yaml")


def test_find_duplicate_keys_ignores_unhashable_keys() -> None:
    assert find_duplicate_keys(["a", ["x"], "a", ["x"], 1]) == ["a"]


def test_unquoted_leading_percent_gets_a_hint(write_file: FileWriter) -> None:
    path = write_file("spec.yaml", "matches:\n  - pattern: %d items\n")

    with pytest.raises(SpecError, match="hint: quote patterns that start"):
        create_loader().load(path)


def test_describe_decode_hints() -> None:
    assert describe_decode_hints("no hint here") == ""
    assert "backtick" in describe_decode_hints("found character '`'")
    assert "'%d items'" in describe_decode_hints("found character '%'")
