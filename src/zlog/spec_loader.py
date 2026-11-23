import json
import logging
from collections import Counter
from collections.abc import Callable, Hashable, Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml
from yaml.constructor import ConstructorError

from zlog.errors import SpecError
from zlog.rules import ExtractionSpec
from zlog.spec_parser import SpecParser

LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_SPEC_BYTES = 1024 * 1024
SPEC_ENCODING = "utf-8"
YAML_MERGE_TAG = "tag:yaml.org,2002:merge"
DECODE_ERROR_HINTS: Mapping[str, str] = MappingProxyType(
    {
        "'@'": 'quote names that start with @, e.g. {"@warnings": 1}',
        "'`'": "quote values that start with a backtick",
        "'%'": "quote patterns that start with %, e.g. '%d items'",
    }
)

SpecDecoder = Callable[[str], object]


def find_duplicate_keys(keys: Iterable[object]) -> list[object]:
    counts = Counter(key for key in keys if isinstance(key, Hashable))
    return [key for key, count in counts.items() if count > 1]


class UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def construct_unique_mapping(
    loader: UniqueKeySafeLoader, node: yaml.MappingNode
) -> dict[Any, Any]:
    keys = [
        loader.construct_object(key_node, deep=True)
        for key_node, _ in node.value
        if key_node.tag != YAML_MERGE_TAG
    ]
    duplicates = find_duplicate_keys(keys)
    if not duplicates:
        return loader.construct_mapping(node, deep=True)
    else:
        raise ConstructorError(
            None,
            None,
            f"duplicate mapping keys {duplicates!r}",
            node.start_mark,
        )


UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping
)


def decode_yaml(text: str) -> object:
    return yaml.load(text, Loader=UniqueKeySafeLoader)


def reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    duplicates = find_duplicate_keys(key for key, _ in pairs)
    if not duplicates:
        return dict(pairs)
    else:
        raise ValueError(f"duplicate object keys {duplicates!r}")


def decode_json(text: str) -> object:
    return json.loads(text, object_pairs_hook=reject_duplicate_json_keys)


SPEC_DECODERS: Mapping[str, SpecDecoder] = MappingProxyType(
    {".yaml": decode_yaml, ".yml": decode_yaml, ".json": decode_json}
)
FALLBACK_SPEC_DECODER: SpecDecoder = decode_yaml


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

    def load(self, spec_file: Path) -> ExtractionSpec:
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
                return spec_file.read_text(encoding=SPEC_ENCODING)
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
            raise SpecError(
                f"cannot decode specification: {error}"
                f"{describe_decode_hints(str(error))}"
            ) from error


def describe_decode_hints(message: str) -> str:
    hints = [
        hint for marker, hint in DECODE_ERROR_HINTS.items() if marker in message
    ]
    return "".join(f"\nhint: {hint}" for hint in hints)
