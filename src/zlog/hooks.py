import logging
from collections.abc import Callable, Iterable
from typing import Any, Protocol, TextIO, runtime_checkable

from zlog.domain import AnalysisSpec, IterationRecord, Summary

LOGGER = logging.getLogger(__name__)


@runtime_checkable
class LoadListener(Protocol):
    def on_load(self, spec: AnalysisSpec) -> None: ...


@runtime_checkable
class IterationListener(Protocol):
    def on_iteration_analyzed(self, record: IterationRecord) -> None: ...


@runtime_checkable
class TerminationListener(Protocol):
    def on_terminate(self, summary: Summary) -> None: ...


class HookDispatcher:
    def __init__(self, hooks: Iterable[object]) -> None:
        registered = tuple(hooks)
        self._load_listeners = tuple(
            hook for hook in registered if isinstance(hook, LoadListener)
        )
        self._iteration_listeners = tuple(
            hook for hook in registered if isinstance(hook, IterationListener)
        )
        self._termination_listeners = tuple(
            hook for hook in registered if isinstance(hook, TerminationListener)
        )

    def on_load(self, spec: AnalysisSpec) -> None:
        for listener in self._load_listeners:
            self._invoke_hook_safely(listener.on_load, spec)

    def on_iteration_analyzed(self, record: IterationRecord) -> None:
        for listener in self._iteration_listeners:
            self._invoke_hook_safely(listener.on_iteration_analyzed, record)

    def on_terminate(self, summary: Summary) -> None:
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


class VerboseIterationPrinter:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def on_iteration_analyzed(self, record: IterationRecord) -> None:
        print(
            f"Group: {dict(record.group)}, "
            f"Iteration: {record.iteration}, "
            f"Segment: {record.segment}, "
            f"Results: {dict(record.values)}",
            file=self._stream,
        )
