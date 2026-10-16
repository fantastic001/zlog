import logging
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Protocol

from zlog.aggregation import parse_numeric_items, summarize_samples
from zlog.domain import GroupKey, IterationRecord, format_group_label
from zlog.group_filter import GroupFilter
from zlog.group_labels import GroupLabeler, find_varying_groups
from zlog.list_statistics import LIST_METRIC_SEPARATOR, ListStatisticsReducer
from zlog.reporting import ReportData, Row

LOGGER = logging.getLogger(__name__)

LINE_PLOT_X_LABEL = "index"


class PlotKind(Enum):
    BAR = "bar"
    LINE = "line"
    SCATTER = "scatter"


@dataclass(frozen=True)
class PlotRequest:
    y: str
    x: str | None = None
    group_filter: GroupFilter = GroupFilter()


@dataclass(frozen=True)
class PlotSeries:
    label: str
    x: tuple[float, ...]
    y: tuple[float, ...]
    spread: tuple[float, ...] = ()
    counts: tuple[int, ...] = ()
    category: str = ""
    axis_label: str = ""


@dataclass(frozen=True)
class PlotData:
    kind: PlotKind
    x_label: str
    y_label: str
    series: tuple[PlotSeries, ...]
    category_label: str = ""


class PlotDataBuilder(Protocol):
    def build(self, request: PlotRequest, data: ReportData) -> PlotData: ...


def select_matching_records(
    records: Sequence[IterationRecord], group_filter: GroupFilter
) -> tuple[IterationRecord, ...]:
    return tuple(
        record for record in records if group_filter.matches(record.group)
    )


def group_records(
    records: Sequence[IterationRecord],
) -> dict[GroupKey, list[IterationRecord]]:
    grouped: dict[GroupKey, list[IterationRecord]] = {}
    for record in records:
        grouped.setdefault(record.group, []).append(record)
    return dict(sorted(grouped.items()))


def select_distinguishing_group(groups: Sequence[GroupKey]) -> str | None:
    return next(iter(find_varying_groups(groups)), None)


def label_series_by_varying_groups(
    series_by_group: Mapping[GroupKey, PlotSeries],
) -> tuple[PlotSeries, ...]:
    plotted = {
        group: series for group, series in series_by_group.items() if series.x
    }
    labeler = GroupLabeler.for_varying_groups(plotted)
    return tuple(
        replace(series, label=labeler.label(group))
        for group, series in plotted.items()
    )


def select_plot_kind(request: PlotRequest, data: ReportData) -> PlotKind:
    matching_records = select_matching_records(
        data.records, request.group_filter
    )
    y_is_array = any(
        isinstance(record.values.get(request.y), tuple)
        for record in matching_records
    )
    match (request.x, y_is_array):
        case (str(), _):
            return PlotKind.SCATTER
        case (None, True):
            return PlotKind.LINE
        case _:
            return PlotKind.BAR


class RecordValueResolver:
    def __init__(self, list_reducer: ListStatisticsReducer) -> None:
        self._list_reducer = list_reducer

    def resolve(
        self, record: IterationRecord, name: str
    ) -> tuple[float, ...] | None:
        match record.values.get(name):
            case str() as raw_value:
                return tuple(parse_numeric_items(name, (raw_value,))) or None
            case tuple() as raw_items:
                return tuple(parse_numeric_items(name, raw_items))
            case _:
                return self._resolve_list_statistic(record, name)

    def _resolve_list_statistic(
        self, record: IterationRecord, name: str
    ) -> tuple[float, ...] | None:
        list_name, separator, _ = name.rpartition(LIST_METRIC_SEPARATOR)
        match record.values.get(list_name):
            case tuple() as raw_items if separator:
                numbers = parse_numeric_items(list_name, raw_items)
                reduced = self._list_reducer.reduce(list_name, numbers)
                return (reduced[name],) if name in reduced else None
            case _:
                return None


class BarPlotDataBuilder:
    def build(self, request: PlotRequest, data: ReportData) -> PlotData:
        selected = request.group_filter.select_groups(data.summary)
        plotted_groups = [
            group
            for group in sorted(selected)
            if request.y in selected[group]
            and selected[group][request.y].count > 0
        ]
        category_group = select_distinguishing_group(plotted_groups)
        labeler = GroupLabeler.for_varying_groups(plotted_groups)
        axis_labeler = labeler.without(category_group)
        series = tuple(
            PlotSeries(
                label=labeler.label(group),
                x=(float(position),),
                y=(selected[group][request.y].mean,),
                spread=(selected[group][request.y].std,),
                counts=(selected[group][request.y].count,),
                category=dict(group).get(category_group or "", ""),
                axis_label=axis_labeler.label(group),
            )
            for position, group in enumerate(plotted_groups)
        )
        LOGGER.debug("bar plot colored by group %r", category_group)
        return PlotData(
            PlotKind.BAR, "", request.y, series, category_group or ""
        )


