import logging
from pathlib import Path
from types import MappingProxyType

from zlog.aggregation import MetricAggregator
from zlog.discovery import RunDirectoryScanner
from zlog.domain import (
    AnalysisSpec,
    GroupKey,
    GroupRun,
    IterationRecord,
    IterationSource,
    Summary,
)
from zlog.errors import ExtractionError
from zlog.extraction import ValueExtractor
from zlog.hooks import HookDispatcher

LOGGER = logging.getLogger(__name__)


class AnalysisPipeline:
    def __init__(
        self,
        scanner: RunDirectoryScanner,
        extractor: ValueExtractor,
        aggregator: MetricAggregator,
        hooks: HookDispatcher,
    ) -> None:
        self._scanner = scanner
        self._extractor = extractor
        self._aggregator = aggregator
        self._hooks = hooks

    def run(self, spec: AnalysisSpec, input_dir: Path) -> Summary:
        assert isinstance(input_dir, Path), "input_dir must be a Path"
        self._hooks.on_load(spec)
        runs = self._scanner.scan(input_dir)
        records = [record for run in runs for record in self._analyze_run(run)]
        summary = self._aggregator.aggregate(records)
        self._hooks.on_terminate(summary)
        assert set(summary) <= {run.key for run in runs}
        return summary

    def _analyze_run(self, run: GroupRun) -> list[IterationRecord]:
        records = (
            self._analyze_iteration(run.key, source) for source in run.sources
        )
        return [record for record in records if record is not None]

    def _analyze_iteration(
        self, group: GroupKey, source: IterationSource
    ) -> IterationRecord | None:
        try:
            values = self._extractor.extract(source.path)
        except ExtractionError as error:
            LOGGER.error("skipping iteration %s: %s", source.path, error)
            return None
        else:
            record = IterationRecord(
                group, source.iteration, MappingProxyType(dict(values))
            )
            self._hooks.on_iteration_analyzed(record)
            return record
