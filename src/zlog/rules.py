from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from zlog.options import ResetScope
from zlog.value_sources import ValueSource
from zlog.variable_names import VariableName


@dataclass(frozen=True)
class Binding:
    variable: VariableName
    source: ValueSource


@dataclass(frozen=True)
class ResetSelection:
    scope: ResetScope = ResetScope.NONE
    names: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchRule:
    pattern: str
    reset: ResetSelection = ResetSelection()
    context: tuple[Binding, ...] = ()
    record: tuple[Binding, ...] = ()


@dataclass(frozen=True)
class ExtractionSpec:
    matches: tuple[MatchRule, ...] = ()
    aliases: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def with_additional_matches(
        self, extra_matches: Sequence[MatchRule]
    ) -> "ExtractionSpec":
        return ExtractionSpec((*self.matches, *extra_matches), self.aliases)

    @property
    def context_names(self) -> tuple[str, ...]:
        return collect_names_in_order(rule.context for rule in self.matches)

    @property
    def record_names(self) -> tuple[str, ...]:
        return collect_names_in_order(rule.record for rule in self.matches)


def collect_names_in_order(
    binding_groups: Iterable[tuple[Binding, ...]],
) -> tuple[str, ...]:
    names = (
        binding.variable.name
        for bindings in binding_groups
        for binding in bindings
    )
    return tuple(dict.fromkeys(names))


@dataclass(frozen=True)
class ColumnLayout:
    path_column: str
    context: tuple[str, ...]
    record: tuple[str, ...]

    @property
    def header(self) -> tuple[str, ...]:
        return (self.path_column, *self.context, *self.record)

    def arrange(
        self,
        path: str,
        context: Mapping[str, str],
        record: Mapping[str, str],
    ) -> tuple[str | None, ...]:
        return (
            path,
            *(context.get(name) for name in self.context),
            *(record.get(name) for name in self.record),
        )


def derive_column_layout(
    spec: ExtractionSpec, path_column: str
) -> ColumnLayout:
    return ColumnLayout(path_column, spec.context_names, spec.record_names)
