import logging
import math
from collections.abc import Iterable, Sequence

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
                metric: self._summarize(values)
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
                return [(metric, self._parse_sample(metric, raw_value))]
            case tuple():
                numbers = [
                    number
                    for item in raw_value
                    for number in self._parse_sample(metric, item)
                ]
                reduced = self._list_reducer.reduce(metric, numbers)
                return [(name, (value,)) for name, value in reduced.items()]

    @staticmethod
    def _parse_sample(metric: str, raw_value: str) -> tuple[float, ...]:
        try:
            return (float(raw_value),)
        except (TypeError, ValueError):
            LOGGER.warning(
                "ignoring non-numeric value %r for metric %r",
                raw_value,
                metric,
            )
            return ()

    def _summarize(self, samples: Sequence[float]) -> MetricSummary:
        values = tuple(value for value in samples if not math.isnan(value))
        return MetricSummary(
            SUMMARY_MEAN_STATISTIC(values, self._std_ddof),
            SUMMARY_STD_STATISTIC(values, self._std_ddof),
            values,
        )
