from collections.abc import Iterable
from dataclasses import dataclass

from zlog.domain import GroupKey


def find_varying_groups(groups: Iterable[GroupKey]) -> tuple[str, ...]:
    labels_by_name: dict[str, set[str]] = {}
    for group in groups:
        for name, label in group:
            labels_by_name.setdefault(name, set()).add(label)
    return tuple(
        name for name, labels in labels_by_name.items() if len(labels) > 1
    )


@dataclass(frozen=True)
class GroupLabeler:
    shown_names: tuple[str, ...]

    @classmethod
    def for_varying_groups(cls, groups: Iterable[GroupKey]) -> "GroupLabeler":
        return cls(find_varying_groups(groups))

    def label(self, group: GroupKey) -> str:
        return ", ".join(
            label for name, label in group if name in self.shown_names
        )

    def without(self, hidden_name: str | None) -> "GroupLabeler":
        return GroupLabeler(
            tuple(name for name in self.shown_names if name != hidden_name)
        )

    def find_hidden_names(self, groups: Iterable[GroupKey]) -> frozenset[str]:
        return frozenset(
            name
            for group in groups
            for name, _ in group
            if name not in self.shown_names
        )
