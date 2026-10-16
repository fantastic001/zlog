import math

import pytest

from zlog.aggregation import MetricAggregator
from zlog.domain import IterationRecord
from zlog.group_filter import GroupFilterParser
from zlog.list_statistics import ListStatisticsReducer
from zlog.plotting import (
    PLOT_ROW_DESCRIBERS,
    PlotKind,
    PlotRequest,
    RecordValueResolver,
    build_plot_data_builders,
    select_distinguishing_group,
    select_plot_kind,
)
from zlog.reporting import ReportData

ADAM = (("optimizer", "adam"),)
SGD = (("optimizer", "sgd"),)
RECORDS = (
    IterationRecord(ADAM, 0, {"loss": ("3", "1"), "lr": ("1", "2"), "a": "5"}),
    IterationRecord(ADAM, 1, {"loss": ("5", "3", "1"), "lr": ("1",), "a": "7"}),
    IterationRecord(SGD, 0, {"loss": ("4", "nan"), "lr": ("1", "2"), "a": "x"}),
)
DATA = ReportData(MetricAggregator().aggregate(RECORDS), RECORDS)
BUILDERS = build_plot_data_builders(ListStatisticsReducer(0), 0)
SGD_ONLY = GroupFilterParser(("optimizer",)).parse({"optimizer": "sgd"}, "f")


@pytest.mark.parametrize(
    ("request_", "kind"),
    [
        (PlotRequest(y="a"), PlotKind.BAR),
        (PlotRequest(y="loss.mean"), PlotKind.BAR),
        (PlotRequest(y="loss"), PlotKind.LINE),
        (PlotRequest(y="loss", x="lr"), PlotKind.SCATTER),
        (PlotRequest(y="a", x="loss.mean"), PlotKind.SCATTER),
    ],
)
def test_select_plot_kind(request_: PlotRequest, kind: PlotKind) -> None:
    assert select_plot_kind(request_, DATA) is kind


def test_resolver_reads_scalars_arrays_and_list_statistics() -> None:
    resolver = RecordValueResolver(ListStatisticsReducer(0))

    assert resolver.resolve(RECORDS[0], "a") == (5.0,)
    assert resolver.resolve(RECORDS[2], "a") is None
    assert resolver.resolve(RECORDS[0], "loss") == (3.0, 1.0)
    assert resolver.resolve(RECORDS[1], "loss.mean") == (3.0,)
    assert resolver.resolve(RECORDS[0], "loss.unknown") is None
    assert resolver.resolve(RECORDS[0], "a.mean") is None
    assert resolver.resolve(RECORDS[0], "missing") is None


def test_bar_plot_uses_group_summaries() -> None:
    plot = BUILDERS[PlotKind.BAR].build(PlotRequest(y="a"), DATA)

    assert [series.label for series in plot.series] == ["adam"]
    assert plot.series[0].y == (6.0,)
    assert plot.series[0].spread == (1.0,)
    assert plot.series[0].category == ""
    assert plot.category_label == ""
    assert PLOT_ROW_DESCRIBERS[PlotKind.BAR](plot) == (
        {"partition": "adam", "mean": 6.0, "std": 1.0, "n": 2},
    )


def test_line_plot_averages_ragged_arrays_per_partition() -> None:
    plot = BUILDERS[PlotKind.LINE].build(PlotRequest(y="loss"), DATA)

    adam, sgd = plot.series
    assert adam.x == (0.0, 1.0, 2.0)
    assert adam.y == (4.0, 2.0, 1.0)
    assert adam.spread == (1.0, 1.0, 0.0)
    assert adam.counts == (2, 2, 1)
    assert sgd.y[0] == 4.0
    assert math.isnan(sgd.y[1])
    rows = PLOT_ROW_DESCRIBERS[PlotKind.LINE](plot)
    assert rows[0] == {
        "partition": "adam",
        "index": 0,
        "mean": 4.0,
        "std": 1.0,
        "n": 2,
    }


def test_line_plot_respects_filter_and_skips_empty_series() -> None:
    plot = BUILDERS[PlotKind.LINE].build(
        PlotRequest(y="missing", group_filter=SGD_ONLY), DATA
    )

    assert plot.series == ()


def test_scatter_plot_pairs_equal_length_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    plot = BUILDERS[PlotKind.SCATTER].build(PlotRequest(y="loss", x="lr"), DATA)

    adam, sgd = plot.series
    assert list(zip(adam.x, adam.y, strict=True)) == [(1.0, 3.0), (2.0, 1.0)]
    assert list(zip(sgd.x, sgd.y, strict=True)) == [(1.0, 4.0)]
    assert "differ in length" in caplog.text
    assert PLOT_ROW_DESCRIBERS[PlotKind.SCATTER](plot)[0] == {
        "partition": "adam",
        "lr": 1.0,
        "loss": 3.0,
    }


def test_scatter_plot_of_scalars_per_iteration() -> None:
    plot = BUILDERS[PlotKind.SCATTER].build(
        PlotRequest(y="a", x="loss.max"), DATA
    )

    assert [(s.label, s.x, s.y) for s in plot.series] == [
        ("adam", (3.0, 5.0), (5.0, 7.0))
    ]


def key(*labels: str) -> tuple[tuple[str, str], ...]:
    return tuple(zip(("g1", "g2", "g3"), labels, strict=True))


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        ([key("a", "b", "c"), key("a", "d", "f")], "g2"),
        ([key("a", "b", "c"), key("x", "b", "f")], "g1"),
        ([key("a", "b", "c"), key("a", "b", "f")], "g3"),
        ([key("a", "b", "c"), key("a", "b", "c")], None),
        ([key("a", "b", "c")], None),
        ([], None),
    ],
)
def test_select_distinguishing_group_picks_first_differing_group(
    groups: list[tuple[tuple[str, str], ...]], expected: str | None
) -> None:
    assert select_distinguishing_group(groups) == expected


def test_bar_plot_categories_follow_first_differing_group() -> None:
    records = tuple(
        IterationRecord(key(*labels), 0, {"acc": value})
        for labels, value in [
            (("a", "b", "c"), "1"),
            (("a", "b", "e"), "2"),
            (("a", "d", "f"), "3"),
        ]
    )
    data = ReportData(MetricAggregator().aggregate(records), records)

    plot = BUILDERS[PlotKind.BAR].build(PlotRequest(y="acc"), data)

    assert plot.category_label == "g2"
    assert [(s.label, s.category) for s in plot.series] == [
        ("a, b, c", "b"),
        ("a, b, e", "b"),
        ("a, d, f", "d"),
    ]
