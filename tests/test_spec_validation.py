import pytest

from tests.conftest import parse_yaml_spec
from zlog.errors import SpecError
from zlog.rules import ExtractionSpec
from zlog.spec_validation import SpecConsistencyChecker


def test_consistent_spec_passes() -> None:
    spec = parse_yaml_spec(
        "matches:\n"
        "  - {pattern: a, reset: [x], context: {x: 0}, record: {y: 0}}\n"
        "  - {pattern: b, reset: all}\n"
    )

    SpecConsistencyChecker("path").check(spec)


@pytest.mark.parametrize(
    ("spec_text", "message"),
    [
        (
            "matches: [{pattern: a, context: {x: 0}, record: {x: 0}}]",
            "'x' is both a context and a record variable",
        ),
        (
            "matches: [{pattern: a, record: {path: 0}}]",
            "'path' is reserved",
        ),
        (
            "matches: [{pattern: a, reset: [ghost], context: {x: 0}}]",
            "resets undeclared context variable 'ghost'",
        ),
    ],
)
def test_inconsistent_specs_are_rejected(spec_text: str, message: str) -> None:
    with pytest.raises(SpecError, match=message):
        SpecConsistencyChecker("path").check(parse_yaml_spec(spec_text))


def test_empty_spec_is_rejected() -> None:
    with pytest.raises(SpecError, match="no match rules"):
        SpecConsistencyChecker("path").check(ExtractionSpec())


def test_all_violations_are_reported_together() -> None:
    spec = parse_yaml_spec(
        "matches:\n"
        "  - {pattern: a, reset: [ghost], context: {x: 0}, record: {x: 0}}\n"
    )

    with pytest.raises(SpecError, match="both.*; rule .*'ghost'"):
        SpecConsistencyChecker("path").check(spec)


def test_reserved_name_follows_the_configured_path_column() -> None:
    spec = parse_yaml_spec("matches: [{pattern: a, record: {path: 0}}]")

    SpecConsistencyChecker("source").check(spec)
