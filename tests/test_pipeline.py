from pathlib import Path

import pytest

from tests.conftest import RunTreeBuilder
from zlog.aggregation import MetricAggregator
from zlog.discovery import DirectoryRunSource, RunDirectoryScanner
from zlog.domain import AnalysisSpec, IterationRecord
from zlog.errors import ExtractionError
from zlog.grouping import SegmentGroupResolver
from zlog.hooks import HookDispatcher
from zlog.pipeline import AnalysisPipeline

SPEC = AnalysisSpec(("optimizer",), ())
SEGMENT_SEPARATOR = "|"


class FakeExtractor:
    def extract(self, source: Path) -> list[dict[str, str]]:
        if source.read_text() == "bad":
            raise ExtractionError("unreadable")
        else:
            return [
                {"acc": value}
                for value in source.read_text().split(SEGMENT_SEPARATOR)
            ]


class GroupedSegmentExtractor:
    def extract(self, source: Path) -> list[dict[str, str]]:
        return [
            dict(item.split(":") for item in segment.split(","))
            for segment in source.read_text().split(SEGMENT_SEPARATOR)
        ]


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
        DirectoryRunSource(RunDirectoryScanner(SPEC.groups, "-", ".out"), root),
        FakeExtractor(),
        SegmentGroupResolver(SPEC.groups, ()),
        MetricAggregator(),
        HookDispatcher([collector]),
    )

    summary = pipeline.run(SPEC)

    assert summary[(("optimizer", "adam"),)]["acc"].mean == 2.0
    assert summary[(("optimizer", "sgd"),)]["acc"].values == (5.0,)
    assert len(collector.records) == 3
    assert "unreadable" in caplog.text


def test_pipeline_records_every_segment(
    build_run_tree: RunTreeBuilder,
) -> None:
    root = build_run_tree({"adam": {0: "1|3|5"}})
    collector = IterationCollector()
    pipeline = AnalysisPipeline(
        DirectoryRunSource(RunDirectoryScanner(SPEC.groups, "-", ".out"), root),
        FakeExtractor(),
        SegmentGroupResolver(SPEC.groups, ()),
        MetricAggregator(),
        HookDispatcher([collector]),
    )

    summary = pipeline.run(SPEC)

    assert summary[(("optimizer", "adam"),)]["acc"].values == (1.0, 3.0, 5.0)
    assert [record.segment for record in collector.records] == [0, 1, 2]


def test_pipeline_groups_segments_by_extracted_labels(
    build_run_tree: RunTreeBuilder, caplog: pytest.LogCaptureFixture
) -> None:
    spec = AnalysisSpec(("optimizer", "size"), ())
    root = build_run_tree(
        {
            "adam": {
                0: "size:small,acc:1|size:large,acc:7|size:small,acc:3|acc:4"
            }
        }
    )
    pipeline = AnalysisPipeline(
        DirectoryRunSource(
            RunDirectoryScanner(("optimizer",), "-", ".out"), root
        ),
        GroupedSegmentExtractor(),
        SegmentGroupResolver(spec.groups, ("size",)),
        MetricAggregator(),
        HookDispatcher([]),
    )

    summary = pipeline.run(spec)

    small = (("optimizer", "adam"), ("size", "small"))
    large = (("optimizer", "adam"), ("size", "large"))
    assert set(summary) == {small, large}
    assert summary[small]["acc"].values == (1.0, 3.0)
    assert "size" not in summary[small]
    assert "skipping segment 3" in caplog.text


def test_pipeline_without_groups_yields_empty_summary(
    build_run_tree: RunTreeBuilder, caplog: pytest.LogCaptureFixture
) -> None:
    root = build_run_tree({"adam": {0: "1"}})
    spec = AnalysisSpec((), ())
    pipeline = AnalysisPipeline(
        DirectoryRunSource(RunDirectoryScanner((), "-", ".out"), root),
        FakeExtractor(),
        SegmentGroupResolver((), ()),
        MetricAggregator(),
        HookDispatcher([]),
    )

    assert pipeline.run(spec) == {}
    assert "declares no groups" in caplog.text
