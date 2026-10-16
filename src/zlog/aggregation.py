import logging
import math
from collections.abc import Iterable, Sequence

import numpy as np

from zlog.domain import GroupKey, IterationRecord, MetricSummary, Summary

LOGGER = logging.getLogger(__name__)

Samples = dict[GroupKey, dict[str, list[float]]]


class MetricAggregator:
    def __init__(self, std_ddof: int = 0) -> None:
        if std_ddof >= 0:
            self._std_ddof = std_ddof
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
            for metric, raw_value in record.values.items():
                group_samples.setdefault(metric, []).extend(
                    self._parse_sample(metric, raw_value)
                )
        return samples

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
        match len(values):
            case 0:
                return MetricSummary(math.nan, math.nan, values)
            case count if count <= self._std_ddof:
                return MetricSummary(float(np.mean(values)), math.nan, values)
            case _:
                return MetricSummary(
                    float(np.mean(values)),
                    float(np.std(values, ddof=self._std_ddof)),
                    values,
                )
