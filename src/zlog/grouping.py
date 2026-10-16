import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from zlog.capture_names import parse_capture_name
from zlog.domain import AnalysisSpec, ExtractedValue, GroupKey

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GroupNamePartition:
    directory_groups: tuple[str, ...]
    extracted_groups: tuple[str, ...]


def partition_group_names(spec: AnalysisSpec) -> GroupNamePartition:
    pattern_names = {
        parse_capture_name(name).name
        for pattern in spec.patterns
        for name in pattern.names
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
        self, directory_key: GroupKey, values: Mapping[str, ExtractedValue]
    ) -> GroupKey | None:
        directory_labels = dict(directory_key)
        labelled_names = (
            (name, self._find_label(name, directory_labels, values))
            for name in self._group_names
        )
        key = tuple(
            (name, label) for name, label in labelled_names if label is not None
        )
        if len(key) == len(self._group_names):
            return key
        else:
            return None

    def select_metric_values(
        self, values: Mapping[str, ExtractedValue]
    ) -> dict[str, ExtractedValue]:
        return {
            name: value
            for name, value in values.items()
            if name not in self._extracted_group_names
        }

    def _find_label(
        self,
        name: str,
        directory_labels: Mapping[str, str],
        values: Mapping[str, ExtractedValue],
    ) -> str | None:
        source = self._select_label_source(name, directory_labels, values)
        match source.get(name):
            case str() as label:
                return label
            case None:
                return None
            case list_value:
                LOGGER.warning(
                    "group %r has list value %s; cannot label", name, list_value
                )
                return None

    def _select_label_source(
        self,
        name: str,
        directory_labels: Mapping[str, str],
        values: Mapping[str, ExtractedValue],
    ) -> Mapping[str, ExtractedValue]:
        if name in self._extracted_group_names:
            return values
        else:
            return directory_labels
