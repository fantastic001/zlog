import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TextIO

from zlog.aggregation import MetricAggregator
from zlog.checkpoint import (
    CheckpointedExtractor,
    CheckpointStore,
    JsonCheckpointStore,
    NullCheckpointStore,
    fingerprint_extraction,
)
from zlog.comparison import MetricComparator, PairwiseComparisonBuilder
from zlog.config import Settings
from zlog.discovery import RunDirectoryScanner
from zlog.domain import AnalysisSpec
from zlog.extraction import (
    CompiledPattern,
    FileValueExtractor,
    SegmentedTextExtractor,
    TextValueExtractor,
    build_iteration_splitter,
    compile_patterns,
)
from zlog.grouping import SegmentGroupResolver, partition_group_names
from zlog.hooks import HookDispatcher, VerboseIterationPrinter
from zlog.list_statistics import ListStatisticsReducer
from zlog.options import CheckpointMode, ComparisonFilter, Verbosity
from zlog.pipeline import AnalysisPipeline
from zlog.plugins import PluginRegistry
from zlog.regex_macros import RegexMacroExpander
from zlog.renderers import OutputFormatPlugin
from zlog.reporting import (
    ComparisonSectionBuilder,
    ReportBuilder,
    SummarySectionBuilder,
)
from zlog.spec_loader import SpecLoader, SpecParser
from zlog.statistics import MannWhitneyUTest

VERBOSITY_HOOK_FACTORIES: Mapping[
    Verbosity, Callable[[TextIO], tuple[object, ...]]
] = MappingProxyType(
    {
        Verbosity.QUIET: lambda stream: (),
        Verbosity.VERBOSE: lambda stream: (VerboseIterationPrinter(stream),),
    }
)


@dataclass(frozen=True)
class CompiledExtraction:
    patterns: tuple[CompiledPattern, ...]
    separator: re.Pattern[str] | None


@dataclass(frozen=True)
class AnalysisRequest:
    spec_file: Path
    input_dir: Path
    output_file: Path | None
    verbosity: Verbosity
    comparison_filter: ComparisonFilter
    checkpoint_mode: CheckpointMode
    settings: Settings


class AnalysisApplication:
    def __init__(
        self,
        request: AnalysisRequest,
        registry: PluginRegistry,
        diagnostics: TextIO,
    ) -> None:
        self._request = request
        self._settings = request.settings
        self._registry = registry
        self._diagnostics = diagnostics

    def run(self) -> str:
        spec = SpecLoader(SpecParser()).load(self._request.spec_file)
        output_format = self._registry.find_output_format(
            self._settings.output_format
        )
        extraction = self._compile_extraction(spec)
        with self._open_checkpoint_store(extraction) as store:
            pipeline = self._build_pipeline(spec, extraction, store)
            summary = pipeline.run(spec, self._request.input_dir)
        sections = self._build_report_builder(output_format).build(summary)
        return output_format.create_renderer().render(sections)

    def _compile_extraction(self, spec: AnalysisSpec) -> CompiledExtraction:
        expander = (
            RegexMacroExpander()
            .with_additional_macros(self._registry.regex_macros)
            .with_additional_macros(spec.macros)
        )
        return CompiledExtraction(
            patterns=compile_patterns(spec.patterns, expander),
            separator=self._compile_iteration_separator(spec, expander),
        )

    @staticmethod
    def _compile_iteration_separator(
        spec: AnalysisSpec, expander: RegexMacroExpander
    ) -> re.Pattern[str] | None:
        match spec.iteration_separator:
            case None:
                return None
            case str() as separator:
                return expander.compile(separator)

    def _open_checkpoint_store(
        self, extraction: CompiledExtraction
    ) -> CheckpointStore:
        if self._settings.checkpoint_file:
            return JsonCheckpointStore(
                Path(self._settings.checkpoint_file),
                fingerprint_extraction(
                    extraction.patterns,
                    extraction.separator,
                    self._settings.match_policy,
                ),
                self._request.checkpoint_mode,
                self._settings.checkpoint_interval,
            )
        else:
            return NullCheckpointStore()

    def _build_pipeline(
        self,
        spec: AnalysisSpec,
        extraction: CompiledExtraction,
        store: CheckpointStore,
    ) -> AnalysisPipeline:
        file_extractor = FileValueExtractor(
            SegmentedTextExtractor(
                build_iteration_splitter(extraction.separator),
                TextValueExtractor(
                    extraction.patterns, self._settings.match_policy
                ),
            ),
            self._settings.file_encoding,
            self._settings.max_input_file_bytes,
        )
        verbosity_hooks = VERBOSITY_HOOK_FACTORIES[self._request.verbosity](
            self._diagnostics
        )
        group_names = partition_group_names(spec)
        return AnalysisPipeline(
            scanner=RunDirectoryScanner(
                group_names.directory_groups,
                self._settings.group_separator,
                self._settings.output_extension,
            ),
            extractor=CheckpointedExtractor(file_extractor, store),
            resolver=SegmentGroupResolver(
                spec.groups, group_names.extracted_groups
            ),
            aggregator=MetricAggregator(
                self._settings.std_ddof,
                ListStatisticsReducer(
                    self._settings.std_ddof, self._registry.list_statistics
                ),
            ),
            hooks=HookDispatcher((*self._registry.hooks, *verbosity_hooks)),
        )

    def _build_report_builder(
        self, output_format: OutputFormatPlugin
    ) -> ReportBuilder:
        comparator = MetricComparator(
            MannWhitneyUTest(),
            self._settings.significance_level,
            self._settings.minimum_sample_size,
        )
        pairwise_builder = PairwiseComparisonBuilder(
            comparator, self._request.comparison_filter
        )
        return ReportBuilder(
            SummarySectionBuilder(output_format.create_cell_formatter()),
            ComparisonSectionBuilder(pairwise_builder),
        )