class LinePlotDataBuilder:
    def __init__(self, resolver: RecordValueResolver, std_ddof: int) -> None:
        self._resolver = resolver
        self._std_ddof = std_ddof

    def build(self, request: PlotRequest, data: ReportData) -> PlotData:
        matching = select_matching_records(data.records, request.group_filter)
        series_by_group = {
            group: self._average_group_arrays(records, request.y)
            for group, records in group_records(matching).items()
        }
        return PlotData(
            PlotKind.LINE,
            LINE_PLOT_X_LABEL,
            request.y,
            label_series_by_varying_groups(series_by_group),
        )

    def _average_group_arrays(
        self, records: Sequence[IterationRecord], name: str
    ) -> PlotSeries:
        arrays = [
            values
            for values in (
                self._resolver.resolve(record, name) for record in records
            )
            if values is not None
        ]
        length = max(map(len, arrays), default=0)
        summaries = [
            summarize_samples(
                (values[index] for values in arrays if index < len(values)),
                self._std_ddof,
            )
            for index in range(length)
        ]
        return PlotSeries(
            label="",
            x=tuple(map(float, range(length))),
            y=tuple(summary.mean for summary in summaries),
            spread=tuple(summary.std for summary in summaries),
            counts=tuple(summary.count for summary in summaries),
        )


class ScatterPlotDataBuilder:
    def __init__(self, resolver: RecordValueResolver) -> None:
        self._resolver = resolver

    def build(self, request: PlotRequest, data: ReportData) -> PlotData:
        assert request.x is not None, "scatter plot needs an x value"
        matching = select_matching_records(data.records, request.group_filter)
        series_by_group = {
            group: self._pair_group_values(records, request.x, request.y)
            for group, records in group_records(matching).items()
        }
        return PlotData(
            PlotKind.SCATTER,
            request.x,
            request.y,
            label_series_by_varying_groups(series_by_group),
        )

    def _pair_group_values(
        self,
        records: Sequence[IterationRecord],
        x_name: str,
        y_name: str,
    ) -> PlotSeries:
        points = [
            point
            for record in records
            for point in self._pair_record_values(record, x_name, y_name)
            if not (math.isnan(point[0]) or math.isnan(point[1]))
        ]
        return PlotSeries(
            label="",
            x=tuple(x for x, _ in points),
            y=tuple(y for _, y in points),
        )

    def _pair_record_values(
        self, record: IterationRecord, x_name: str, y_name: str
    ) -> list[tuple[float, float]]:
        x_values = self._resolver.resolve(record, x_name)
        y_values = self._resolver.resolve(record, y_name)
        match (x_values, y_values):
            case (tuple(), tuple()) if len(x_values) == len(y_values):
                return list(zip(x_values, y_values, strict=True))
            case _:
                LOGGER.warning(
                    "skipping iteration %d segment %d of %s for scatter: "
                    "%r and %r are missing or differ in length",
                    record.iteration,
                    record.segment,
                    format_group_label(record.group),
                    x_name,
                    y_name,
                )
                return []


def describe_bar_series(plot: PlotData) -> tuple[Row, ...]:
    return tuple(
        {
            "partition": series.label,
            "mean": series.y[0],
            "std": series.spread[0],
            "n": series.counts[0],
        }
        for series in plot.series
    )


def describe_line_series(plot: PlotData) -> tuple[Row, ...]:
    return tuple(
        {
            "partition": series.label,
            plot.x_label: int(x),
            "mean": y,
            "std": spread,
            "n": count,
        }
        for series in plot.series
        for x, y, spread, count in zip(
            series.x, series.y, series.spread, series.counts, strict=True
        )
    )


def describe_scatter_series(plot: PlotData) -> tuple[Row, ...]:
    return tuple(
        {"partition": series.label, plot.x_label: x, plot.y_label: y}
        for series in plot.series
        for x, y in zip(series.x, series.y, strict=True)
    )


PLOT_ROW_DESCRIBERS: Mapping[
    PlotKind, Callable[[PlotData], tuple[Row, ...]]
] = MappingProxyType(
    {
        PlotKind.BAR: describe_bar_series,
        PlotKind.LINE: describe_line_series,
        PlotKind.SCATTER: describe_scatter_series,
    }
)


def build_plot_data_builders(
    list_reducer: ListStatisticsReducer, std_ddof: int
) -> Mapping[PlotKind, PlotDataBuilder]:
    resolver = RecordValueResolver(list_reducer)
    return MappingProxyType(
        {
            PlotKind.BAR: BarPlotDataBuilder(),
            PlotKind.LINE: LinePlotDataBuilder(resolver, std_ddof),
            PlotKind.SCATTER: ScatterPlotDataBuilder(resolver),
        }
    )
