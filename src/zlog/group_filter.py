import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from zlog.domain import GroupKey, Summary
from zlog.errors import SpecError

LOGGER = logging.getLogger(__name__)

FilterAlternative = Mapping[str, frozenset[str]]

MATCH_ALL_ALTERNATIVE: FilterAlternative = MappingProxyType({})


@dataclass(frozen=True)
class GroupFilter:
    alternatives: tuple[FilterAlternative, ...] = (MATCH_ALL_ALTERNATIVE,)

    def matches(self, group: GroupKey) -> bool:
        labels = dict(group)
        return any(
            all(
                labels.get(name) in allowed_labels
                for name, allowed_labels in alternative.items()
            )
            for alternative in self.alternatives
        )

    def select_groups(self, summary: Summary) -> Summary:
        return {
            group: metrics
            for group, metrics in summary.items()
            if self.matches(group)
        }


MATCH_ALL_FILTER = GroupFilter()


def parse_filter_label(raw_label: object, field_name: str) -> str:
    match raw_label:
        case bool():
            raise SpecError(
                f"{field_name}: boolean label {raw_label!r} is ambiguous, "
                "quote it"
            )
        case str() | int() | float():
            return str(raw_label)
        case _:
            raise SpecError(f"{field_name} must be a label or list of labels")


class GroupFilterParser:
    def __init__(self, group_names: Sequence[str]) -> None:
        self._group_names = frozenset(group_names)

    def parse(self, raw_filter: object, field_name: str) -> GroupFilter:
        match raw_filter:
            case None:
                return MATCH_ALL_FILTER
            case dict():
                return GroupFilter(
                    (self._parse_alternative(raw_filter, field_name),)
                )
            case list() if raw_filter:
                return GroupFilter(
                    tuple(
                        self._parse_alternative(
                            raw_alternative, f"{field_name}[{index}]"
                        )
                        for index, raw_alternative in enumerate(raw_filter)
                    )
                )
            case _:
                raise SpecError(
                    f"{field_name} must be a mapping of group labels "
                    "or a non-empty list of such mappings"
                )

    def _parse_alternative(
        self, raw_alternative: object, field_name: str
    ) -> FilterAlternative:
        match raw_alternative:
            case dict():
                self._require_declared_groups(raw_alternative, field_name)
                return MappingProxyType(
                    {
                        str(name): self._parse_allowed_labels(
                            raw_labels, f"{field_name}.{name}"
                        )
                        for name, raw_labels in raw_alternative.items()
                    }
                )
            case _:
                raise SpecError(f"{field_name} must map group names to labels")

    def _require_declared_groups(
        self, raw_alternative: Mapping[object, object], field_name: str
    ) -> None:
        unknown_names = sorted(
            str(name)
            for name in raw_alternative
            if name not in self._group_names
        )
        if not unknown_names:
            LOGGER.debug("%s filters on %s", field_name, list(raw_alternative))
        else:
            raise SpecError(
                f"{field_name} uses undeclared groups: "
                f"{', '.join(unknown_names)}"
            )

    @staticmethod
    def _parse_allowed_labels(
        raw_labels: object, field_name: str
    ) -> frozenset[str]:
        match raw_labels:
            case list() if raw_labels:
                return frozenset(
                    parse_filter_label(raw_label, field_name)
                    for raw_label in raw_labels
                )
            case _:
                return frozenset((parse_filter_label(raw_labels, field_name),))
