import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO, TextIO

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
from zlog.domain import AnalysisSpec
from zlog.extraction import (
    CompiledPattern,
    SegmentedTextExtractor,
    SourceValueExtractor,
    TextValueExtractor,
    build_iteration_splitter,
    compile_patterns,
)
from zlog.grouping import SegmentGroupResolver, partition_group_names
from zlog.hooks import (
    HookDispatcher,
    IterationRecordCollector,
    VerboseIterationPrinter,
)
from zlog.inputs import DirectoryInput, InputChannel, StdinInput
from zlog.list_statistics import ListStatisticsReducer
from zlog.options import (
    CheckpointMode,
    ComparisonFilter,
    FeatureState,
    InputKind,
    Verbosity,
)
from zlog.pipeline import AnalysisPipeline
from zlog.plot_drawing import MatplotlibPlotWriter, PlotFileLocator
from zlog.plugins import PluginRegistry
from zlog.regex_macros import RegexMacroExpander
from zlog.renderers import OutputFormatPlugin
from zlog.report_types import ReportContext, ReportLayoutFactory
from zlog.reporting import (
    ComparisonSectionBuilder,
    DefaultReportLayout,
    ReportBuilder,
    ReportData,
    ReportLayout,
    SummarySectionBuilder,
)
from zlog.spec_loader import SpecLoader, SpecParser
from zlog.statistics import MannWhitneyUTest

LOGGER = logging.getLogger(__name__)

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
    input_path: Path
    output_file: Path | None
    verbosity: Verbosity
    comparison_filter: ComparisonFilter
    checkpoint_mode: CheckpointMode
    settings: Settings
    input_kind: InputKind = InputKind.DIRECTORY
    stdin_labels: str = ""


INPUT_CHANNEL_FACTORIES: Mapping[
    InputKind, Callable[[AnalysisRequest, BinaryIO], InputChannel]
] = MappingProxyType(
    {
        InputKind.DIRECTORY: lambda request, stream: DirectoryInput(
            request.input_path, request.settings
        ),
        InputKind.STDIN: lambda request, stream: StdinInput(
            stream, request.stdin_labels, request.settings
        ),
    }
)


class AnalysisApplication:
    def __init__(
        self,
        request: AnalysisRequest,
        registry: PluginRegistry,
        stdin: BinaryIO,
        diagnostics: TextIO,
    ) -> None:
        self._request = request
        self._settings = request.settings
        self._registry = registry
        self._input_channel = INPUT_CHANNEL_FACTORIES[request.input_kind](
            request, stdin
        )
        self._diagnostics = diagnostics

    def run(self) -> str:
        spec = SpecLoader(SpecParser()).load(self._request.spec_file)
        output_format = self._registry.find_output_format(
            self._settings.output_format
        )
        report_layout = self._build_report_layout(spec, output_format)
        extraction = self._compile_extraction(spec)
        collector = IterationRecordCollector()
        with self._open_checkpoint_store(extraction) as store:
            pipeline = self._build_pipeline(spec, extraction, store, collector)
            summary = pipeline.run(spec)
        sections = report_layout.build(ReportData(summary, collector.records))
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
        checkpointing = self._input_channel.checkpointing
        if self._settings.checkpoint_file and (
            checkpointing is FeatureState.ENABLED
        ):
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
            self._warn_when_checkpoint_ignored(checkpointing)
            return NullCheckpointStore()

    def _warn_when_checkpoint_ignored(
        self, checkpointing: FeatureState
    ) -> None:
        if self._settings.checkpoint_file:
            LOGGER.warning(
                "checkpointing is %s for %s input; ignoring %s",
                checkpointing.value,
                self._request.input_kind.value,
                self._settings.checkpoint_file,
            )
        else:
            LOGGER.debug("checkpointing not requested")

    def _build_pipeline(
        self,
        spec: AnalysisSpec,
        extraction: CompiledExtraction,
        store: CheckpointStore,
        collector: IterationRecordCollector,
    ) -> AnalysisPipeline:
        source_extractor = SourceValueExtractor(
            self._input_channel.create_reader(),
            SegmentedTextExtractor(
                build_iteration_splitter(extraction.separator),
                TextValueExtractor(
                    extraction.patterns, self._settings.match_policy
                ),
            ),
        )
        verbosity_hooks = VERBOSITY_HOOK_FACTORIES[self._request.verbosity](
            self._diagnostics
        )
        group_names = partition_group_names(spec)
        return AnalysisPipeline(
            runs=self._input_channel.create_run_source(
                group_names.directory_groups
            ),
            extractor=CheckpointedExtractor(source_extractor, store),
            resolver=SegmentGroupResolver(
                spec.groups, group_names.extracted_groups
            ),
            aggregator=MetricAggregator(
                self._settings.std_ddof, self._create_list_reducer()
            ),
            hooks=HookDispatcher(
                (*self._registry.hooks, *verbosity_hooks, collector)
            ),
        )

    def _create_list_reducer(self) -> ListStatisticsReducer:
        return ListStatisticsReducer(
            self._settings.std_ddof, self._registry.list_statistics
        )

    def _create_comparator(self) -> MetricComparator:
        return MetricComparator(
            MannWhitneyUTest(),
            self._settings.significance_level,
            self._settings.minimum_sample_size,
        )

    def _build_report_layout(
        self, spec: AnalysisSpec, output_format: OutputFormatPlugin
    ) -> ReportLayout:
        match spec.reports:
            case ():
                return DefaultReportLayout(
                    self._build_report_builder(output_format)
                )
            case entries:
                factory = ReportLayoutFactory(
                    self._registry.report_types,
                    self._build_report_context(spec, output_format),
                )
                return factory.create(entries)

    def _build_report_builder(
        self, output_format: OutputFormatPlugin
    ) -> ReportBuilder:
        pairwise_builder = PairwiseComparisonBuilder(
            self._create_comparator(), self._request.comparison_filter
        )
        return ReportBuilder(
            SummarySectionBuilder(output_format.create_cell_formatter()),
            ComparisonSectionBuilder(pairwise_builder),
        )

    def _build_report_context(
        self, spec: AnalysisSpec, output_format: OutputFormatPlugin
    ) -> ReportContext:
        return ReportContext(
            groups=spec.groups,
            cell_formatter=output_format.create_cell_formatter(),
            comparator=self._create_comparator(),
            comparison_filter=self._request.comparison_filter,
            list_reducer=self._create_list_reducer(),
            std_ddof=self._settings.std_ddof,
            plot_files=self._create_plot_file_locator(),
            plot_writer=MatplotlibPlotWriter(self._settings.plot_dpi),
        )

    def _create_plot_file_locator(self) -> PlotFileLocator:
        match self._request.output_file:
            case None:
                link_base = Path.cwd()
            case Path() as output_file:
                link_base = output_file.parent
        plot_directory = Path(self._settings.plot_directory or link_base)
        LOGGER.info("plots go to %s", plot_directory)
        return PlotFileLocator(
            plot_directory, link_base, self._settings.plot_format
        )
