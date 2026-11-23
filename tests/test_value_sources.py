import re

import pytest

from zlog.errors import SpecError
from zlog.value_sources import (
    ConstantSource,
    GroupSource,
    UnnamedGroupSource,
    list_unnamed_groups,
)

PATTERN = re.compile(r"epoch (?P<epoch>\d+)(?: loss=(\d+))?")


@pytest.mark.parametrize("reference", [0, 1, 2, "epoch"])
def test_existing_groups_validate(reference: int | str) -> None:
    GroupSource(reference).validate(PATTERN)


@pytest.mark.parametrize("reference", [3, -1, "loss", True])
def test_missing_groups_are_rejected(reference: int | str) -> None:
    with pytest.raises(SpecError, match="has no group"):
        GroupSource(reference).validate(PATTERN)


def test_group_source_resolves_captures() -> None:
    found = PATTERN.search("epoch 7 loss=3")
    assert found is not None

    assert GroupSource(0).resolve(found) == "epoch 7 loss=3"
    assert GroupSource("epoch").resolve(found) == "7"
    assert GroupSource(2).resolve(found) == "3"


def test_non_participating_group_resolves_to_none() -> None:
    found = PATTERN.search("epoch 7")
    assert found is not None

    assert GroupSource(2).resolve(found) is None


def test_constant_source_ignores_the_match() -> None:
    found = PATTERN.search("epoch 7")
    assert found is not None
    source = ConstantSource("start")

    source.validate(PATTERN)

    assert source.resolve(found) == "start"


@pytest.mark.parametrize(
    ("pattern", "unnamed"),
    [
        ("plain", ()),
        (r"(a)(?P<b>b)(c)", (1, 3)),
        (r"(?P<a>a)(?:b)(?P<c>c)", ()),
        (r"((a)(?P<b>b))", (1, 2)),
    ],
)
def test_list_unnamed_groups(pattern: str, unnamed: tuple[int, ...]) -> None:
    assert list_unnamed_groups(re.compile(pattern)) == unnamed


def test_unnamed_group_source_counts_only_unnamed_groups() -> None:
    found = PATTERN.search("epoch 7 loss=3")
    assert found is not None
    source = UnnamedGroupSource(1)

    source.validate(PATTERN)

    assert source.resolve(found) == "3"


def test_unnamed_group_source_rejects_missing_groups() -> None:
    with pytest.raises(SpecError, match="has 1 unnamed groups"):
        UnnamedGroupSource(2).validate(PATTERN)


@pytest.mark.parametrize("ordinal", [0, -1])
def test_unnamed_group_ordinal_must_be_positive(ordinal: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        UnnamedGroupSource(ordinal)
