import re
from collections.abc import Mapping
from types import MappingProxyType

from zlog.errors import SpecError

FLOAT_REGEX = r"[+-]?(?:\d*\.?\d+|\b(?:nan|inf(?:inity)?)\b)"
UP_TO_COLON_REGEX = r"[^:]*:"
OPTIONAL_WHITESPACE_REGEX = r"\s*"

DEFAULT_REGEX_MACROS: Mapping[str, str] = MappingProxyType(
    {
        r"\f": FLOAT_REGEX,
        r"\:": UP_TO_COLON_REGEX,
        r"\s": OPTIONAL_WHITESPACE_REGEX,
    }
)


class RegexMacroExpander:
    def __init__(
        self, macros: Mapping[str, str] = DEFAULT_REGEX_MACROS
    ) -> None:
        self._macros = dict(macros)

    def with_additional_macros(
        self, extra_macros: Mapping[str, str]
    ) -> "RegexMacroExpander":
        return RegexMacroExpander({**self._macros, **extra_macros})

    def expand(self, regex: str) -> str:
        assert isinstance(regex, str), "regex must be a string"
        expanded = regex
        for macro, replacement in self._macros.items():
            expanded = expanded.replace(macro, replacement)
        return expanded

    def compile(self, regex: str) -> re.Pattern[str]:
        expanded = self.expand(regex)
        try:
            return re.compile(expanded)
        except re.error as error:
            raise SpecError(
                f"invalid regex {regex!r} (expanded to {expanded!r}): {error}"
            ) from error
