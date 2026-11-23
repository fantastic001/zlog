import re
from collections.abc import Collection
from dataclasses import dataclass

from zlog.errors import SpecError

VARIABLE_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
REPLACE_PREFIX = ""


@dataclass(frozen=True)
class VariableName:
    name: str
    prefix: str = REPLACE_PREFIX


def is_valid_variable_name(name: str) -> bool:
    return VARIABLE_NAME_PATTERN.fullmatch(name) is not None


def parse_variable_name(
    raw_name: str, prefixes: Collection[str]
) -> VariableName:
    assert isinstance(raw_name, str), "raw_name must be a string"
    prefix = max(
        (candidate for candidate in prefixes if raw_name.startswith(candidate)),
        key=len,
        default=REPLACE_PREFIX,
    )
    name = raw_name.removeprefix(prefix)
    if is_valid_variable_name(name):
        return VariableName(name, prefix)
    else:
        raise SpecError(
            f"invalid variable name {raw_name!r}: expected an optional "
            f"prefix ({', '.join(sorted(map(repr, prefixes)))}) followed "
            f"by a name matching {VARIABLE_NAME_PATTERN.pattern}"
        )
