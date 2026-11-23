import pytest

from tests.conftest import ProcessorBuilder
from zlog.errors import InvalidValueError
from zlog.line_processing import LineProcessor, MatchedLine

FIRST_MATCH_SPEC = """
matches:
  - {pattern: 'loss=(\\d+)', record: {loss: 1}}
  - {pattern: 'acc=(\\d+)', record: {acc: 1}}
"""


def process_all(processor: LineProcessor, lines: list[str]) -> list[object]:
    return [processor.process(line) for line in lines]


def test_first_matching_rule_wins(build_processor: ProcessorBuilder) -> None:
    processor = build_processor(FIRST_MATCH_SPEC)

    assert processor.process("acc=2 loss=1") == MatchedLine(
        0, {}, {"loss": "1"}
    )
    assert processor.process("acc=2") == MatchedLine(1, {}, {"acc": "2"})
    assert processor.process("nothing") is None


def test_every_matched_line_produces_a_row(
    build_processor: ProcessorBuilder,
) -> None:
    processor = build_processor(
        "matches:\n"
        "  - {pattern: 'run (\\w+)', context: {run: 1}}\n"
        "  - {pattern: marker}\n"
    )

    assert process_all(processor, ["run a", "marker", "other"]) == [
        MatchedLine(0, {"run": "a"}, {}),
        MatchedLine(1, {"run": "a"}, {}),
        None,
    ]


def test_context_update_is_visible_on_the_same_line(
    build_processor: ProcessorBuilder,
) -> None:
    processor = build_processor(
        "matches:\n"
        "  - {pattern: 'epoch (\\d) loss=(\\d)', context: {epoch: 1},"
        " record: {loss: 2}}\n"
    )

    assert processor.process("epoch 3 loss=1") == MatchedLine(
        0, {"epoch": "3"}, {"loss": "1"}
    )


def test_lemma_persistence_unrelated_lines_keep_context(
    build_processor: ProcessorBuilder,
) -> None:
    processor = build_processor(
        "matches:\n"
        "  - {pattern: 'run (\\w+)', context: {run: 1}}\n"
        "  - {pattern: 'epoch (\\d)', context: {epoch: 1}}\n"
    )

    rows = process_all(processor, ["run a", "epoch 1", "x", "epoch 2"])

    assert [row.context for row in rows if isinstance(row, MatchedLine)] == [
        {"run": "a"},
        {"run": "a", "epoch": "1"},
        {"run": "a", "epoch": "2"},
    ]


@pytest.mark.parametrize("reset", ["[n, w]", "all"])
def test_lemma_reset_clears_before_updates(
    build_processor: ProcessorBuilder, reset: str
) -> None:
    processor = build_processor(
        "matches:\n"
        f"  - {{pattern: 'run (\\w+)', reset: {reset}, context: {{run: 1}}}}\n"
        "  - {pattern: 'n=(\\d)', context: {+n: 1}}\n"
        "  - {pattern: 'w=(\\w)', context: {'@w': 1}}\n"
    )

    rows = process_all(
        processor, ["run a", "n=2", "w=x", "n=3", "run b", "n=4", "w=y"]
    )

    assert [row.context for row in rows if isinstance(row, MatchedLine)] == [
        {"run": "a"},
        {"run": "a", "n": "2"},
        {"run": "a", "n": "2", "w": "x"},
        {"run": "a", "n": "5", "w": "x"},
        {"run": "b"},
        {"run": "b", "n": "4"},
        {"run": "b", "n": "4", "w": "y"},
    ]


def test_lemma_counter_counts_matches(
    build_processor: ProcessorBuilder,
) -> None:
    processor = build_processor(
        "matches:\n"
        "  - {pattern: '^=+', context: {+runs: {value: 1}},"
        " record: {event: {value: start}}}\n"
    )

    rows = process_all(processor, ["===", "x", "====", "=", "y"])

    assert [row for row in rows if row is not None] == [
        MatchedLine(0, {"runs": str(count)}, {"event": "start"})
        for count in (1, 2, 3)
    ]


def test_non_participating_groups_are_skipped(
    build_processor: ProcessorBuilder,
) -> None:
    processor = build_processor(
        "matches:\n"
        "  - {pattern: 'v(\\d)?(?: r(\\d))?', context: {v: 1},"
        " record: {r: 2}}\n"
    )

    assert process_all(processor, ["v1 r2", "v", "v3"]) == [
        MatchedLine(0, {"v": "1"}, {"r": "2"}),
        MatchedLine(0, {"v": "1"}, {}),
        MatchedLine(0, {"v": "3"}, {}),
    ]


def test_invalid_addition_names_the_variable(
    build_processor: ProcessorBuilder,
) -> None:
    processor = build_processor(
        "matches: [{pattern: 'n=(\\w+)', context: {+total: 1}}]"
    )
    processor.process("n=1")

    with pytest.raises(InvalidValueError, match="'total': cannot add 'x'"):
        processor.process("n=x")
