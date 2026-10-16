from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from zlog.comparison import (
    ComparisonResult,
    GroupComparison,
    PairwiseComparisonBuilder,
)
from zlog.domain import (
    GroupKey,
    IterationRecord,
    MetricSummary,
    Summary,
    format_group_label,
)

Row = Mapping[str, object]

NO_RESULTS_TITLE = "No results to summarize."
SUMMARY_TITLE = "Summary for all groups"
COMPARISON_TITLE_TEMPLATE = "Comparing groups for pattern: {metric}"


@dataclass(frozen=True)
class ReportSection:
    title: str
    rows: tuple[Row, ...] = ()
    description: str = ""
    attachments: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportData:
    summary: Summary
    records: tuple[IterationRecord, ...] = ()


class ReportLayout(Protocol):
    def build(self, data: ReportData) -> tuple[ReportSection, ...]: ...


def list_metrics(summary: Summary) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            metric for group in sorted(summary) for metric in summary[group]
        )
    )


class MetricCellFormatter(Protocol):
    def format_cell(self, summary: MetricSummary) -> object: ...


class TextMetricCellFormatter:
    def format_cell(self, summary: MetricSummary) -> object:
        return f"{summary.mean:f} +- {summary.std:f} (N={summary.count})"


class StructuredMetricCellFormatter:
    def format_cell(self, summary: MetricSummary) -> object:
        return {"mean": summary.mean, "std": summary.std, "n": summary.count}


def describe_comparison_result(result: ComparisonResult) -> Row:
    return {
        "mannwhitneyu_stat": result.statistic,
        "mannwhitneyu_p": result.p_value,
        "same_distribution": result.same_distribution,
        "cohen_d": result.cohen_d,
    }


def describe_comparison(comparison: GroupComparison) -> Row:
    first_label = format_group_label(comparison.first)
    second_label = format_group_label(comparison.second)
    return {
        "groups": f"({first_label}) vs ({second_label})",
        **describe_comparison_result(comparison.result),
    }


class SummarySectionBuilder:
    def __init__(self, cell_formatter: MetricCellFormatter) -> None:
        self._cell_formatter = cell_formatter

    def build(self, summary: Summary) -> ReportSection:
        rows = tuple(
            self._build_group_row(group, summary[group])
            for group in sorted(summary)
        )
        return ReportSection(SUMMARY_TITLE, rows)

    def _build_group_row(
        self, group: GroupKey, metrics: Mapping[str, MetricSummary]
    ) -> Row:
        cells = {
            metric: self._cell_formatter.format_cell(metric_summary)
            for metric, metric_summary in metrics.items()
        }
        return {**dict(group), **cells}


class ComparisonSectionBuilder:
    def __init__(self, pairwise_builder: PairwiseComparisonBuilder) -> None:
        self._pairwise_builder = pairwise_builder

    def build(self, summary: Summary) -> tuple[ReportSection, ...]:
        return tuple(
            self._build_metric_section(summary, metric)
            for metric in list_metrics(summary)
        )

    def _build_metric_section(
        self, summary: Summary, metric: str
    ) -> ReportSection:
        comparisons = self._pairwise_builder.compare_metric(summary, metric)
        return ReportSection(
            COMPARISON_TITLE_TEMPLATE.format(metric=metric),
            tuple(map(describe_comparison, comparisons)),
        )


class ReportBuilder:
    def __init__(
        self,
        summary_builder: SummarySectionBuilder,
        comparison_builder: ComparisonSectionBuilder,
    ) -> None:
        self._summary_builder = summary_builder
        self._comparison_builder = comparison_builder

    def build(self, summary: Summary) -> tuple[ReportSection, ...]:
        if summary:
            return (
                self._summary_builder.build(summary),
                *self._comparison_builder.build(summary),
            )
        else:
            return (ReportSection(NO_RESULTS_TITLE),)


class DefaultReportLayout:
    def __init__(self, report_builder: ReportBuilder) -> None:
        self._report_builder = report_builder

    def build(self, data: ReportData) -> tuple[ReportSection, ...]:
        return self._report_builder.build(data.summary)
