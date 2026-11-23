import pytest

from zlog.hooks import ExtractedRow, HookDispatcher, RunSummary
from zlog.rules import ExtractionSpec

ROW = ExtractedRow("a.log", 3, 0, {"path": "a.log"})
SUMMARY = RunSummary(1, 5, 2, (2,))


class RecordingHook:
    def __init__(self) -> None:
        self.events: list[str] = []

    def on_load(self, spec: ExtractionSpec) -> None:
        self.events.append("load")

    def on_row(self, row: ExtractedRow) -> None:
        self.events.append(f"row {row.line_number}")

    def on_terminate(self, summary: RunSummary) -> None:
        self.events.append(f"terminate {summary.rows_written}")


class FailingTerminationHook:
    def on_terminate(self, summary: RunSummary) -> None:
        raise RuntimeError("hook exploded")


def test_dispatches_lifecycle_events() -> None:
    hook = RecordingHook()
    dispatcher = HookDispatcher([hook, object()])

    dispatcher.on_load(ExtractionSpec())
    dispatcher.on_row(ROW)
    dispatcher.on_terminate(SUMMARY)

    assert dispatcher.has_row_listeners
    assert hook.events == ["load", "row 3", "terminate 2"]


def test_failing_hook_is_logged_and_isolated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hook = RecordingHook()
    dispatcher = HookDispatcher([FailingTerminationHook(), hook])

    dispatcher.on_terminate(SUMMARY)

    assert not HookDispatcher([FailingTerminationHook()]).has_row_listeners
    assert hook.events == ["terminate 2"]
    assert "hook exploded" in caplog.text
