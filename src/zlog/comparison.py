import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import combinations
from types import MappingProxyType

from zlog.domain import GroupKey, MetricSummary, Summary
from zlog.options import ComparisonFilter
from zlog.statistics import DistributionTest, compute_cohen_d

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComparisonResult:
    statistic: float | None = None
    p_value: float | None = None
    same_distribution: bool | None = None
    cohen_d: float | None = None


INSUFFICIENT_DATA = ComparisonResult()


@dataclass(frozen=True)
class GroupComparison:
    first: GroupKey
    second: GroupKey
    metric: str
    result: ComparisonResult


COMPARISON_FILTERS: Mapping[
    ComparisonFilter, Callable[[ComparisonResult], bool]
] = MappingProxyType(
    {
        ComparisonFilter.ALL: lambda result: True,
        ComparisonFilter.SAME_DISTRIBUTION_ONLY: (
            lambda result: result.same_distribution is True
        ),
    }
)


class MetricComparator:
    def __init__(
        self,
        test: DistributionTest,
        significance_level: float,
        minimum_sample_size: int,
    ) -> None:
        if 0.0 < significance_level < 1.0 and minimum_sample_size >= 1:
            self._test = test
            self._significance_level = significance_level
            self._minimum_sample_size = minimum_sample_size
        else:
            raise ValueError(
                "significance_level must be in (0, 1) and "
                "minimum_sample_size at least 1"
            )

    def compare(
        self, first: MetricSummary, second: MetricSummary
    ) -> ComparisonResult:
        has_enough_samples = (
            first.count >= self._minimum_sample_size
            and second.count >= self._minimum_sample_size
        )
        if has_enough_samples:
            return self._compare_samples(first.values, second.values)
        else:
            return INSUFFICIENT_DATA

    def _compare_samples(
        self, first: tuple[float, ...], second: tuple[float, ...]
    ) -> ComparisonResult:
        try:
            outcome = self._test.run(first, second)
        except ValueError as error:
            LOGGER.error("distribution test failed: %s", error)
            return INSUFFICIENT_DATA
        else:
            return ComparisonResult(
                statistic=outcome.statistic,
                p_value=outcome.p_value,
                same_distribution=outcome.p_value > self._significance_level,
                cohen_d=compute_cohen_d(first, second),
            )


class PairwiseComparisonBuilder:
    def __init__(
        self,
        comparator: MetricComparator,
        comparison_filter: ComparisonFilter,
    ) -> None:
        self._comparator = comparator
        self._should_keep = COMPARISON_FILTERS[comparison_filter]

    def compare_metric(
        self, summary: Summary, metric: str
    ) -> list[GroupComparison]:
        comparable_pairs = [
            (first, second)
            for first, second in combinations(sorted(summary), 2)
            if metric in summary[first] and metric in summary[second]
        ]
        comparisons = (
            GroupComparison(
                first,
                second,
                metric,
                self._comparator.compare(
                    summary[first][metric], summary[second][metric]
                ),
            )
            for first, second in comparable_pairs
        )
        return [
            comparison
            for comparison in comparisons
            if self._should_keep(comparison.result)
        ]
