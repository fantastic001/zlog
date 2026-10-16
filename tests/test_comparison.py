from collections.abc import Sequence

import pytest

from zlog.comparison import (
    INSUFFICIENT_DATA,
    MetricComparator,
    PairwiseComparisonBuilder,
)
from zlog.domain import MetricSummary
from zlog.options import ComparisonFilter
from zlog.statistics import DistributionTestOutcome, MannWhitneyUTest

GROUP_A = (("optimizer", "adam"),)
GROUP_B = (("optimizer", "sgd"),)
GROUP_C = (("optimizer", "rms"),)


def summarize(*values: float) -> MetricSummary:
    return MetricSummary(sum(values) / len(values), 1.0, tuple(values))


class FailingTest:
    def run(
        self, first: Sequence[float], second: Sequence[float]
    ) -> DistributionTestOutcome:
        raise ValueError("boom")


def build_comparator() -> MetricComparator:
    return MetricComparator(MannWhitneyUTest(), 0.05, 2)


def test_compare_reports_test_and_effect_size() -> None:
    result = build_comparator().compare(summarize(1, 2, 3), summarize(4, 5, 6))

    assert result.p_value == pytest.approx(0.1)
    assert result.same_distribution is True
    assert result.cohen_d is not None


def test_compare_detects_different_distributions() -> None:
    first = summarize(*range(10))
    second = summarize(*range(100, 110))

    result = build_comparator().compare(first, second)

    assert result.same_distribution is False


def test_compare_with_too_few_samples() -> None:
    result = build_comparator().compare(summarize(1), summarize(1, 2))

    assert result is INSUFFICIENT_DATA


def test_failing_test_is_insufficient_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    comparator = MetricComparator(FailingTest(), 0.05, 2)

    assert comparator.compare(summarize(1, 2), summarize(3, 4)) is (
        INSUFFICIENT_DATA
    )
    assert "boom" in caplog.text


@pytest.mark.parametrize(
    ("significance_level", "minimum_sample_size"), [(0.0, 2), (0.05, 0)]
)
def test_comparator_validates_arguments(
    significance_level: float, minimum_sample_size: int
) -> None:
    with pytest.raises(ValueError):
        MetricComparator(
            MannWhitneyUTest(), significance_level, minimum_sample_size
        )


def build_summary() -> dict:  # type: ignore[type-arg]
    return {
        GROUP_B: {"acc": summarize(1, 2, 3)},
        GROUP_A: {"acc": summarize(1, 2, 3), "loss": summarize(1, 2)},
        GROUP_C: {"acc": summarize(1)},
    }


def test_pairwise_builder_compares_ordered_pairs() -> None:
    builder = PairwiseComparisonBuilder(
        build_comparator(), ComparisonFilter.ALL
    )

    comparisons = builder.compare_metric(build_summary(), "acc")

    assert [(c.first, c.second) for c in comparisons] == [
        (GROUP_A, GROUP_C),
        (GROUP_A, GROUP_B),
        (GROUP_C, GROUP_B),
    ]
    assert builder.compare_metric(build_summary(), "loss") == []


def test_pairwise_builder_filters_same_distributions() -> None:
    builder = PairwiseComparisonBuilder(
        build_comparator(), ComparisonFilter.SAME_DISTRIBUTION_ONLY
    )

    comparisons = builder.compare_metric(build_summary(), "acc")

    assert [(c.first, c.second) for c in comparisons] == [(GROUP_A, GROUP_B)]
