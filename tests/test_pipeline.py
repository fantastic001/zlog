from pathlib import Path

import pytest

from tests.conftest import RunTreeBuilder
from zlog.aggregation import MetricAggregator
from zlog.discovery import RunDirectoryScanner
from zlog.domain import AnalysisSpec, IterationRecord
from zlog.errors import ExtractionError
from zlog.hooks import HookDispatcher
from zlog.pipeline import AnalysisPipeline

SPEC = AnalysisSpec(("optimizer",), ())


class FakeExtractor:
    def extract(self, source: Path) -> dict[str, str]:
        if source.read_text() == "bad":
            raise ExtractionError("unreadable")
        else:
            return {"acc": source.read_text()}


class IterationCollector:
    def __init__(self) -> None:
        self.records: list[IterationRecord] = []

    def on_iteration_analyzed(self, record: IterationRecord) -> None:
        self.records.append(record)


def test_pipeline_aggregates_and_skips_failed_iterations(
    build_run_tree: RunTreeBuilder, caplog: pytest.LogCaptureFixture
) -> None:
    root = build_run_tree({"adam": {0: "1", 1: "3", 2: "bad"}, "sgd": {0: "5"}})
    collector = IterationCollector()
    pipeline = AnalysisPipeline(
        RunDirectoryScanner(SPEC.groups, "-", ".out"),
        FakeExtractor(),
        MetricAggregator(),
        HookDispatcher([collector]),
    )

    summary = pipeline.run(SPEC, root)

    assert summary[(("optimizer", "adam"),)]["acc"].mean == 2.0
    assert summary[(("optimizer", "sgd"),)]["acc"].values == (5.0,)
    assert len(collector.records) == 3
    assert "unreadable" in caplog.text
