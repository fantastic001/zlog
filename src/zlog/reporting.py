from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from zlog.comparison import GroupComparison, PairwiseComparisonBuilder
from zlog.domain import GroupKey, MetricSummary, Summary, format_group_label

Row = Mapping[str, object]

NO_RESULTS_TITLE = "No results to summarize."
SUMMARY_TITLE = "Summary for all groups"
COMPARISON_TITLE_TEMPLATE = "Comparing groups for pattern: {metric}"


@dataclass(frozen=True)
class ReportSection:
    title: str
    rows: tuple[Row, ...] = ()


class MetricCellFormatter(Protocol):
    def format_cell(self, summary: MetricSummary) -> object: ...


class TextMetricCellFormatter:
    def format_cell(self, summary: MetricSummary) -> object:
        return f"{summary.mean:f} +- {summary.std:f} (N={summary.count})"


class StructuredMetricCellFormatter:
    def format_cell(self, summary: MetricSummary) -> object:
        return {"mean": summary.mean, "std": summary.std, "n": summary.count}


def describe_comparison(comparison: GroupComparison) -> Row:
    first_label = format_group_label(comparison.first)
    second_label = format_group_label(comparison.second)
    return {
        "groups": f"({first_label}) vs ({second_label})",
        "mannwhitneyu_stat": comparison.result.statistic,
        "mannwhitneyu_p": comparison.result.p_value,
        "same_distribution": comparison.result.same_distribution,
        "cohen_d": comparison.result.cohen_d,
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
        metrics = dict.fromkeys(
            metric for group in sorted(summary) for metric in summary[group]
        )
        return tuple(
            self._build_metric_section(summary, metric) for metric in metrics
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
