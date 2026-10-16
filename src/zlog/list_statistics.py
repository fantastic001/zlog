import logging
import math
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType

import numpy as np

LOGGER = logging.getLogger(__name__)

ListStatistic = Callable[[Sequence[float], int], float]

LIST_METRIC_SEPARATOR = "."

LIST_STATISTICS: Mapping[str, ListStatistic] = MappingProxyType(
    {
        "mean": lambda values, ddof: (
            float(np.mean(values)) if values else math.nan
        ),
        "count": lambda values, ddof: float(len(values)),
        "stddev": lambda values, ddof: (
            float(np.std(values, ddof=ddof)) if len(values) > ddof else math.nan
        ),
        "min": lambda values, ddof: (
            float(np.min(values)) if values else math.nan
        ),
        "max": lambda values, ddof: (
            float(np.max(values)) if values else math.nan
        ),
    }
)


class ListStatisticsReducer:
    def __init__(
        self,
        std_ddof: int,
        statistics: Mapping[str, ListStatistic] = LIST_STATISTICS,
    ) -> None:
        if std_ddof >= 0:
            self._std_ddof = std_ddof
            self._statistics = MappingProxyType(dict(statistics))
        else:
            raise ValueError("std_ddof must not be negative")

    def reduce(self, metric: str, values: Sequence[float]) -> dict[str, float]:
        numbers = [value for value in values if not math.isnan(value)]
        reduced = {
            f"{metric}{LIST_METRIC_SEPARATOR}{name}": statistic(
                numbers, self._std_ddof
            )
            for name, statistic in self._statistics.items()
        }
        LOGGER.debug("reduced %r list %s to %s", metric, values, reduced)
        return reduced
