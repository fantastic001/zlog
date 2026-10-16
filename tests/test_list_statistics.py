import math

import pytest

from zlog.list_statistics import ListStatisticsReducer


def test_reduces_list_to_named_statistics() -> None:
    reduced = ListStatisticsReducer(std_ddof=0).reduce(
        "loss", [3.0, 1.0, math.nan, 2.0]
    )

    assert list(reduced) == [
        "loss.mean",
        "loss.count",
        "loss.stddev",
        "loss.min",
        "loss.max",
    ]
    assert reduced["loss.mean"] == pytest.approx(2.0)
    assert reduced["loss.count"] == 3.0
    assert reduced["loss.stddev"] == pytest.approx(math.sqrt(2 / 3))
    assert (reduced["loss.min"], reduced["loss.max"]) == (1.0, 3.0)


def test_empty_list_gives_zero_count_and_nan_statistics() -> None:
    reduced = ListStatisticsReducer(std_ddof=0).reduce("loss", [])

    assert reduced["loss.count"] == 0.0
    assert all(
        math.isnan(reduced[f"loss.{name}"])
        for name in ("mean", "stddev", "min", "max")
    )


def test_stddev_needs_more_values_than_ddof() -> None:
    reduced = ListStatisticsReducer(std_ddof=1).reduce("loss", [4.0])

    assert math.isnan(reduced["loss.stddev"])


def test_custom_statistics_table() -> None:
    reducer = ListStatisticsReducer(
        0, {"sum": lambda values, ddof: sum(values)}
    )

    assert reducer.reduce("x", [1.0, 2.0]) == {"x.sum": 3.0}


def test_rejects_negative_ddof() -> None:
    with pytest.raises(ValueError):
        ListStatisticsReducer(std_ddof=-1)
