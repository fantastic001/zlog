from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

GroupKey = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PatternSpec:
    regex: str
    names: tuple[str, ...]


@dataclass(frozen=True)
class AnalysisSpec:
    groups: tuple[str, ...]
    patterns: tuple[PatternSpec, ...]
    macros: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True)
class IterationSource:
    iteration: int
    path: Path


@dataclass(frozen=True)
class GroupRun:
    key: GroupKey
    directory: Path
    sources: tuple[IterationSource, ...]


@dataclass(frozen=True)
class IterationRecord:
    group: GroupKey
    iteration: int
    values: Mapping[str, str]


@dataclass(frozen=True)
class MetricSummary:
    mean: float
    std: float
    values: tuple[float, ...]

    @property
    def count(self) -> int:
        return len(self.values)


Summary = Mapping[GroupKey, Mapping[str, MetricSummary]]


def format_group_label(group: GroupKey) -> str:
    return ", ".join(value for _, value in group)
