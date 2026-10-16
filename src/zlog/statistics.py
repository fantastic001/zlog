import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from scipy import stats

MANN_WHITNEY_ALTERNATIVE = "two-sided"


@dataclass(frozen=True)
class DistributionTestOutcome:
    statistic: float
    p_value: float


class DistributionTest(Protocol):
    def run(
        self, first: Sequence[float], second: Sequence[float]
    ) -> DistributionTestOutcome: ...


class MannWhitneyUTest:
    def run(
        self, first: Sequence[float], second: Sequence[float]
    ) -> DistributionTestOutcome:
        if first and second:
            result = stats.mannwhitneyu(
                first, second, alternative=MANN_WHITNEY_ALTERNATIVE
            )
            return DistributionTestOutcome(
                float(result.statistic), float(result.pvalue)
            )
        else:
            raise ValueError("Mann-Whitney U needs two non-empty samples")


def compute_cohen_d(first: Sequence[float], second: Sequence[float]) -> float:
    if first and second:
        mean_difference = float(np.mean(first)) - float(np.mean(second))
        pooled_std = math.sqrt(
            (float(np.var(first)) + float(np.var(second))) / 2
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            return float(np.divide(mean_difference, pooled_std))
    else:
        raise ValueError("Cohen's d needs two non-empty samples")
