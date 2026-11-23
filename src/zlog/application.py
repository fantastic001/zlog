import logging
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from zlog.cli_rules import PendingCliRule, build_cli_rules
from zlog.compilation import CompiledRule, RuleCompiler
from zlog.config import Settings
from zlog.context_state import ContextState
from zlog.context_updates import ContextUpdate, build_context_updates
from zlog.extraction_run import ExtractionRunner, RowSink
from zlog.hooks import HookDispatcher, RunSummary
from zlog.line_processing import LineProcessor
from zlog.line_sources import (
    FileLineSource,
    LineSource,
    StdinLineSource,
    TextDecoding,
)
from zlog.outputs import AtomicFileTarget, OutputTarget, StandardOutputTarget
from zlog.pattern_aliases import PatternAliasExpander
from zlog.plugins import PluginRegistry
from zlog.rule_factory import MatchRuleFactory
from zlog.rules import ColumnLayout, ExtractionSpec, derive_column_layout
from zlog.spec_loader import SpecLoader
from zlog.spec_parser import SpecParser
from zlog.spec_validation import SpecConsistencyChecker
from zlog.writers import RowWriter, apply_formula_escaping

LOGGER = logging.getLogger(__name__)

STDIN_ARGUMENT = "-"


@dataclass(frozen=True)
class ExtractionRequest:
    spec_file: Path | None
    cli_rules: tuple[PendingCliRule, ...]
    inputs: tuple[str, ...]
    output_file: Path | None
    settings: Settings


@dataclass(frozen=True)
class StandardStreams:
    stdin: BinaryIO
    stdout: BinaryIO


class ExtractionApplication:
    def __init__(
        self,
        request: ExtractionRequest,
        registry: PluginRegistry,
        streams: StandardStreams,
    ) -> None:
        self._request = request
        self._settings = request.settings
        self._registry = registry
        self._streams = streams
        self._updates: Mapping[str, ContextUpdate] = build_context_updates(
            registry.context_updates, request.settings
        )

    def run(self) -> RunSummary:
        spec = self._assemble_spec()
        SpecConsistencyChecker(self._settings.path_column).check(spec)
        layout = derive_column_layout(spec, self._settings.path_column)
        rules = self._compile_rules(spec, layout)
        writer_factory = self._registry.find_output_format(
            self._settings.output_format
        )
        sources = self._create_sources()
        for source in sources:
            source.ensure_readable()
        hooks = HookDispatcher(self._registry.hooks)
        hooks.on_load(spec)
        with ExitStack() as resources:
            stream = resources.enter_context(self._create_output().open())
            writer = apply_formula_escaping(
                writer_factory(stream, self._settings),
                self._settings.formula_escaping,
            )
            summary = self._create_runner(rules, layout, writer, hooks).run(
                sources
            )
        hooks.on_terminate(summary)
        return summary

    def _assemble_spec(self) -> ExtractionSpec:
        factory = MatchRuleFactory(self._updates.keys())
        cli_rules = build_cli_rules(self._request.cli_rules, factory)
        match self._request.spec_file:
            case None:
                return ExtractionSpec(cli_rules)
            case Path() as spec_file:
                file_spec = SpecLoader(SpecParser(factory)).load(spec_file)
                return file_spec.with_additional_matches(cli_rules)

    def _compile_rules(
        self, spec: ExtractionSpec, layout: ColumnLayout
    ) -> tuple[CompiledRule, ...]:
        patterns = PatternAliasExpander(
            self._registry.pattern_aliases
        ).with_additional_aliases(spec.aliases)
        return RuleCompiler(patterns, self._updates).compile(
            spec.matches, layout
        )

    def _create_sources(self) -> tuple[LineSource, ...]:
        inputs = self._request.inputs or (STDIN_ARGUMENT,)
        decoding = TextDecoding(
            self._settings.file_encoding, self._settings.decode_errors
        )
        return tuple(
            self._create_source(argument, decoding) for argument in inputs
        )

    def _create_source(
        self, argument: str, decoding: TextDecoding
    ) -> LineSource:
        match argument:
            case "-":
                return StdinLineSource(
                    self._streams.stdin, self._settings.stdin_path, decoding
                )
            case _:
                return FileLineSource(Path(argument), decoding)

    def _create_output(self) -> OutputTarget:
        match self._request.output_file:
            case None:
                return StandardOutputTarget(
                    self._streams.stdout, self._settings.output_encoding
                )
            case Path() as output_file:
                return AtomicFileTarget(
                    output_file, self._settings.output_encoding
                )

    def _create_runner(
        self,
        rules: tuple[CompiledRule, ...],
        layout: ColumnLayout,
        writer: RowWriter,
        hooks: HookDispatcher,
    ) -> ExtractionRunner:
        state = ContextState()
        return ExtractionRunner(
            LineProcessor(rules, state),
            state,
            RowSink(layout, writer, hooks),
            self._settings.max_line_length,
            len(rules),
        )
