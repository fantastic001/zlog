import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from zlog.aggregation import summarize_samples
from zlog.comparison import (
    COMPARISON_FILTERS,
    GroupComparison,
    MetricComparator,
    PairwiseComparisonBuilder,
)
from zlog.domain import MetricSummary, ReportEntry, Summary
from zlog.errors import SpecError
from zlog.group_filter import GroupFilter, GroupFilterParser
from zlog.list_statistics import ListStatisticsReducer
from zlog.options import ComparisonFilter
from zlog.plot_drawing import PlotFileLocator, PlotWriter
from zlog.plotting import (
    PLOT_ROW_DESCRIBERS,
    PlotRequest,
    build_plot_data_builders,
    select_plot_kind,
)
from zlog.reporting import (
    NO_RESULTS_TITLE,
    MetricCellFormatter,
    ReportData,
    ReportSection,
    Row,
    SummarySectionBuilder,
    describe_comparison,
    describe_comparison_result,
    list_metrics,
)

LOGGER = logging.getLogger(__name__)

FILTER_OPTION = "filter"
FIRST_FILTER_OPTION = "first"
SECOND_FILTER_OPTION = "second"
POOLED_OPTION = "pooled"
X_OPTION = "x"
Y_OPTION = "y"


class StatisticsSelection(Enum):
    FILTERED_PAIRS = "filtered-pairs"
    POOLED = "pooled"


STATISTICS_SELECTION_BY_POOLED: Mapping[bool, StatisticsSelection] = (
    MappingProxyType(
        {
            False: StatisticsSelection.FILTERED_PAIRS,
            True: StatisticsSelection.POOLED,
        }
    )
)


@dataclass(frozen=True)
class ReportContext:
    groups: tuple[str, ...]
    cell_formatter: MetricCellFormatter
    comparator: MetricComparator
    comparison_filter: ComparisonFilter
    list_reducer: ListStatisticsReducer
    std_ddof: int
    plot_files: PlotFileLocator
    plot_writer: PlotWriter


class SectionContentBuilder(Protocol):
    def build(self, data: ReportData) -> ReportSection: ...


class ReportType(Protocol):
    def create_builder(
        self, entry: ReportEntry, context: ReportContext
    ) -> SectionContentBuilder: ...


def require_known_options(
    entry: ReportEntry, allowed_options: Sequence[str]
) -> None:
    unknown_options = sorted(set(entry.options) - set(allowed_options))
    if not unknown_options:
        LOGGER.debug("report %r options: %s", entry.name, dict(entry.options))
    else:
        raise SpecError(
            f"report {entry.name!r} of type {entry.type!r} has unknown "
            f"options: {', '.join(unknown_options)}"
        )


def parse_entry_filter(
    entry: ReportEntry, context: ReportContext, option: str
) -> GroupFilter:
    return GroupFilterParser(context.groups).parse(
        entry.options.get(option), f"report {entry.name!r}.{option}"
    )


def connects_filters(
    pair: GroupComparison, first: GroupFilter, second: GroupFilter
) -> bool:
    return (first.matches(pair.first) and second.matches(pair.second)) or (
        first.matches(pair.second) and second.matches(pair.first)
    )


class TableSectionBuilder:
    def __init__(
        self, group_filter: GroupFilter, summary_builder: SummarySectionBuilder
    ) -> None:
        self._group_filter = group_filter
        self._summary_builder = summary_builder

    def build(self, data: ReportData) -> ReportSection:
        selected = self._group_filter.select_groups(data.summary)
        return self._summary_builder.build(selected)


class TableReportType:
    def create_builder(
        self, entry: ReportEntry, context: ReportContext
    ) -> SectionContentBuilder:
        require_known_options(entry, (FILTER_OPTION,))
        return TableSectionBuilder(
            parse_entry_filter(entry, context, FILTER_OPTION),
            SummarySectionBuilder(context.cell_formatter),
        )


