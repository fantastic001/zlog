import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from zlog.errors import SpecError
from zlog.options import BindingSection
from zlog.pattern_aliases import CaptureName, find_capture_names
from zlog.rule_factory import MatchRuleFactory, RawBinding, RuleFactory
from zlog.rules import MatchRule, ResetSelection
from zlog.value_sources import GroupSource
from zlog.variable_names import REPLACE_PREFIX

LOGGER = logging.getLogger(__name__)

RECORD_CAPTURE_PREFIX = ""
CONTEXT_REPLACE_CAPTURE_PREFIX = "="


@dataclass(frozen=True)
class CaptureDestination:
    section: BindingSection
    variable_prefix: str


@dataclass(frozen=True)
class CapturedBindings:
    context: tuple[RawBinding, ...] = ()
    record: tuple[RawBinding, ...] = ()


def build_capture_destinations(
    context_prefixes: Collection[str],
) -> Mapping[str, CaptureDestination]:
    destinations = {
        prefix: CaptureDestination(BindingSection.CONTEXT, prefix)
        for prefix in context_prefixes
        if prefix != REPLACE_PREFIX
    }
    destinations[RECORD_CAPTURE_PREFIX] = CaptureDestination(
        BindingSection.RECORD, REPLACE_PREFIX
    )
    destinations[CONTEXT_REPLACE_CAPTURE_PREFIX] = CaptureDestination(
        BindingSection.CONTEXT, REPLACE_PREFIX
    )
    return MappingProxyType(destinations)


class CaptureBindingScanner:
    def __init__(self, context_prefixes: Collection[str]) -> None:
        self._destinations = build_capture_destinations(context_prefixes)

    def scan(self, pattern: str) -> CapturedBindings:
        bindings: dict[BindingSection, list[RawBinding]] = {
            section: [] for section in BindingSection
        }
        for capture_name in find_capture_names(pattern):
            destination = self._find_destination(capture_name, pattern)
            bindings[destination.section].append(
                (
                    destination.variable_prefix + capture_name.group_name,
                    GroupSource(capture_name.group_name),
                )
            )
        captured = CapturedBindings(
            tuple(bindings[BindingSection.CONTEXT]),
            tuple(bindings[BindingSection.RECORD]),
        )
        LOGGER.debug("captures of %r bind %s", pattern, captured)
        return captured

    def _find_destination(
        self, capture_name: CaptureName, pattern: str
    ) -> CaptureDestination:
        try:
            return self._destinations[capture_name.prefix]
        except KeyError as error:
            context_prefixes = ", ".join(
                repr(prefix)
                for prefix in sorted(self._destinations)
                if prefix != RECORD_CAPTURE_PREFIX
            )
            raise SpecError(
                f"rule {pattern!r}: unknown capture prefix "
                f"{capture_name.prefix!r} before {capture_name.group_name!r}; "
                f"write no prefix for a record variable or one of "
                f"{context_prefixes} for a context variable"
            ) from error


class CaptureBindingRuleFactory:
    def __init__(
        self, rules: RuleFactory, scanner: CaptureBindingScanner
    ) -> None:
        self._rules = rules
        self._scanner = scanner

    def create(
        self,
        pattern: str,
        reset: ResetSelection,
        context: Sequence[RawBinding],
        record: Sequence[RawBinding],
    ) -> MatchRule:
        captured = self._scanner.scan(pattern)
        return self._rules.create(
            pattern,
            reset,
            (*captured.context, *context),
            (*captured.record, *record),
        )


def create_rule_factory(
    context_prefixes: Collection[str],
) -> CaptureBindingRuleFactory:
    return CaptureBindingRuleFactory(
        MatchRuleFactory(context_prefixes),
        CaptureBindingScanner(context_prefixes),
    )
