import logging
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from zlog.aggregation import MetricAggregator
from zlog.discovery import RunDirectoryScanner
from zlog.domain import (
    AnalysisSpec,
    GroupKey,
    IterationRecord,
    IterationSource,
    Summary,
)
from zlog.errors import ExtractionError
from zlog.extraction import ValueExtractor
from zlog.grouping import SegmentGroupResolver
from zlog.hooks import HookDispatcher

LOGGER = logging.getLogger(__name__)


class AnalysisPipeline:
    def __init__(
        self,
        scanner: RunDirectoryScanner,
        extractor: ValueExtractor,
        resolver: SegmentGroupResolver,
        aggregator: MetricAggregator,
        hooks: HookDispatcher,
    ) -> None:
        self._scanner = scanner
        self._extractor = extractor
        self._resolver = resolver
        self._aggregator = aggregator
        self._hooks = hooks

    def run(self, spec: AnalysisSpec, input_dir: Path) -> Summary:
        assert isinstance(input_dir, Path), "input_dir must be a Path"
        self._hooks.on_load(spec)
        records = self._analyze_runs(spec, input_dir)
        summary = self._aggregator.aggregate(records)
        self._hooks.on_terminate(summary)
        assert set(summary) <= {record.group for record in records}
        return summary

    def _analyze_runs(
        self, spec: AnalysisSpec, input_dir: Path
    ) -> list[IterationRecord]:
        if spec.groups:
            return [
                record
                for run in self._scanner.scan(input_dir)
                for source in run.sources
                for record in self._analyze_iteration(run.key, source)
            ]
        else:
            LOGGER.warning("specification declares no groups")
            return []

    def _analyze_iteration(
        self, directory_key: GroupKey, source: IterationSource
    ) -> list[IterationRecord]:
        try:
            segments = self._extractor.extract(source.path)
        except ExtractionError as error:
            LOGGER.error("skipping iteration %s: %s", source.path, error)
            return []
        else:
            records = (
                self._build_segment_record(
                    directory_key, source, segment, values
                )
                for segment, values in enumerate(segments)
            )
            return [record for record in records if record is not None]

    def _build_segment_record(
        self,
        directory_key: GroupKey,
        source: IterationSource,
        segment: int,
        values: Mapping[str, str],
    ) -> IterationRecord | None:
        group = self._resolver.resolve(directory_key, values)
        if group is not None:
            record = IterationRecord(
                group,
                source.iteration,
                MappingProxyType(self._resolver.select_metric_values(values)),
                segment,
            )
            self._hooks.on_iteration_analyzed(record)
            return record
        else:
            LOGGER.warning(
                "skipping segment %d of %s: group labels not found",
                segment,
                source.path,
            )
            return None
