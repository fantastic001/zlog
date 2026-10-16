import json
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

import yaml

from zlog.capture_names import parse_capture_name
from zlog.domain import AnalysisSpec, PatternSpec
from zlog.errors import SpecError

LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_SPEC_BYTES = 1024 * 1024

SpecDecoder = Callable[[str], object]

SPEC_DECODERS: Mapping[str, SpecDecoder] = MappingProxyType(
    {
        ".yaml": yaml.safe_load,
        ".yml": yaml.safe_load,
        ".json": json.loads,
    }
)
FALLBACK_SPEC_DECODER: SpecDecoder = yaml.safe_load


def require_string_list(value: object, field_name: str) -> tuple[str, ...]:
    match value:
        case list() if all(isinstance(item, str) for item in value):
            return tuple(value)
        case _:
            raise SpecError(f"'{field_name}' must be a list of strings")


def require_string_mapping(value: object, field_name: str) -> Mapping[str, str]:
    match value:
        case dict() if all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in value.items()
        ):
            return MappingProxyType(dict(value))
        case _:
            raise SpecError(f"'{field_name}' must map strings to strings")


class SpecParser:
    def parse(self, raw_spec: object) -> AnalysisSpec:
        match raw_spec:
            case dict():
                return self._parse_mapping(raw_spec)
            case _:
                raise SpecError("specification must be a mapping")

    def _parse_mapping(self, raw_spec: Mapping[str, object]) -> AnalysisSpec:
        raw_patterns = raw_spec.get("patterns", [])
        match raw_patterns:
            case list():
                patterns = tuple(
                    self._parse_pattern(raw_pattern, index)
                    for index, raw_pattern in enumerate(raw_patterns)
                )
            case _:
                raise SpecError("'patterns' must be a list")
        return AnalysisSpec(
            groups=require_string_list(raw_spec.get("groups", []), "groups"),
            patterns=patterns,
            macros=require_string_mapping(raw_spec.get("macros", {}), "macros"),
            iteration_separator=self._parse_iteration_separator(
                raw_spec.get("iteration_separator")
            ),
        )

    @staticmethod
    def _parse_capture_names(raw_names: object, index: int) -> tuple[str, ...]:
        names = require_string_list(raw_names, f"patterns[{index}].names")
        try:
            for name in names:
                parse_capture_name(name)
        except ValueError as error:
            raise SpecError(f"patterns[{index}].names: {error}") from error
        else:
            return names

    @staticmethod
    def _parse_iteration_separator(raw_separator: object) -> str | None:
        match raw_separator:
            case None:
                return None
            case str() as separator if separator:
                return separator
            case _:
                raise SpecError(
                    "'iteration_separator' must be a non-empty regex string"
                )

    def _parse_pattern(self, raw_pattern: object, index: int) -> PatternSpec:
        match raw_pattern:
            case {"regex": str() as regex, "names": names} if regex:
                return PatternSpec(
                    regex=regex,
                    names=self._parse_capture_names(names, index),
                )
            case _:
                raise SpecError(
                    f"patterns[{index}] needs a non-empty 'regex' "
                    "string and a 'names' list"
                )


class SpecLoader:
    def __init__(
        self,
        parser: SpecParser,
        decoders: Mapping[str, SpecDecoder] = SPEC_DECODERS,
        max_spec_bytes: int = DEFAULT_MAX_SPEC_BYTES,
    ) -> None:
        self._parser = parser
        self._decoders = decoders
        self._max_spec_bytes = max_spec_bytes

    def load(self, spec_file: Path) -> AnalysisSpec:
        LOGGER.info("loading specification %s", spec_file)
        decoder = self._decoders.get(
            spec_file.suffix.lower(), FALLBACK_SPEC_DECODER
        )
        raw_spec = self._decode(decoder, self._read_text(spec_file))
        spec = self._parser.parse(raw_spec)
        LOGGER.info("loaded specification %s: %s", spec_file, spec)
        return spec

    def _read_text(self, spec_file: Path) -> str:
        try:
            size = spec_file.stat().st_size
            if size <= self._max_spec_bytes:
                return spec_file.read_text(encoding="utf-8")
            else:
                raise SpecError(
                    f"specification {spec_file} has {size} bytes, "
                    f"limit is {self._max_spec_bytes}"
                )
        except (OSError, UnicodeDecodeError) as error:
            raise SpecError(
                f"cannot read specification {spec_file}: {error}"
            ) from error

    @staticmethod
    def _decode(decoder: SpecDecoder, text: str) -> object:
        try:
            return decoder(text)
        except (yaml.YAMLError, ValueError) as error:
            raise SpecError(f"cannot decode specification: {error}") from error
