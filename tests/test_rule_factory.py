from typing import cast

import pytest

from tests.conftest import create_rule_factory
from zlog.errors import SpecError
from zlog.options import ResetScope
from zlog.rule_factory import find_duplicates
from zlog.rules import Binding, MatchRule, ResetSelection
from zlog.value_sources import ConstantSource, GroupSource
from zlog.variable_names import VariableName

NO_RESET = ResetSelection()


def test_create_parses_names_and_keeps_sources() -> None:
    rule = create_rule_factory().create(
        "p",
        ResetSelection(ResetScope.LISTED, ("a",)),
        (("+a", GroupSource(1)), ("@b", ConstantSource("x"))),
        (("c", GroupSource("name")),),
    )

    assert rule == MatchRule(
        "p",
        ResetSelection(ResetScope.LISTED, ("a",)),
        (
            Binding(VariableName("a", "+"), GroupSource(1)),
            Binding(VariableName("b", "@"), ConstantSource("x")),
        ),
        (Binding(VariableName("c"), GroupSource("name")),),
    )


@pytest.mark.parametrize("pattern", ["", 3])
def test_pattern_must_be_a_non_empty_string(pattern: object) -> None:
    with pytest.raises(SpecError, match="non-empty pattern"):
        create_rule_factory().create(cast("str", pattern), NO_RESET, (), ())


def test_record_variables_take_no_prefix() -> None:
    with pytest.raises(SpecError, match=r"take no prefix, got \+a"):
        create_rule_factory().create(
            "p", NO_RESET, (), (("+a", GroupSource(1)),)
        )


@pytest.mark.parametrize(
    ("context", "record"),
    [
        ((("a", GroupSource(1)), ("+a", GroupSource(2))), ()),
        ((), (("a", GroupSource(1)), ("a", GroupSource(2)))),
    ],
)
def test_duplicate_names_in_one_section_are_rejected(
    context: tuple[tuple[str, GroupSource], ...],
    record: tuple[tuple[str, GroupSource], ...],
) -> None:
    with pytest.raises(SpecError, match="duplicate"):
        create_rule_factory().create("p", NO_RESET, context, record)


@pytest.mark.parametrize(
    "reset",
    [
        ResetSelection(ResetScope.LISTED, ()),
        ResetSelection(ResetScope.ALL, ("a",)),
        ResetSelection(ResetScope.NONE, ("a",)),
        ResetSelection(ResetScope.LISTED, ("1bad",)),
        ResetSelection(ResetScope.LISTED, ("a", "a")),
    ],
)
def test_invalid_resets_are_rejected(reset: ResetSelection) -> None:
    with pytest.raises(SpecError, match="invalid reset"):
        create_rule_factory().create("p", reset, (), ())


def test_find_duplicates() -> None:
    assert find_duplicates(["b", "a", "b", "c", "a"]) == ["a", "b"]
    assert find_duplicates([]) == []
