from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from zlog.options import AssignmentMode

CAPTURE_NAME_PREFIXES: Mapping[str, AssignmentMode] = MappingProxyType(
    {
        "+": AssignmentMode.APPEND,
        "": AssignmentMode.REPLACE,
    }
)


@dataclass(frozen=True)
class CaptureTarget:
    name: str
    mode: AssignmentMode


def parse_capture_name(raw_name: str) -> CaptureTarget:
    prefix = max(
        (
            candidate
            for candidate in CAPTURE_NAME_PREFIXES
            if raw_name.startswith(candidate)
        ),
        key=len,
    )
    name = raw_name.removeprefix(prefix)
    if name:
        return CaptureTarget(name, CAPTURE_NAME_PREFIXES[prefix])
    else:
        raise ValueError(f"capture name {raw_name!r} has no name after prefix")
