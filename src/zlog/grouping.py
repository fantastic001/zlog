import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from zlog.domain import AnalysisSpec, GroupKey

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GroupNamePartition:
    directory_groups: tuple[str, ...]
    extracted_groups: tuple[str, ...]


def partition_group_names(spec: AnalysisSpec) -> GroupNamePartition:
    pattern_names = {
        name for pattern in spec.patterns for name in pattern.names
    }
    partition = GroupNamePartition(
        directory_groups=tuple(
            name for name in spec.groups if name not in pattern_names
        ),
        extracted_groups=tuple(
            name for name in spec.groups if name in pattern_names
        ),
    )
    LOGGER.debug("group name partition: %s", partition)
    return partition


class SegmentGroupResolver:
    def __init__(
        self,
        group_names: Sequence[str],
        extracted_group_names: Collection[str],
    ) -> None:
        if set(extracted_group_names) <= set(group_names):
            self._group_names = tuple(group_names)
            self._extracted_group_names = frozenset(extracted_group_names)
        else:
            raise ValueError("extracted groups must be declared groups")

    def resolve(
        self, directory_key: GroupKey, values: Mapping[str, str]
    ) -> GroupKey | None:
        directory_labels = dict(directory_key)
        labelled_names = (
            (name, self._select_label_source(name, directory_labels, values))
            for name in self._group_names
        )
        key = tuple(
            (name, source[name])
            for name, source in labelled_names
            if name in source
        )
        if len(key) == len(self._group_names):
            return key
        else:
            return None

    def select_metric_values(self, values: Mapping[str, str]) -> dict[str, str]:
        return {
            name: value
            for name, value in values.items()
            if name not in self._extracted_group_names
        }

    def _select_label_source(
        self,
        name: str,
        directory_labels: Mapping[str, str],
        values: Mapping[str, str],
    ) -> Mapping[str, str]:
        if name in self._extracted_group_names:
            return values
        else:
            return directory_labels
