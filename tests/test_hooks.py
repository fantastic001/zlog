import io

import pytest

from zlog.domain import AnalysisSpec, IterationRecord
from zlog.hooks import HookDispatcher, VerboseIterationPrinter

RECORD = IterationRecord((("optimizer", "adam"),), 3, {"acc": "0.5"})


class RecordingHook:
    def __init__(self) -> None:
        self.events: list[str] = []

    def on_load(self, spec: AnalysisSpec) -> None:
        self.events.append("load")

    def on_iteration_analyzed(self, record: IterationRecord) -> None:
        self.events.append(f"iteration {record.iteration}")

    def on_terminate(self, summary: object) -> None:
        self.events.append("terminate")


class FailingTerminationHook:
    def on_terminate(self, summary: object) -> None:
        raise RuntimeError("hook exploded")


def test_dispatches_lifecycle_events() -> None:
    hook = RecordingHook()
    dispatcher = HookDispatcher([hook, object()])

    dispatcher.on_load(AnalysisSpec((), ()))
    dispatcher.on_iteration_analyzed(RECORD)
    dispatcher.on_terminate({})

    assert hook.events == ["load", "iteration 3", "terminate"]


def test_failing_hook_is_logged_and_isolated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hook = RecordingHook()
    dispatcher = HookDispatcher([FailingTerminationHook(), hook])

    dispatcher.on_terminate({})

    assert hook.events == ["terminate"]
    assert "hook exploded" in caplog.text


def test_verbose_printer_writes_iteration() -> None:
    stream = io.StringIO()

    VerboseIterationPrinter(stream).on_iteration_analyzed(RECORD)

    assert stream.getvalue() == (
        "Group: {'optimizer': 'adam'}, Iteration: 3, Results: {'acc': '0.5'}\n"
    )
