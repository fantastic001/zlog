import logging
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from zlog.errors import SpecError
from zlog.options import ResetScope
from zlog.rule_factory import MatchRuleFactory, RawBinding
from zlog.rules import ExtractionSpec, MatchRule, ResetSelection
from zlog.value_sources import ConstantSource, GroupSource, ValueSource

LOGGER = logging.getLogger(__name__)

MATCHES_KEY = "matches"
ALIASES_KEY = "aliases"
SPEC_KEYS = frozenset({MATCHES_KEY, ALIASES_KEY})
PATTERN_KEY = "pattern"
RESET_KEY = "reset"
CONTEXT_KEY = "context"
RECORD_KEY = "record"
MATCH_KEYS = frozenset({PATTERN_KEY, RESET_KEY, CONTEXT_KEY, RECORD_KEY})
CONSTANT_KEY = "value"
RESET_ALL_KEYWORD = "all"
LEGACY_SPEC_KEYS = frozenset(
    {"groups", "patterns", "iteration_separator", "report"}
)
NO_RESET = ResetSelection()


def format_constant(value: object, field_name: str) -> str:
    match value:
        case bool() | None:
            raise SpecError(
                f"{field_name}: constant {value!r} is not text or a number; "
                "quote it to use it as text"
            )
        case str():
            return value
        case int():
            return str(value)
        case float():
            return repr(value)
        case _:
            raise SpecError(f"{field_name}: constant must be a scalar")


def parse_value_source(raw_source: object, field_name: str) -> ValueSource:
    match raw_source:
        case bool():
            raise SpecError(f"{field_name}: {raw_source!r} is not a group")
        case int() as index if index >= 0:
            return GroupSource(index)
        case str() as name if name:
            return GroupSource(name)
        case dict() if set(raw_source) == {CONSTANT_KEY}:
            return ConstantSource(
                format_constant(raw_source[CONSTANT_KEY], field_name)
            )
        case _:
            raise SpecError(
                f"{field_name}: expected a group index, a group name or "
                f"{{{CONSTANT_KEY}: ...}}, got {raw_source!r}"
            )


def require_string_mapping(value: object, field_name: str) -> Mapping[str, str]:
    match value:
        case dict() if all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in value.items()
        ):
            return MappingProxyType(dict(value))
        case _:
            raise SpecError(f"'{field_name}' must map strings to strings")


def reject_unknown_keys(
    raw: Mapping[Any, object], allowed: frozenset[str], field_name: str
) -> None:
    unknown = sorted(map(str, set(raw) - allowed))
    if not unknown:
        LOGGER.debug("%s has only known keys", field_name)
    else:
        raise SpecError(
            f"{field_name}: unknown keys {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(allowed))}"
        )


class SpecParser:
    def __init__(self, factory: MatchRuleFactory) -> None:
        self._factory = factory

    def parse(self, raw_spec: object) -> ExtractionSpec:
        match raw_spec:
            case dict() if MATCHES_KEY in raw_spec:
                return self._parse_mapping(raw_spec)
            case dict() if LEGACY_SPEC_KEYS & set(raw_spec):
                raise SpecError(
                    "this is an old zlog specification (groups/patterns); "
                    "see 'Migrating from the old format' in the README"
                )
            case _:
                raise SpecError(
                    f"specification must be a mapping with '{MATCHES_KEY}'"
                )

    def _parse_mapping(self, raw_spec: Mapping[str, object]) -> ExtractionSpec:
        reject_unknown_keys(raw_spec, SPEC_KEYS, "specification")
        match raw_spec[MATCHES_KEY]:
            case list() as raw_matches if raw_matches:
                matches = tuple(
                    self._parse_match(raw_match, f"{MATCHES_KEY}[{index}]")
                    for index, raw_match in enumerate(raw_matches)
                )
            case _:
                raise SpecError(f"'{MATCHES_KEY}' must be a non-empty list")
        return ExtractionSpec(
            matches=matches,
            aliases=require_string_mapping(
                raw_spec.get(ALIASES_KEY, {}), ALIASES_KEY
            ),
        )

    def _parse_match(self, raw_match: object, field_name: str) -> MatchRule:
        match raw_match:
            case dict():
                return self._parse_match_mapping(raw_match, field_name)
            case _:
                raise SpecError(f"{field_name} must be a mapping")

    def _parse_match_mapping(
        self, raw_match: Mapping[Any, object], field_name: str
    ) -> MatchRule:
        pattern = raw_match.get(PATTERN_KEY)
        if isinstance(pattern, str):
            reject_unknown_keys(raw_match, MATCH_KEYS, field_name)
            return self._factory.create(
                pattern,
                self._parse_reset(raw_match.get(RESET_KEY), field_name),
                self._parse_bindings(raw_match, CONTEXT_KEY, field_name),
                self._parse_bindings(raw_match, RECORD_KEY, field_name),
            )
        else:
            raise SpecError(f"{field_name} needs a '{PATTERN_KEY}' string")

    @staticmethod
    def _parse_bindings(
        raw_match: Mapping[Any, object], section_key: str, field_name: str
    ) -> tuple[RawBinding, ...]:
        section_field = f"{field_name}.{section_key}"
        match raw_match.get(section_key, {}):
            case dict() as raw_bindings if all(
                isinstance(name, str) for name in raw_bindings
            ):
                return tuple(
                    (name, parse_value_source(raw, f"{section_field}.{name}"))
                    for name, raw in raw_bindings.items()
                )
            case _:
                raise SpecError(
                    f"{section_field} must map variable names to sources"
                )

    @staticmethod
    def _parse_reset(raw_reset: object, field_name: str) -> ResetSelection:
        match raw_reset:
            case None:
                return NO_RESET
            case str() if raw_reset == RESET_ALL_KEYWORD:
                return ResetSelection(ResetScope.ALL)
            case list() if raw_reset and all(
                isinstance(name, str) for name in raw_reset
            ):
                return ResetSelection(ResetScope.LISTED, tuple(raw_reset))
            case _:
                raise SpecError(
                    f"{field_name}.{RESET_KEY} must be "
                    f"'{RESET_ALL_KEYWORD}' or a non-empty list of names"
                )
