import logging
from collections.abc import Callable, Sequence

from zlog.errors import SpecError
from zlog.options import ResetScope
from zlog.rules import ExtractionSpec

LOGGER = logging.getLogger(__name__)

SpecCheck = Callable[[ExtractionSpec], list[str]]


class SpecConsistencyChecker:
    def __init__(self, path_column: str) -> None:
        self._path_column = path_column
        self._checks: Sequence[SpecCheck] = (
            self._find_missing_matches,
            self._find_section_overlap,
            self._find_reserved_names,
            self._find_unknown_reset_names,
        )

    def check(self, spec: ExtractionSpec) -> None:
        violations = [
            message for check in self._checks for message in check(spec)
        ]
        if not violations:
            LOGGER.debug("specification is consistent")
        else:
            raise SpecError("; ".join(violations))

    @staticmethod
    def _find_missing_matches(spec: ExtractionSpec) -> list[str]:
        return [] if spec.matches else ["no match rules given"]

    @staticmethod
    def _find_section_overlap(spec: ExtractionSpec) -> list[str]:
        overlap = sorted(set(spec.context_names) & set(spec.record_names))
        return [
            f"variable {name!r} is both a context and a record variable"
            for name in overlap
        ]

    def _find_reserved_names(self, spec: ExtractionSpec) -> list[str]:
        declared = {*spec.context_names, *spec.record_names}
        return [
            f"variable {name!r} is reserved for the input path"
            for name in sorted(declared & {self._path_column})
        ]

    @staticmethod
    def _find_unknown_reset_names(spec: ExtractionSpec) -> list[str]:
        declared = set(spec.context_names)
        return [
            f"rule {rule.pattern!r} resets undeclared context variable {name!r}"
            for rule in spec.matches
            if rule.reset.scope is ResetScope.LISTED
            for name in rule.reset.names
            if name not in declared
        ]
