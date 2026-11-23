import logging
import re
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ConstantSource:
    text: str

    def validate(self, regex: re.Pattern[str]) -> None:
        LOGGER.debug(
            "constant %r needs no group of %s", self.text, regex.pattern
        )

    def resolve(self, found: re.Match[str]) -> str | None:
        return self.text
