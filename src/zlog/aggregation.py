import logging
import math
from collections.abc import Iterable

from zlog.domain import (
    ExtractedValue,
    GroupKey,
    IterationRecord,
    MetricSummary,
    Summary,
)
from zlog.list_statistics import LIST_STATISTICS, ListStatisticsReducer

LOGGER = logging.getLogger(__name__)

Samples = dict[GroupKey, dict[str, list[float]]]
MetricSamples = list[tuple[str, tuple[float, ...]]]

SUMMARY_MEAN_STATISTIC = LIST_STATISTICS["mean"]
SUMMARY_STD_STATISTIC = LIST_STATISTICS["stddev"]


def parse_numeric_items(metric: str, raw_items: Iterable[str]) -> list[float]:
    numbers: list[float] = []
    for raw_item in raw_items:
        try:
            numbers.append(float(raw_item))
        except (TypeError, ValueError):
            LOGGER.warning(
                "ignoring non-numeric value %r for metric %r",
                raw_item,
                metric,
            )
    return numbers


def summarize_samples(samples: Iterable[float], std_ddof: int) -> MetricSummary:
    values = tuple(value for value in samples if not math.isnan(value))
    return MetricSummary(
        SUMMARY_MEAN_STATISTIC(values, std_ddof),
        SUMMARY_STD_STATISTIC(values, std_ddof),
        values,
    )


class MetricAggregator:
    def __init__(
        self,
        std_ddof: int = 0,
        list_reducer: ListStatisticsReducer | None = None,
    ) -> None:
        if std_ddof >= 0:
            self._std_ddof = std_ddof
            self._list_reducer = list_reducer or ListStatisticsReducer(std_ddof)
        else:
            raise ValueError("std_ddof must not be negative")

    def aggregate(self, records: Iterable[IterationRecord]) -> Summary:
        samples = self._collect_samples(records)
        summary = {
            group: {
                metric: summarize_samples(values, self._std_ddof)
                for metric, values in metrics.items()
            }
            for group, metrics in samples.items()
        }
        assert set(summary) == set(samples)
        return summary

    def _collect_samples(self, records: Iterable[IterationRecord]) -> Samples:
        samples: Samples = {}
        for record in records:
            group_samples = samples.setdefault(record.group, {})
            for metric, values in self._expand_record_samples(record):
                group_samples.setdefault(metric, []).extend(values)
        return samples

    def _expand_record_samples(self, record: IterationRecord) -> MetricSamples:
        return [
            metric_samples
            for metric, raw_value in record.values.items()
            for metric_samples in self._expand_metric_samples(metric, raw_value)
        ]

    def _expand_metric_samples(
        self, metric: str, raw_value: ExtractedValue
    ) -> MetricSamples:
        match raw_value:
            case str():
                numbers = parse_numeric_items(metric, (raw_value,))
                return [(metric, tuple(numbers))]
            case tuple():
                numbers = parse_numeric_items(metric, raw_value)
                reduced = self._list_reducer.reduce(metric, numbers)
                return [(name, (value,)) for name, value in reduced.items()]
