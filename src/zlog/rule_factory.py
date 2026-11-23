import logging
from collections.abc import Collection, Sequence
from typing import Protocol

from zlog.errors import SpecError
from zlog.options import ResetScope
from zlog.rules import Binding, MatchRule, ResetSelection
from zlog.value_sources import ValueSource
from zlog.variable_names import (
    REPLACE_PREFIX,
    is_valid_variable_name,
    parse_variable_name,
)

LOGGER = logging.getLogger(__name__)

RawBinding = tuple[str, ValueSource]


class RuleFactory(Protocol):
    def create(
        self,
        pattern: str,
        reset: ResetSelection,
        context: Sequence[RawBinding],
        record: Sequence[RawBinding],
    ) -> MatchRule: ...


def find_duplicates(names: Sequence[str]) -> list[str]:
    return sorted({name for name in names if names.count(name) > 1})


class MatchRuleFactory:
    def __init__(self, context_prefixes: Collection[str]) -> None:
        self._context_prefixes = frozenset(context_prefixes)

    def create(
        self,
        pattern: str,
        reset: ResetSelection,
        context: Sequence[RawBinding],
        record: Sequence[RawBinding],
    ) -> MatchRule:
        if isinstance(pattern, str) and pattern:
            rule = MatchRule(
                pattern=pattern,
                reset=self._validate_reset(reset, pattern),
                context=self._create_context_bindings(context, pattern),
                record=self._create_record_bindings(record, pattern),
            )
            LOGGER.debug("created rule %s", rule)
            return rule
        else:
            raise SpecError("a match rule needs a non-empty pattern string")

    def _create_context_bindings(
        self, raw_bindings: Sequence[RawBinding], pattern: str
    ) -> tuple[Binding, ...]:
        bindings = self._parse_bindings(raw_bindings)
        self._reject_duplicate_names(bindings, "context", pattern)
        return bindings

    def _create_record_bindings(
        self, raw_bindings: Sequence[RawBinding], pattern: str
    ) -> tuple[Binding, ...]:
        bindings = self._parse_bindings(raw_bindings)
        prefixed = [
            binding.variable.prefix + binding.variable.name
            for binding in bindings
            if binding.variable.prefix != REPLACE_PREFIX
        ]
        if not prefixed:
            self._reject_duplicate_names(bindings, "record", pattern)
            return bindings
        else:
            raise SpecError(
                f"rule {pattern!r}: record variables take no prefix, "
                f"got {', '.join(prefixed)}"
            )

    def _parse_bindings(
        self, raw_bindings: Sequence[RawBinding]
    ) -> tuple[Binding, ...]:
        return tuple(
            Binding(parse_variable_name(name, self._context_prefixes), source)
            for name, source in raw_bindings
        )

    @staticmethod
    def _reject_duplicate_names(
        bindings: Sequence[Binding], section: str, pattern: str
    ) -> None:
        duplicates = find_duplicates(
            [binding.variable.name for binding in bindings]
        )
        if not duplicates:
            LOGGER.debug("rule %r %s names are unique", pattern, section)
        else:
            raise SpecError(
                f"rule {pattern!r}: duplicate {section} variables "
                f"{', '.join(duplicates)}"
            )

    @staticmethod
    def _validate_reset(reset: ResetSelection, pattern: str) -> ResetSelection:
        invalid = [
            name for name in reset.names if not is_valid_variable_name(name)
        ]
        duplicates = find_duplicates(list(reset.names))
        names_expected = reset.scope is ResetScope.LISTED
        if (
            not invalid
            and not duplicates
            and names_expected == bool(reset.names)
        ):
            return reset
        else:
            raise SpecError(
                f"rule {pattern!r}: invalid reset {reset.scope.value} "
                f"with names {list(reset.names)}"
            )
