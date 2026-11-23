import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from zlog.context_updates import ContextUpdate
from zlog.errors import InvalidValueError, SpecError
from zlog.options import ResetScope
from zlog.rules import Binding, ColumnLayout, MatchRule, ResetSelection
from zlog.value_sources import ConstantSource, ValueSource

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompiledContextBinding:
    name: str
    source: ValueSource
    update: ContextUpdate


@dataclass(frozen=True)
class CompiledRecordBinding:
    name: str
    source: ValueSource


@dataclass(frozen=True)
class CompiledRule:
    index: int
    regex: re.Pattern[str]
    reset: frozenset[str]
    context: tuple[CompiledContextBinding, ...]
    record: tuple[CompiledRecordBinding, ...]


class PatternCompiler(Protocol):
    def compile(self, pattern: str) -> re.Pattern[str]: ...


class RuleCompiler:
    def __init__(
        self,
        patterns: PatternCompiler,
        updates: Mapping[str, ContextUpdate],
    ) -> None:
        self._patterns = patterns
        self._updates = updates

    def compile(
        self, rules: tuple[MatchRule, ...], layout: ColumnLayout
    ) -> tuple[CompiledRule, ...]:
        compiled = tuple(
            self._compile_rule(index, rule, layout)
            for index, rule in enumerate(rules)
        )
        LOGGER.info("compiled %d rules", len(compiled))
        return compiled

    def _compile_rule(
        self, index: int, rule: MatchRule, layout: ColumnLayout
    ) -> CompiledRule:
        regex = self._patterns.compile(rule.pattern)
        for binding in (*rule.context, *rule.record):
            binding.source.validate(regex)
        compiled = CompiledRule(
            index=index,
            regex=regex,
            reset=self._resolve_reset(rule.reset, layout),
            context=tuple(map(self._compile_context_binding, rule.context)),
            record=tuple(
                CompiledRecordBinding(binding.variable.name, binding.source)
                for binding in rule.record
            ),
        )
        LOGGER.debug("compiled rule %d: %s", index, regex.pattern)
        return compiled

    def _compile_context_binding(
        self, binding: Binding
    ) -> CompiledContextBinding:
        update = self._updates[binding.variable.prefix]
        match binding.source:
            case ConstantSource(text=constant):
                self._check_constant_update(binding, update, constant)
            case _:
                LOGGER.debug("binding %s reads a group", binding.variable)
        return CompiledContextBinding(
            binding.variable.name, binding.source, update
        )

    @staticmethod
    def _check_constant_update(
        binding: Binding, update: ContextUpdate, constant: str
    ) -> None:
        try:
            update.apply(None, constant)
        except InvalidValueError as error:
            raise SpecError(
                f"context variable "
                f"{binding.variable.prefix}{binding.variable.name}: {error}"
            ) from error
        else:
            LOGGER.debug("constant %r accepted by %r", constant, update)

    @staticmethod
    def _resolve_reset(
        reset: ResetSelection, layout: ColumnLayout
    ) -> frozenset[str]:
        match reset.scope:
            case ResetScope.NONE:
                return frozenset()
            case ResetScope.ALL:
                return frozenset(layout.context)
            case ResetScope.LISTED:
                return frozenset(reset.names)
