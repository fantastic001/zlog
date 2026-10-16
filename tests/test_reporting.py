import math

from zlog.comparison import (
    ComparisonResult,
    GroupComparison,
    MetricComparator,
    PairwiseComparisonBuilder,
)
from zlog.domain import MetricSummary
from zlog.options import ComparisonFilter
from zlog.reporting import (
    NO_RESULTS_TITLE,
    SUMMARY_TITLE,
    ComparisonSectionBuilder,
    ReportBuilder,
    StructuredMetricCellFormatter,
    SummarySectionBuilder,
    TextMetricCellFormatter,
    describe_comparison,
)
from zlog.statistics import MannWhitneyUTest

GROUP_A = (("optimizer", "adam"), ("size", "small"))
GROUP_B = (("optimizer", "sgd"), ("size", "small"))
SUMMARY = {
    GROUP_B: {"acc": MetricSummary(2.0, 0.5, (1.5, 2.5))},
    GROUP_A: {
        "acc": MetricSummary(1.0, 0.0, (1.0, 1.0)),
        "loss": MetricSummary(math.nan, math.nan, ()),
    },
}


def build_report_builder() -> ReportBuilder:
    pairwise = PairwiseComparisonBuilder(
        MetricComparator(MannWhitneyUTest(), 0.05, 2), ComparisonFilter.ALL
    )
    return ReportBuilder(
        SummarySectionBuilder(TextMetricCellFormatter()),
        ComparisonSectionBuilder(pairwise),
    )


def test_text_cell_format() -> None:
    cell = TextMetricCellFormatter().format_cell(
        MetricSummary(2.0, 0.5, (1.5, 2.5))
    )

    assert cell == "2.000000 +- 0.500000 (N=2)"


def test_structured_cell_format() -> None:
    cell = StructuredMetricCellFormatter().format_cell(
        MetricSummary(2.0, 0.5, (1.5, 2.5))
    )

    assert cell == {"mean": 2.0, "std": 0.5, "n": 2}


def test_report_has_sorted_summary_and_metric_sections() -> None:
    sections = build_report_builder().build(SUMMARY)

    assert [section.title for section in sections] == [
        SUMMARY_TITLE,
        "Comparing groups for pattern: acc",
        "Comparing groups for pattern: loss",
    ]
    summary_rows = sections[0].rows
    assert [row["optimizer"] for row in summary_rows] == ["adam", "sgd"]
    assert summary_rows[0]["loss"] == "nan +- nan (N=0)"
    assert sections[1].rows[0]["groups"] == "(adam, small) vs (sgd, small)"
    assert sections[2].rows == ()


def test_empty_summary_reports_no_results() -> None:
    sections = build_report_builder().build({})

    assert [section.title for section in sections] == [NO_RESULTS_TITLE]


def test_describe_comparison_of_insufficient_data() -> None:
    row = describe_comparison(
        GroupComparison(GROUP_A, GROUP_B, "acc", ComparisonResult())
    )

    assert row == {
        "groups": "(adam, small) vs (sgd, small)",
        "mannwhitneyu_stat": None,
        "mannwhitneyu_p": None,
        "same_distribution": None,
        "cohen_d": None,
    }
