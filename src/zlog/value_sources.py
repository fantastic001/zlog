import logging
import re
from dataclasses import dataclass
from functools import cache
from typing import Protocol

from zlog.errors import SpecError

LOGGER = logging.getLogger(__name__)

GroupReference = int | str


class ValueSource(Protocol):
    def validate(self, regex: re.Pattern[str]) -> None: ...

    def resolve(self, found: re.Match[str]) -> str | None: ...


@dataclass(frozen=True)
class GroupSource:
    reference: GroupReference

    def validate(self, regex: re.Pattern[str]) -> None:
        if self._exists_in(regex):
            LOGGER.debug("group %r found in %s", self.reference, regex.pattern)
        else:
            raise SpecError(
                f"pattern {regex.pattern!r} has no group {self.reference!r}"
            )

    def resolve(self, found: re.Match[str]) -> str | None:
        return found.group(self.reference)

    def _exists_in(self, regex: re.Pattern[str]) -> bool:
        match self.reference:
            case bool():
                return False
            case int() as index:
                return 0 <= index <= regex.groups
            case str() as name:
                return name in regex.groupindex


@cache
def list_unnamed_groups(regex: re.Pattern[str]) -> tuple[int, ...]:
    named = frozenset(regex.groupindex.values())
    return tuple(
        index for index in range(1, regex.groups + 1) if index not in named
    )


@dataclass(frozen=True)
class UnnamedGroupSource:
    ordinal: int

    def __post_init__(self) -> None:
        if self.ordinal >= 1:
            LOGGER.debug("unnamed group number %d requested", self.ordinal)
        else:
            raise ValueError("unnamed group ordinal must be at least 1")

    def validate(self, regex: re.Pattern[str]) -> None:
        unnamed_count = len(list_unnamed_groups(regex))
        if self.ordinal <= unnamed_count:
            LOGGER.debug(
                "unnamed group %d found in %s", self.ordinal, regex.pattern
            )
        else:
            raise SpecError(
                f"pattern {regex.pattern!r} has {unnamed_count} unnamed "
                f"groups, so bare name number {self.ordinal} has no group; "
                "write NAME=GROUP"
            )

    def resolve(self, found: re.Match[str]) -> str | None:
        return found.group(list_unnamed_groups(found.re)[self.ordinal - 1])


@dataclass(frozen=True)
class ConstantSource:
    text: str

    def validate(self, regex: re.Pattern[str]) -> None:
        LOGGER.debug(
            "constant %r needs no group of %s", self.text, regex.pattern
        )

    def resolve(self, found: re.Match[str]) -> str | None:
        return self.text
