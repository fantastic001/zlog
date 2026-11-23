import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from zlog.compilation import CompiledContextBinding, CompiledRule
from zlog.context_state import ContextState
from zlog.errors import InvalidValueError

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchedLine:
    rule_index: int
    context: Mapping[str, str]
    record: Mapping[str, str]


class LineProcessor:
    def __init__(
        self, rules: Sequence[CompiledRule], state: ContextState
    ) -> None:
        self._rules = tuple(rules)
        self._state = state

    def process(self, line: str) -> MatchedLine | None:
        for rule in self._rules:
            found = rule.regex.search(line)
            if found is not None:
                return self._apply_rule(rule, found)
            else:
                continue
        LOGGER.debug("no rule matches %r", line)
        return None

    def _apply_rule(
        self, rule: CompiledRule, found: re.Match[str]
    ) -> MatchedLine:
        self._state.reset(rule.reset)
        for binding in rule.context:
            self._update_context(binding, found)
        record = {
            binding.name: value
            for binding in rule.record
            if (value := binding.source.resolve(found)) is not None
        }
        LOGGER.debug("rule %d matched, record %s", rule.index, record)
        return MatchedLine(
            rule.index, self._state.snapshot(), MappingProxyType(record)
        )

    def _update_context(
        self, binding: CompiledContextBinding, found: re.Match[str]
    ) -> None:
        value = binding.source.resolve(found)
        if value is not None:
            self._update_or_name_variable(binding, value)
        else:
            LOGGER.debug("group for %s did not participate", binding.name)

    def _update_or_name_variable(
        self, binding: CompiledContextBinding, value: str
    ) -> None:
        try:
            self._state.update(binding.name, binding.update, value)
        except InvalidValueError as error:
            raise InvalidValueError(
                f"context variable {binding.name!r}: {error}"
            ) from error
