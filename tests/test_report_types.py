from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

import pytest

from zlog.aggregation import MetricAggregator
from zlog.comparison import MetricComparator
from zlog.domain import IterationRecord, ReportEntry
from zlog.errors import SpecError
from zlog.list_statistics import ListStatisticsReducer
from zlog.options import ComparisonFilter
from zlog.plot_drawing import PlotFileLocator
from zlog.plotting import PlotData, PlotKind
from zlog.report_types import (
    BUILTIN_REPORT_TYPES,
    ReportContext,
    ReportLayoutFactory,
)
from zlog.reporting import (
    NO_RESULTS_TITLE,
    ReportData,
    TextMetricCellFormatter,
)
from zlog.statistics import MannWhitneyUTest

GROUPS = ("optimizer", "size")


def make_record(
    optimizer: str, size: str, iteration: int, values: Mapping[str, object]
) -> IterationRecord:
    return IterationRecord(
        (("optimizer", optimizer), ("size", size)),
        iteration,
        MappingProxyType(dict(values)),  # type: ignore[arg-type]
    )


RECORDS = tuple(
    make_record(optimizer, size, index, {"acc": str(base + index)})
    for optimizer, size, base in [
        ("adam", "small", 0),
        ("adam", "large", 10),
        ("sgd", "small", 20),
        ("sgd", "large", 30),
    ]
    for index in range(3)
) + (make_record("adam", "small", 9, {"loss": ("2", "1")}),)
DATA = ReportData(MetricAggregator().aggregate(RECORDS), RECORDS)


class RecordingPlotWriter:
    def __init__(self) -> None:
        self.written: list[tuple[Path, str, PlotData]] = []

    def write(self, path: Path, title: str, plot: PlotData) -> None:
        self.written.append((path, title, plot))


def make_context(
    tmp_path: Path,
    writer: RecordingPlotWriter,
    comparison_filter: ComparisonFilter = ComparisonFilter.ALL,
) -> ReportContext:
    return ReportContext(
        groups=GROUPS,
        cell_formatter=TextMetricCellFormatter(),
        comparator=MetricComparator(MannWhitneyUTest(), 0.05, 2),
        comparison_filter=comparison_filter,
        list_reducer=ListStatisticsReducer(0),
        std_ddof=0,
        plot_files=PlotFileLocator(tmp_path / "plots", tmp_path, "png"),
        plot_writer=writer,
    )


def entry(name: str, report_type: str, **options: object) -> ReportEntry:
    return ReportEntry(name, report_type, f"about {name}", options)


def build_sections(
    tmp_path: Path,
    *entries: ReportEntry,
    comparison_filter: ComparisonFilter = ComparisonFilter.ALL,
) -> tuple[object, ...]:
    context = make_context(tmp_path, RecordingPlotWriter(), comparison_filter)
    layout = ReportLayoutFactory(BUILTIN_REPORT_TYPES, context).create(entries)
    return layout.build(DATA)


def test_table_filters_partitions_and_uses_entry_title(tmp_path: Path) -> None:
    (section,) = build_sections(
        tmp_path, entry("Adam", "table", filter={"optimizer": "adam"})
    )

    assert section.title == "Adam"  # type: ignore[attr-defined]
    assert section.description == "about Adam"  # type: ignore[attr-defined]
    rows = section.rows  # type: ignore[attr-defined]
    assert [(row["optimizer"], row["size"]) for row in rows] == [
        ("adam", "large"),
        ("adam", "small"),
    ]
    assert rows[1]["loss.mean"] == "1.500000 +- 0.000000 (N=1)"


def test_unfiltered_statistics_compare_every_pair(tmp_path: Path) -> None:
    (section,) = build_sections(tmp_path, entry("All", "statistics"))

    accuracy_rows = [
        row
        for row in section.rows  # type: ignore[attr-defined]
        if row["metric"] == "acc"
    ]
    assert len(accuracy_rows) == 6


def test_filtered_statistics_keep_only_cross_filter_pairs(
    tmp_path: Path,
) -> None:
    (section,) = build_sections(
        tmp_path,
        entry(
            "Opt",
            "statistics",
            first={"optimizer": "adam"},
            second={"optimizer": "sgd", "size": "small"},
        ),
    )

    assert [
        (row["metric"], row["groups"])
        for row in section.rows  # type: ignore[attr-defined]
    ] == [
        ("acc", "(adam, large) vs (sgd, small)"),
        ("acc", "(adam, small) vs (sgd, small)"),
    ]


