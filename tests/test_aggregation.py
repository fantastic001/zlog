import math

import pytest

from zlog.aggregation import MetricAggregator
from zlog.domain import IterationRecord

GROUP_A = (("optimizer", "adam"),)
GROUP_B = (("optimizer", "sgd"),)


def test_computes_population_mean_and_std() -> None:
    records = [
        IterationRecord(GROUP_A, index, {"acc": value})
        for index, value in enumerate(["1", "2", "3", "nan"])
    ]

    summary = MetricAggregator().aggregate(records)

    acc = summary[GROUP_A]["acc"]
    assert acc.mean == pytest.approx(2.0)
    assert acc.std == pytest.approx(math.sqrt(2 / 3))
    assert acc.values == (1.0, 2.0, 3.0)
    assert acc.count == 3


def test_sample_std_with_ddof() -> None:
    records = [IterationRecord(GROUP_A, 0, {"acc": "1"})] + [
        IterationRecord(GROUP_A, 1, {"acc": "3"})
    ]

    summary = MetricAggregator(std_ddof=1).aggregate(records)

    assert summary[GROUP_A]["acc"].std == pytest.approx(math.sqrt(2))


def test_too_few_samples_for_ddof_gives_nan_std() -> None:
    records = [IterationRecord(GROUP_A, 0, {"acc": "4"})]

    summary = MetricAggregator(std_ddof=1).aggregate(records)

    assert summary[GROUP_A]["acc"].mean == 4.0
    assert math.isnan(summary[GROUP_A]["acc"].std)


def test_non_numeric_and_empty_samples(
    caplog: pytest.LogCaptureFixture,
) -> None:
    records = [
        IterationRecord(GROUP_A, 0, {"acc": "oops"}),
        IterationRecord(GROUP_B, 0, {}),
    ]

    summary = MetricAggregator().aggregate(records)

    assert math.isnan(summary[GROUP_A]["acc"].mean)
    assert summary[GROUP_A]["acc"].count == 0
    assert summary[GROUP_B] == {}
    assert "non-numeric" in caplog.text


def test_rejects_negative_ddof() -> None:
    with pytest.raises(ValueError):
        MetricAggregator(std_ddof=-1)
