import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from zlog.errors import SpecError

LOGGER = logging.getLogger(__name__)

IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CAPTURE_NAME_PATTERN = re.compile(
    rf"(?P<prefix>[^A-Za-z0-9_]*)(?P<group_name>{IDENTIFIER_PATTERN.pattern})"
)
LITERAL_PERCENT = "%"

INTEGER_REGEX = r"[+-]?\d+"
FLOAT_REGEX = (
    r"[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    r"|(?i:\bnan\b|\binf(?:inity)?\b))"
)
HEXADECIMAL_REGEX = r"(?:0[xX])?[0-9A-Fa-f]+"
NON_SPACE_REGEX = r"\S+"
WORD_REGEX = r"\w+"
REST_OF_LINE_REGEX = r".*"

BUILTIN_PATTERN_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "d": INTEGER_REGEX,
        "f": FLOAT_REGEX,
        "x": HEXADECIMAL_REGEX,
        "s": NON_SPACE_REGEX,
        "w": WORD_REGEX,
        "r": REST_OF_LINE_REGEX,
    }
)

ALIAS_TOKEN_PATTERN = re.compile(
    r"(?P<escaped>\\.)"
    r"|%(?:"
    r"(?P<percent>%)"
    r"|(?:(?P<suppressed>\*)|\((?P<capture>[^()]*)\))?"
    r"(?:\{(?P<long_alias>[^{}]*)\}|(?P<short_alias>[A-Za-z]))"
    r"|(?P<incomplete>[*({])"
    r")",
    re.DOTALL,
)


class CaptureMode(Enum):
    POSITIONAL = "positional"
    NAMED = "named"
    SUPPRESSED = "suppressed"


CAPTURE_TEMPLATES: Mapping[CaptureMode, str] = MappingProxyType(
    {
        CaptureMode.POSITIONAL: "({regex})",
        CaptureMode.NAMED: "(?P<{name}>{regex})",
        CaptureMode.SUPPRESSED: "(?:{regex})",
    }
)


@dataclass(frozen=True)
class CaptureName:
    prefix: str
    group_name: str


def parse_capture_name(capture: str, pattern: str) -> CaptureName:
    found = CAPTURE_NAME_PATTERN.fullmatch(capture)
    if found is not None:
        return CaptureName(found.group("prefix"), found.group("group_name"))
    else:
        raise SpecError(
            f"capture name {capture!r} in {pattern!r} must be an optional "
            f"prefix followed by a name matching {IDENTIFIER_PATTERN.pattern}; "
            "bind other names explicitly, e.g. %f with record: {NAME: 1}"
        )


def find_capture_names(pattern: str) -> tuple[CaptureName, ...]:
    assert isinstance(pattern, str), "pattern must be a string"
    return tuple(
        parse_capture_name(capture, pattern)
        for token in ALIAS_TOKEN_PATTERN.finditer(pattern)
        if (capture := token.group("capture")) is not None
    )


def validate_pattern_alias(name: str, regex: str) -> None:
    assert isinstance(name, str), "alias name must be a string"
    assert isinstance(regex, str), "alias regex must be a string"
    if IDENTIFIER_PATTERN.fullmatch(name) is not None:
        LOGGER.debug("pattern alias name %r is valid", name)
    else:
        raise SpecError(
            f"pattern alias name {name!r} must match "
            f"{IDENTIFIER_PATTERN.pattern}"
        )
    try:
        group_count = re.compile(regex).groups
    except re.error as error:
        raise SpecError(
            f"pattern alias {name!r}: invalid regex {regex!r}: {error}"
        ) from error
    if group_count == 0:
        LOGGER.debug("pattern alias %r expands to %r", name, regex)
    else:
        raise SpecError(
            f"pattern alias {name!r} has {group_count} capturing groups; "
            "write (?:...) inside an alias"
        )


class PatternAliasExpander:
    def __init__(
        self, aliases: Mapping[str, str] = BUILTIN_PATTERN_ALIASES
    ) -> None:
        for name, regex in aliases.items():
            validate_pattern_alias(name, regex)
        self._aliases: Mapping[str, str] = MappingProxyType(dict(aliases))

    def with_additional_aliases(
        self, extra_aliases: Mapping[str, str]
    ) -> "PatternAliasExpander":
        return PatternAliasExpander({**self._aliases, **extra_aliases})

    def expand(self, pattern: str) -> str:
        assert isinstance(pattern, str), "pattern must be a string"
        return ALIAS_TOKEN_PATTERN.sub(
            lambda token: self._render_token(token, pattern), pattern
        )

    def compile(self, pattern: str) -> re.Pattern[str]:
        expanded = self.expand(pattern)
        try:
            compiled = re.compile(expanded)
        except re.error as error:
            raise SpecError(
                f"invalid regex {pattern!r} (expanded to {expanded!r}): {error}"
            ) from error
        else:
            LOGGER.debug("expanded pattern %r to %r", pattern, expanded)
            return compiled

    def _render_token(self, token: re.Match[str], pattern: str) -> str:
        match token.lastgroup:
            case "escaped":
                return token.group()
            case "percent":
                return LITERAL_PERCENT
            case "short_alias" | "long_alias":
                return self._render_alias(token, pattern)
            case _:
                raise SpecError(
                    f"incomplete alias {token.group()!r} at position "
                    f"{token.start()} in {pattern!r}; expected %x, %*x, "
                    "%(name)x or %{alias}, or %% for a literal %"
                )

    def _render_alias(self, token: re.Match[str], pattern: str) -> str:
        alias_name = token.group("short_alias") or token.group("long_alias")
        regex = self._find_alias_regex(alias_name, pattern)
        mode, group_name = self._resolve_capture(token, pattern)
        return CAPTURE_TEMPLATES[mode].format(name=group_name, regex=regex)

    def _find_alias_regex(self, alias_name: str, pattern: str) -> str:
        try:
            return self._aliases[alias_name]
        except KeyError as error:
            available = ", ".join(sorted(self._aliases))
            raise SpecError(
                f"unknown pattern alias {alias_name!r} in {pattern!r}; "
                f"available: {available}; write %% for a literal %"
            ) from error

    @staticmethod
    def _resolve_capture(
        token: re.Match[str], pattern: str
    ) -> tuple[CaptureMode, str | None]:
        match (token.group("suppressed"), token.group("capture")):
            case (None, None):
                return CaptureMode.POSITIONAL, None
            case (None, str() as capture):
                capture_name = parse_capture_name(capture, pattern)
                return CaptureMode.NAMED, capture_name.group_name
            case _:
                return CaptureMode.SUPPRESSED, None