def test_pooled_statistics_compare_pooled_samples(tmp_path: Path) -> None:
    (section,) = build_sections(
        tmp_path,
        entry(
            "Pooled",
            "statistics",
            first={"optimizer": "adam"},
            second={"optimizer": "sgd"},
            pooled=True,
        ),
    )

    rows = section.rows  # type: ignore[attr-defined]
    assert [row["metric"] for row in rows] == ["acc", "loss.mean"] + [
        "loss.count",
        "loss.stddev",
        "loss.min",
        "loss.max",
    ]
    assert rows[0]["first"] == "6.000000 +- 5.066228 (N=6)"
    assert rows[0]["second"] == "26.000000 +- 5.066228 (N=6)"
    assert rows[0]["same_distribution"] is False
    assert rows[1]["second"] == "nan +- nan (N=0)"
    assert rows[1]["mannwhitneyu_p"] is None


def test_pooled_statistics_apply_comparison_filter(tmp_path: Path) -> None:
    (section,) = build_sections(
        tmp_path,
        entry(
            "Pooled",
            "statistics",
            first={"size": "small"},
            second={"size": "large"},
            pooled=True,
        ),
        comparison_filter=ComparisonFilter.SAME_DISTRIBUTION_ONLY,
    )

    assert [
        row["metric"]
        for row in section.rows  # type: ignore[attr-defined]
    ] == ["acc"]


def test_plot_writes_file_and_attaches_link(tmp_path: Path) -> None:
    writer = RecordingPlotWriter()
    context = make_context(tmp_path, writer)
    layout = ReportLayoutFactory(BUILTIN_REPORT_TYPES, context).create(
        [entry("Accuracy plot", "plot", y="acc", filter={"size": "small"})]
    )

    (section,) = layout.build(DATA)

    assert section.attachments == ("plots/Accuracy_plot.png",)
    assert [row["partition"] for row in section.rows] == [
        "adam, small",
        "sgd, small",
    ]
    ((path, title, plot),) = writer.written
    assert path == tmp_path / "plots" / "Accuracy_plot.png"
    assert title == "Accuracy plot"
    assert plot.kind is PlotKind.BAR


def test_plot_without_data_has_no_attachment(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (section,) = build_sections(tmp_path, entry("None", "plot", y="nothing"))

    assert section.attachments == ()  # type: ignore[attr-defined]
    assert section.rows == ()  # type: ignore[attr-defined]
    assert "has no data" in caplog.text


def test_line_and_scatter_plots_are_selected(tmp_path: Path) -> None:
    writer = RecordingPlotWriter()
    context = make_context(tmp_path, writer)
    layout = ReportLayoutFactory(BUILTIN_REPORT_TYPES, context).create(
        [
            entry("Line", "plot", y="loss"),
            entry("Scatter", "plot", y="loss.mean", x="loss.max"),
        ]
    )

    layout.build(DATA)

    assert [plot.kind for _, _, plot in writer.written] == [
        PlotKind.LINE,
        PlotKind.SCATTER,
    ]


def test_layout_without_results_reports_no_results(tmp_path: Path) -> None:
    context = make_context(tmp_path, RecordingPlotWriter())
    layout = ReportLayoutFactory(BUILTIN_REPORT_TYPES, context).create(
        [entry("T", "table")]
    )

    (section,) = layout.build(ReportData({}))

    assert section.title == NO_RESULTS_TITLE


@pytest.mark.parametrize(
    ("report_entry", "message"),
    [
        (entry("X", "chart"), "unknown type 'chart'; available: plot"),
        (entry("X", "table", y="acc"), "unknown options: y"),
        (entry("X", "table", filter={"model": "a"}), "undeclared groups"),
        (entry("X", "statistics", pooled="yes"), "must be true or false"),
        (entry("X", "plot"), "'X'.y must name a value"),
        (entry("X", "plot", y="acc", x=" "), "'X'.x must name a value"),
    ],
)
def test_invalid_entries_are_rejected(
    tmp_path: Path, report_entry: ReportEntry, message: str
) -> None:
    context = make_context(tmp_path, RecordingPlotWriter())

    with pytest.raises(SpecError, match=message):
        ReportLayoutFactory(BUILTIN_REPORT_TYPES, context).create(
            [report_entry]
        )