class FilteredPairsStatisticsBuilder:
    def __init__(
        self,
        first: GroupFilter,
        second: GroupFilter,
        pairwise_builder: PairwiseComparisonBuilder,
    ) -> None:
        self._first = first
        self._second = second
        self._pairwise_builder = pairwise_builder

    def build(self, data: ReportData) -> ReportSection:
        candidates = {
            group: metrics
            for group, metrics in data.summary.items()
            if self._first.matches(group) or self._second.matches(group)
        }
        rows = tuple(
            {"metric": metric, **describe_comparison(comparison)}
            for metric in list_metrics(candidates)
            for comparison in self._pairwise_builder.compare_metric(
                candidates, metric
            )
            if connects_filters(comparison, self._first, self._second)
        )
        return ReportSection("", rows)


class PooledStatisticsBuilder:
    def __init__(
        self,
        first: GroupFilter,
        second: GroupFilter,
        context: ReportContext,
    ) -> None:
        self._first = first
        self._second = second
        self._context = context
        self._should_keep = COMPARISON_FILTERS[context.comparison_filter]

    def build(self, data: ReportData) -> ReportSection:
        first_summary = self._first.select_groups(data.summary)
        second_summary = self._second.select_groups(data.summary)
        metrics = list_metrics({**first_summary, **second_summary})
        rows = (
            self._compare_pooled_metric(first_summary, second_summary, metric)
            for metric in metrics
        )
        return ReportSection("", tuple(row for row in rows if row is not None))

    def _compare_pooled_metric(
        self, first_summary: Summary, second_summary: Summary, metric: str
    ) -> Row | None:
        first = self._pool_metric(first_summary, metric)
        second = self._pool_metric(second_summary, metric)
        result = self._context.comparator.compare(first, second)
        if self._should_keep(result):
            formatter = self._context.cell_formatter
            return {
                "metric": metric,
                "first": formatter.format_cell(first),
                "second": formatter.format_cell(second),
                **describe_comparison_result(result),
            }
        else:
            return None

    def _pool_metric(self, summary: Summary, metric: str) -> MetricSummary:
        pooled_values = (
            value
            for group in sorted(summary)
            if metric in summary[group]
            for value in summary[group][metric].values
        )
        return summarize_samples(pooled_values, self._context.std_ddof)


STATISTICS_BUILDER_FACTORIES: Mapping[
    StatisticsSelection,
    Callable[[GroupFilter, GroupFilter, ReportContext], SectionContentBuilder],
] = MappingProxyType(
    {
        StatisticsSelection.FILTERED_PAIRS: (
            lambda first, second, context: FilteredPairsStatisticsBuilder(
                first,
                second,
                PairwiseComparisonBuilder(
                    context.comparator, context.comparison_filter
                ),
            )
        ),
        StatisticsSelection.POOLED: PooledStatisticsBuilder,
    }
)


class StatisticsReportType:
    def create_builder(
        self, entry: ReportEntry, context: ReportContext
    ) -> SectionContentBuilder:
        require_known_options(
            entry, (FIRST_FILTER_OPTION, SECOND_FILTER_OPTION, POOLED_OPTION)
        )
        selection = self._parse_selection(entry)
        LOGGER.debug("report %r uses %s", entry.name, selection.value)
        return STATISTICS_BUILDER_FACTORIES[selection](
            parse_entry_filter(entry, context, FIRST_FILTER_OPTION),
            parse_entry_filter(entry, context, SECOND_FILTER_OPTION),
            context,
        )

    @staticmethod
    def _parse_selection(entry: ReportEntry) -> StatisticsSelection:
        match entry.options.get(POOLED_OPTION, False):
            case bool() as pooled:
                return STATISTICS_SELECTION_BY_POOLED[pooled]
            case _:
                raise SpecError(
                    f"report {entry.name!r}.{POOLED_OPTION} must be "
                    "true or false"
                )


