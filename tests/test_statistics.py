import math

import pytest

from zlog.statistics import MannWhitneyUTest, compute_cohen_d


def test_mann_whitney_disjoint_samples() -> None:
    outcome = MannWhitneyUTest().run([1, 2, 3], [4, 5, 6])

    assert outcome.statistic == 0.0
    assert outcome.p_value == pytest.approx(0.1)


def test_mann_whitney_requires_samples() -> None:
    with pytest.raises(ValueError):
        MannWhitneyUTest().run([], [1.0])


def test_cohen_d_matches_definition() -> None:
    expected = -3 / math.sqrt(2 / 3)

    assert compute_cohen_d([1, 2, 3], [4, 5, 6]) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("first", "second", "check"),
    [
        ([1.0, 1.0], [1.0, 1.0], math.isnan),
        ([2.0, 2.0], [1.0, 1.0], lambda value: value == math.inf),
    ],
)
def test_cohen_d_with_zero_variance(first, second, check) -> None:  # type: ignore[no-untyped-def]
    assert check(compute_cohen_d(first, second))


def test_cohen_d_requires_samples() -> None:
    with pytest.raises(ValueError):
        compute_cohen_d([1.0], [])
