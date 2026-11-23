from decimal import Decimal
from functools import reduce

import pytest

from zlog.config import Settings
from zlog.context_updates import (
    ADD_PREFIX,
    BUILTIN_CONTEXT_UPDATES,
    CONCATENATE_PREFIX,
    ConcatenateUpdate,
    ContextUpdate,
    NumericAddUpdate,
    ReplaceUpdate,
    build_context_updates,
)
from zlog.errors import InvalidValueError
from zlog.variable_names import REPLACE_PREFIX


def fold_updates(update: ContextUpdate, values: list[str]) -> str | None:
    return reduce(update.apply, values, None)


def test_replace_keeps_the_latest_value() -> None:
    assert ReplaceUpdate().apply("old", "new") == "new"
    assert ReplaceUpdate().apply(None, "") == ""


@pytest.mark.parametrize(
    ("previous", "value", "expected"),
    [
        (None, "5", "5"),
        ("3", "4", "7"),
        ("0.1", "0.2", "0.3"),
        ("0.90", "0.10", "1.00"),
        (None, "1e3", "1000"),
        ("-2.5", "+1", "-1.5"),
        ("nan", "1", "NaN"),
        ("inf", "1", "Infinity"),
    ],
)
def test_numeric_add(previous: str | None, value: str, expected: str) -> None:
    assert NumericAddUpdate(50).apply(previous, value) == expected


@pytest.mark.parametrize(
    ("previous", "value"),
    [
        ("5", "abc"),
        ("abc", "5"),
        ("5", ""),
        ("inf", "-inf"),
        ("1", "snan"),
        ("1_000", "1"),
    ],
)
def test_numeric_add_rejects_invalid_operands(
    previous: str, value: str
) -> None:
    with pytest.raises(InvalidValueError, match="cannot add"):
        NumericAddUpdate(50).apply(previous, value)


def test_numeric_add_fails_instead_of_rounding() -> None:
    with pytest.raises(InvalidValueError, match="Inexact at precision 5"):
        NumericAddUpdate(5).apply("123456", "1")


def test_numeric_add_rejects_non_positive_precision() -> None:
    with pytest.raises(ValueError, match="precision"):
        NumericAddUpdate(0)


@pytest.mark.parametrize(
    "values",
    [
        ["1"],
        ["1", "2", "3"],
        ["0.1"] * 10,
        ["1e20", "1", "-1e20"],
        ["-0.5", "0.25", "3"],
    ],
)
def test_lemma_sum_folding_add_equals_exact_sum(values: list[str]) -> None:
    folded = fold_updates(NumericAddUpdate(50), values)

    assert folded is not None
    assert Decimal(folded) == sum(map(Decimal, values), Decimal(0))


@pytest.mark.parametrize(
    ("values", "separator"),
    [(["a"], "|"), (["a", "b", "c"], "|"), (["x", "", "y"], ""), (["p"], "")],
)
def test_lemma_concatenation_equals_join(
    values: list[str], separator: str
) -> None:
    assert fold_updates(ConcatenateUpdate(separator), values) == (
        separator.join(values)
    )


def test_build_context_updates_reads_settings() -> None:
    settings = Settings(concat_separator=";", decimal_precision=3)

    updates = build_context_updates(BUILTIN_CONTEXT_UPDATES, settings)

    assert set(updates) == {REPLACE_PREFIX, ADD_PREFIX, CONCATENATE_PREFIX}
    assert updates[CONCATENATE_PREFIX].apply("a", "b") == "a;b"
    with pytest.raises(InvalidValueError):
        updates[ADD_PREFIX].apply("999", "2")