class PlotSectionBuilder:
    def __init__(
        self,
        request: PlotRequest,
        plot_file: Path,
        title: str,
        context: ReportContext,
    ) -> None:
        self._request = request
        self._plot_file = plot_file
        self._title = title
        self._context = context
        self._data_builders = build_plot_data_builders(
            context.list_reducer, context.std_ddof
        )

    def build(self, data: ReportData) -> ReportSection:
        kind = select_plot_kind(self._request, data)
        plot = self._data_builders[kind].build(self._request, data)
        rows = PLOT_ROW_DESCRIBERS[kind](plot)
        if plot.series:
            self._context.plot_writer.write(self._plot_file, self._title, plot)
            link = self._context.plot_files.link(self._plot_file)
            return ReportSection("", rows, attachments=(link,))
        else:
            LOGGER.warning(
                "plot %r has no data for y=%r x=%r",
                self._title,
                self._request.y,
                self._request.x,
            )
            return ReportSection("", rows)


class PlotReportType:
    def create_builder(
        self, entry: ReportEntry, context: ReportContext
    ) -> SectionContentBuilder:
        require_known_options(entry, (FILTER_OPTION, X_OPTION, Y_OPTION))
        request = PlotRequest(
            y=self._parse_value_name(entry, Y_OPTION),
            x=self._parse_optional_value_name(entry, X_OPTION),
            group_filter=parse_entry_filter(entry, context, FILTER_OPTION),
        )
        plot_file = context.plot_files.reserve(entry.name)
        return PlotSectionBuilder(request, plot_file, entry.name, context)

    @classmethod
    def _parse_optional_value_name(
        cls, entry: ReportEntry, option: str
    ) -> str | None:
        if option in entry.options:
            return cls._parse_value_name(entry, option)
        else:
            return None

    @staticmethod
    def _parse_value_name(entry: ReportEntry, option: str) -> str:
        match entry.options.get(option):
            case str() as name if name.strip():
                return name.strip()
            case _:
                raise SpecError(
                    f"report {entry.name!r}.{option} must name a value"
                )


BUILTIN_REPORT_TYPES: Mapping[str, ReportType] = MappingProxyType(
    {
        "table": TableReportType(),
        "statistics": StatisticsReportType(),
        "plot": PlotReportType(),
    }
)


@dataclass(frozen=True)
class ConfiguredSection:
    entry: ReportEntry
    builder: SectionContentBuilder


class ConfiguredReportLayout:
    def __init__(self, sections: Sequence[ConfiguredSection]) -> None:
        self._sections = tuple(sections)

    def build(self, data: ReportData) -> tuple[ReportSection, ...]:
        if data.summary:
            return tuple(
                self._build_titled_section(section, data)
                for section in self._sections
            )
        else:
            return (ReportSection(NO_RESULTS_TITLE),)

    @staticmethod
    def _build_titled_section(
        section: ConfiguredSection, data: ReportData
    ) -> ReportSection:
        content = section.builder.build(data)
        return replace(
            content,
            title=section.entry.name,
            description=section.entry.description,
        )


class ReportLayoutFactory:
    def __init__(
        self, report_types: Mapping[str, ReportType], context: ReportContext
    ) -> None:
        self._report_types = report_types
        self._context = context

    def create(self, entries: Sequence[ReportEntry]) -> ConfiguredReportLayout:
        assert entries, "a configured layout needs report entries"
        return ConfiguredReportLayout(
            tuple(
                ConfiguredSection(entry, self._create_builder(entry))
                for entry in entries
            )
        )

    def _create_builder(self, entry: ReportEntry) -> SectionContentBuilder:
        try:
            report_type = self._report_types[entry.type]
        except KeyError as error:
            available = ", ".join(sorted(self._report_types))
            raise SpecError(
                f"report {entry.name!r} has unknown type {entry.type!r}; "
                f"available: {available}"
            ) from error
        else:
            return report_type.create_builder(entry, self._context)
