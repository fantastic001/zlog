import pytest

from zlog.domain import AnalysisSpec, PatternSpec
from zlog.grouping import (
    GroupNamePartition,
    SegmentGroupResolver,
    partition_group_names,
)

DIRECTORY_KEY = (("optimizer", "adam"),)


def test_partition_separates_extracted_groups() -> None:
    spec = AnalysisSpec(
        ("optimizer", "size", "seed"),
        (
            PatternSpec(r"size=(\w+) acc=(\f)", ("size", "acc")),
            PatternSpec(r"seed=(\d+)", ("seed",)),
        ),
    )

    assert partition_group_names(spec) == GroupNamePartition(
        directory_groups=("optimizer",),
        extracted_groups=("size", "seed"),
    )


def test_resolver_combines_directory_and_extracted_labels() -> None:
    resolver = SegmentGroupResolver(("optimizer", "size"), ("size",))

    key = resolver.resolve(DIRECTORY_KEY, {"size": "small", "acc": "1"})

    assert key == (("optimizer", "adam"), ("size", "small"))


def test_extracted_label_wins_only_for_extracted_groups() -> None:
    resolver = SegmentGroupResolver(("optimizer",), ())

    key = resolver.resolve(DIRECTORY_KEY, {"optimizer": "sgd"})

    assert key == DIRECTORY_KEY


@pytest.mark.parametrize(
    ("directory_key", "values"),
    [(DIRECTORY_KEY, {"acc": "1"}), ((), {"size": "small"})],
)
def test_resolver_returns_none_when_label_missing(
    directory_key: tuple[tuple[str, str], ...], values: dict[str, str]
) -> None:
    resolver = SegmentGroupResolver(("optimizer", "size"), ("size",))

    assert resolver.resolve(directory_key, values) is None


def test_metric_values_exclude_extracted_groups() -> None:
    resolver = SegmentGroupResolver(("optimizer", "size"), ("size",))

    metrics = resolver.select_metric_values({"size": "small", "acc": "1"})

    assert metrics == {"acc": "1"}


def test_resolver_rejects_undeclared_extracted_group() -> None:
    with pytest.raises(ValueError):
        SegmentGroupResolver(("optimizer",), ("size",))


def test_partition_ignores_append_prefix() -> None:
    spec = AnalysisSpec(
        ("optimizer", "size"), (PatternSpec(r"(\w+)", ("+size",)),)
    )

    assert partition_group_names(spec).extracted_groups == ("size",)


def test_list_label_cannot_name_a_group(
    caplog: pytest.LogCaptureFixture,
) -> None:
    resolver = SegmentGroupResolver(("optimizer", "size"), ("size",))

    assert resolver.resolve(DIRECTORY_KEY, {"size": ("a", "b")}) is None
    assert "list value" in caplog.text
