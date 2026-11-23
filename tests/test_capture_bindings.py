import pytest

from tests.conftest import (
    DEFAULT_SETTINGS,
    EXAMPLES_DIRECTORY,
    ProcessorBuilder,
    compile_spec,
    create_rule_factory,
    parse_yaml_spec,
)
from zlog.capture_bindings import (
    CaptureBindingScanner,
    CapturedBindings,
    build_capture_destinations,
)
from zlog.context_state import ContextState
from zlog.context_updates import BUILTIN_CONTEXT_UPDATES
from zlog.errors import SpecError
from zlog.line_processing import LineProcessor, MatchedLine
from zlog.options import BindingSection
from zlog.rules import (
    Binding,
    ExtractionSpec,
    MatchRule,
    ResetSelection,
    derive_column_layout,
)
from zlog.value_sources import ConstantSource, GroupSource
from zlog.variable_names import VariableName

SCANNER = CaptureBindingScanner(BUILTIN_CONTEXT_UPDATES.keys())
NO_RESET = ResetSelection()
EXPLICIT_TRAIN_SPEC = """
matches:
  - pattern: '^=+ run %w'
    reset: [epoch, samples, warnings]
    context: {run: 1, +run_index: {value: 1}}
    record: {event: {value: start}}
  - pattern: 'epoch %d loss=%f acc=%f'
    context: {epoch: 1}
    record: {event: {value: epoch}, loss: 2, acc: 3}
  - pattern: 'processed %d samples'
    context: {+samples: 1}
    record: {event: {value: progress}}
  - pattern: 'warning: %s'
    context: {"@warnings": 1}
    record: {event: {value: warning}}
"""


def test_capture_destinations_table() -> None:
    destinations = build_capture_destinations(["", "+", "@", "^"])

    assert {
        prefix: (destination.section, destination.variable_prefix)
        for prefix, destination in destinations.items()
    } == {
        "": (BindingSection.RECORD, ""),
        "=": (BindingSection.CONTEXT, ""),
        "+": (BindingSection.CONTEXT, "+"),
        "@": (BindingSection.CONTEXT, "@"),
        "^": (BindingSection.CONTEXT, "^"),
    }


@pytest.mark.parametrize(
    ("pattern", "context", "record"),
    [
        ("plain %d (?P<raw>x)", (), ()),
        ("%(loss)f", (), (("loss", GroupSource("loss")),)),
        ("%(=run)w", (("run", GroupSource("run")),), ()),
        ("%(+n)d", (("+n", GroupSource("n")),), ()),
        ("%(@tags){s}", (("@tags", GroupSource("tags")),), ()),
        (
            "%(acc)f %(=e)d %(loss)f %(+n)d",
            (("e", GroupSource("e")), ("+n", GroupSource("n"))),
            (("acc", GroupSource("acc")), ("loss", GroupSource("loss"))),
        ),
        (r"%%(a)d \%(b)d %*d", (), ()),
    ],
)
def test_scanner_routes_captures_by_prefix(
    pattern: str,
    context: tuple[tuple[str, GroupSource], ...],
    record: tuple[tuple[str, GroupSource], ...],
) -> None:
    assert SCANNER.scan(pattern) == CapturedBindings(context, record)


def test_plugin_prefixes_work_in_captures() -> None:
    scanner = CaptureBindingScanner([*BUILTIN_CONTEXT_UPDATES, "^"])

    assert scanner.scan("best %(^best)f") == CapturedBindings(
        (("^best", GroupSource("best")),)
    )


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("%(-x)d", "unknown capture prefix '-' before 'x'"),
        ("%( x)d", "unknown capture prefix ' '"),
        ("%(=+x)d", "unknown capture prefix '=\\+'"),
        ("%(^x)d", "one of '\\+', '=', '@' for a context variable"),
        ("%(=)d", "capture name '='"),
        ("%(a.b)f", "capture name 'a.b'"),
    ],
)
def test_invalid_captures_are_rejected(pattern: str, message: str) -> None:
    with pytest.raises(SpecError, match=message):
        SCANNER.scan(pattern)


def test_factory_puts_captures_before_explicit_bindings() -> None:
    rule = create_rule_factory().create(
        "%(=e)d %(loss)f",
        NO_RESET,
        (("+n", ConstantSource("1")),),
        (("tag", ConstantSource("x")),),
    )

    assert rule == MatchRule(
        "%(=e)d %(loss)f",
        NO_RESET,
        (
            Binding(VariableName("e"), GroupSource("e")),
            Binding(VariableName("n", "+"), ConstantSource("1")),
        ),
        (
            Binding(VariableName("loss"), GroupSource("loss")),
            Binding(VariableName("tag"), ConstantSource("x")),
        ),
    )


@pytest.mark.parametrize(
    ("spec_text", "message"),
    [
        (
            "matches: [{pattern: '%(loss)f', record: {loss: 0}}]",
            "duplicate record variables loss",
        ),
        (
            "matches: [{pattern: '%(=x)d %(+x)d'}]",
            "duplicate context variables x",
        ),
        (
            "matches: [{pattern: '%(=x)d'}, {pattern: '%(x)d'}]",
            "'x' is both a context and a record variable",
        ),
        (
            "matches: [{pattern: '%(path)s'}]",
            "'path' is reserved for the input path",
        ),
        (
            "matches: [{pattern: '%(x)d', reset: [x]}]",
            "resets undeclared context variable 'x'",
        ),
    ],
)
def test_conflicting_captures_are_rejected(
    spec_text: str, message: str
) -> None:
    with pytest.raises(SpecError, match=message):
        compile_spec(parse_yaml_spec(spec_text))


def process_log(spec: ExtractionSpec) -> list[MatchedLine | None]:
    processor = LineProcessor(compile_spec(spec), ContextState())
    log = (EXAMPLES_DIRECTORY / "train.log").read_text(encoding="utf-8")
    return [processor.process(line) for line in log.splitlines()]


def test_lemma_captures_equal_explicit_bindings() -> None:
    captured = parse_yaml_spec(
        (EXAMPLES_DIRECTORY / "train.yaml").read_text(encoding="utf-8")
    )
    explicit = parse_yaml_spec(EXPLICIT_TRAIN_SPEC)
    path_column = DEFAULT_SETTINGS.path_column

    assert derive_column_layout(captured, path_column) == (
        derive_column_layout(explicit, path_column)
    )
    assert process_log(captured) == process_log(explicit)


def test_explicit_bindings_may_read_captured_groups(
    build_processor: ProcessorBuilder,
) -> None:
    processor = build_processor(
        "matches:\n"
        "  - pattern: 'step %(=step)d(?: loss=%(loss)f)?'\n"
        "    context: {+loss_sum: loss}\n"
    )

    assert [
        processor.process(line)
        for line in ["step 1 loss=0.5", "step 2", "step 3 loss=0.25"]
    ] == [
        MatchedLine(0, {"step": "1", "loss_sum": "0.5"}, {"loss": "0.5"}),
        MatchedLine(0, {"step": "2", "loss_sum": "0.5"}, {}),
        MatchedLine(0, {"step": "3", "loss_sum": "0.75"}, {"loss": "0.25"}),
    ]
