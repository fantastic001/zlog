from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from zlog import capture_bindings
from zlog.compilation import CompiledRule, RuleCompiler
from zlog.config import Settings
from zlog.context_state import ContextState
from zlog.context_updates import BUILTIN_CONTEXT_UPDATES, build_context_updates
from zlog.line_processing import LineProcessor
from zlog.pattern_aliases import PatternAliasExpander
from zlog.rules import ExtractionSpec, derive_column_layout
from zlog.spec_parser import SpecParser
from zlog.spec_validation import SpecConsistencyChecker

EXAMPLES_DIRECTORY = Path(__file__).resolve().parent.parent / "examples"
DEFAULT_SETTINGS = Settings()

FileWriter = Callable[[str, str], Path]
SpecBuilder = Callable[[str], ExtractionSpec]
ProcessorBuilder = Callable[[str], LineProcessor]


def create_rule_factory() -> capture_bindings.CaptureBindingRuleFactory:
    return capture_bindings.create_rule_factory(BUILTIN_CONTEXT_UPDATES.keys())


def parse_yaml_spec(text: str) -> ExtractionSpec:
    return SpecParser(create_rule_factory()).parse(yaml.safe_load(text))


def compile_spec(
    spec: ExtractionSpec, settings: Settings = DEFAULT_SETTINGS
) -> tuple[CompiledRule, ...]:
    SpecConsistencyChecker(settings.path_column).check(spec)
    patterns = PatternAliasExpander().with_additional_aliases(spec.aliases)
    updates = build_context_updates(BUILTIN_CONTEXT_UPDATES, settings)
    layout = derive_column_layout(spec, settings.path_column)
    return RuleCompiler(patterns, updates).compile(spec.matches, layout)


@pytest.fixture
def write_file(tmp_path: Path) -> FileWriter:
    def write(name: str, content: str) -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    return write


@pytest.fixture
def build_processor() -> ProcessorBuilder:
    def build(spec_text: str) -> LineProcessor:
        rules = compile_spec(parse_yaml_spec(spec_text))
        return LineProcessor(rules, ContextState())

    return build
