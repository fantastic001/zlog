import pytest

from zlog.errors import SpecError
from zlog.variable_names import (
    VariableName,
    is_valid_variable_name,
    parse_variable_name,
)

PREFIXES = ("", "+", "@")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("epoch", VariableName("epoch", "")),
        ("+samples", VariableName("samples", "+")),
        ("@warnings", VariableName("warnings", "@")),
        ("loss.mean", VariableName("loss.mean", "")),
        ("_private2", VariableName("_private2", "")),
    ],
)
def test_parse_variable_name(raw: str, expected: VariableName) -> None:
    assert parse_variable_name(raw, PREFIXES) == expected


def test_longest_prefix_wins() -> None:
    assert parse_variable_name("++x", ("", "+", "++")) == VariableName(
        "x", "++"
    )


def test_missing_prefixes_default_to_replace() -> None:
    assert parse_variable_name("x", ()) == VariableName("x", "")


@pytest.mark.parametrize("raw", ["", "+", "@", "1abc", "a b", "+@x", "a=b"])
def test_invalid_variable_names_are_rejected(raw: str) -> None:
    with pytest.raises(SpecError, match="invalid variable name"):
        parse_variable_name(raw, PREFIXES)


def test_is_valid_variable_name() -> None:
    assert is_valid_variable_name("path")
    assert not is_valid_variable_name("-path")
