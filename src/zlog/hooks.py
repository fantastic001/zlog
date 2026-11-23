import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from zlog.rules import ExtractionSpec

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractedRow:
    path: str
    line_number: int
    rule_index: int
    values: Mapping[str, str | None]


@dataclass(frozen=True)
class RunSummary:
    inputs_read: int
    lines_read: int
    rows_written: int
    matches_per_rule: tuple[int, ...]


@runtime_checkable
class LoadListener(Protocol):
    def on_load(self, spec: ExtractionSpec) -> None: ...


@runtime_checkable
class RowListener(Protocol):
    def on_row(self, row: ExtractedRow) -> None: ...


@runtime_checkable
class TerminationListener(Protocol):
    def on_terminate(self, summary: RunSummary) -> None: ...


class HookDispatcher:
    def __init__(self, hooks: Iterable[object]) -> None:
        registered = tuple(hooks)
        self._load_listeners = tuple(
            hook for hook in registered if isinstance(hook, LoadListener)
        )
        self._row_listeners = tuple(
            hook for hook in registered if isinstance(hook, RowListener)
        )
        self._termination_listeners = tuple(
            hook for hook in registered if isinstance(hook, TerminationListener)
        )

    @property
    def has_row_listeners(self) -> bool:
        return bool(self._row_listeners)

    def on_load(self, spec: ExtractionSpec) -> None:
        for listener in self._load_listeners:
            self._invoke_hook_safely(listener.on_load, spec)

    def on_row(self, row: ExtractedRow) -> None:
        for listener in self._row_listeners:
            self._invoke_hook_safely(listener.on_row, row)

    def on_terminate(self, summary: RunSummary) -> None:
        for listener in self._termination_listeners:
            self._invoke_hook_safely(listener.on_terminate, summary)

    @staticmethod
    def _invoke_hook_safely(
        callback: Callable[[Any], None], argument: object
    ) -> None:
        try:
            callback(argument)
        except Exception:
            LOGGER.exception("hook %r failed", callback)
