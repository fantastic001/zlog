import pytest

from zlog.domain import MetricSummary, Summary
from zlog.errors import SpecError
from zlog.group_filter import (
    MATCH_ALL_FILTER,
    GroupFilterParser,
    parse_filter_label,
)

GROUPS = ("optimizer", "size")
ADAM_SMALL = (("optimizer", "adam"), ("size", "small"))
ADAM_LARGE = (("optimizer", "adam"), ("size", "large"))
SGD_SMALL = (("optimizer", "sgd"), ("size", "small"))
SGD_SIZE_ONE = (("optimizer", "sgd"), ("size", "1"))


def parse(raw_filter: object) -> object:
    return GroupFilterParser(GROUPS).parse(raw_filter, "filter")


@pytest.mark.parametrize(
    ("raw_filter", "matching"),
    [
        (None, {ADAM_SMALL, ADAM_LARGE, SGD_SMALL, SGD_SIZE_ONE}),
        ({}, {ADAM_SMALL, ADAM_LARGE, SGD_SMALL, SGD_SIZE_ONE}),
        ({"optimizer": "adam"}, {ADAM_SMALL, ADAM_LARGE}),
        ({"optimizer": "adam", "size": "small"}, {ADAM_SMALL}),
        ({"size": ["large", 1]}, {ADAM_LARGE, SGD_SIZE_ONE}),
        (
            [{"optimizer": "sgd"}, {"size": "large"}],
            {ADAM_LARGE, SGD_SMALL, SGD_SIZE_ONE},
        ),
    ],
)
def test_filter_matches_conjunctions_of_alternatives(
    raw_filter: object, matching: set[object]
) -> None:
    group_filter = GroupFilterParser(GROUPS).parse(raw_filter, "filter")
    groups = [ADAM_SMALL, ADAM_LARGE, SGD_SMALL, SGD_SIZE_ONE]

    assert {g for g in groups if group_filter.matches(g)} == matching


def test_select_groups_keeps_matching_summary_entries() -> None:
    group_filter = GroupFilterParser(GROUPS).parse({"size": "small"}, "f")
    summary: Summary = {
        ADAM_SMALL: {"acc": MetricSummary(1.0, 0.0, (1.0,))},
        ADAM_LARGE: {"acc": MetricSummary(2.0, 0.0, (2.0,))},
    }

    assert set(group_filter.select_groups(summary)) == {ADAM_SMALL}
    assert MATCH_ALL_FILTER.select_groups(summary) == summary


@pytest.mark.parametrize(
    ("raw_filter", "message"),
    [
        ([], "non-empty list"),
        ("optimizer=adam", "non-empty list"),
        (["optimizer"], r"filter\[0\] must map"),
        ({"model": "x"}, "undeclared groups: model"),
        ({"optimizer": []}, "must be a label"),
        ({"optimizer": {"a": 1}}, "must be a label"),
        ({"optimizer": True}, "quote it"),
    ],
)
def test_parser_rejects_invalid_filters(
    raw_filter: object, message: str
) -> None:
    with pytest.raises(SpecError, match=message):
        parse(raw_filter)


def test_parse_filter_label_converts_numbers() -> None:
    assert parse_filter_label(1, "f") == "1"
    assert parse_filter_label(0.5, "f") == "0.5"
    assert parse_filter_label("adam", "f") == "adam"
