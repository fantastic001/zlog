import re
from pathlib import Path

import pytest

from zlog.domain import PatternSpec
from zlog.errors import ExtractionError
from zlog.extraction import (
    FileValueExtractor,
    SegmentedTextExtractor,
    SeparatorLineSplitter,
    TextValueExtractor,
    WholeFileSplitter,
    build_iteration_splitter,
    compile_patterns,
)
from zlog.options import MatchPolicy
from zlog.regex_macros import RegexMacroExpander

LOG_TEXT = "epoch 1 accuracy: 0.5 loss=2\nepoch 2 accuracy: 0.7 loss=1\ndone\n"


def build_text_extractor(
    patterns: list[PatternSpec], policy: MatchPolicy
) -> TextValueExtractor:
    compiled = compile_patterns(patterns, RegexMacroExpander())
    return TextValueExtractor(compiled, policy)


def build_file_extractor(
    patterns: list[PatternSpec], max_file_bytes: int
) -> FileValueExtractor:
    return FileValueExtractor(
        SegmentedTextExtractor(
            WholeFileSplitter(),
            build_text_extractor(patterns, MatchPolicy.LAST),
        ),
        "utf-8",
        max_file_bytes,
    )


@pytest.mark.parametrize(
    ("policy", "expected"),
    [(MatchPolicy.LAST, "0.7"), (MatchPolicy.FIRST, "0.5")],
)
def test_match_policy_selects_line(policy: MatchPolicy, expected: str) -> None:
    extractor = build_text_extractor(
        [PatternSpec(r"accuracy\:\s(\f)", ("accuracy",))], policy
    )

    assert extractor.extract_from_text(LOG_TEXT) == {"accuracy": expected}


def test_multiple_groups_and_patterns() -> None:
    extractor = build_text_extractor(
        [
            PatternSpec(r"epoch (\d+) accuracy\:\s(\f)", ("epoch", "acc")),
            PatternSpec(r"loss=(\f)", ("loss",)),
        ],
        MatchPolicy.LAST,
    )

    assert extractor.extract_from_text(LOG_TEXT) == {
        "epoch": "2",
        "acc": "0.7",
        "loss": "1",
    }


def test_unmatched_pattern_and_optional_group_are_omitted() -> None:
    extractor = build_text_extractor(
        [
            PatternSpec(r"missing=(\f)", ("missing",)),
            PatternSpec(r"done(x)?", ("suffix",)),
        ],
        MatchPolicy.LAST,
    )

    assert extractor.extract_from_text(LOG_TEXT) == {}


def test_more_names_than_groups_is_tolerated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    extractor = build_text_extractor(
        [PatternSpec(r"loss=(\f)", ("loss", "extra"))], MatchPolicy.LAST
    )

    assert extractor.extract_from_text(LOG_TEXT) == {"loss": "1"}
    assert "extra names unused" in caplog.text


def test_file_extractor_reads_file(tmp_path: Path) -> None:
    source = tmp_path / "0.out"
    source.write_text(LOG_TEXT)
    extractor = build_file_extractor(
        [PatternSpec(r"loss=(\f)", ("loss",))], 1024
    )

    assert extractor.extract(source) == [{"loss": "1"}]


def test_file_extractor_rejects_oversized_file(tmp_path: Path) -> None:
    source = tmp_path / "0.out"
    source.write_text(LOG_TEXT)
    extractor = build_file_extractor([], 5)

    with pytest.raises(ExtractionError, match="limit"):
        extractor.extract(source)


def test_file_extractor_reports_missing_file(tmp_path: Path) -> None:
    extractor = build_file_extractor([], 5)

    with pytest.raises(ExtractionError, match="cannot read"):
        extractor.extract(tmp_path / "missing.out")


def test_file_extractor_requires_positive_limit() -> None:
    with pytest.raises(ValueError):
        build_file_extractor([], 0)


SEPARATED_LOG_LINES = [
    "preamble",
    "=== run ===",
    "run adam accuracy: 0.5",
    "",
    "=== run ===",
    "   ",
    "=== run ===",
    "run sgd accuracy: 0.9",
]


def test_whole_file_splitter_keeps_single_segment() -> None:
    assert WholeFileSplitter().split(["a", "b"]) == [["a", "b"]]


def test_separator_splitter_drops_separators_and_blank_segments() -> None:
    splitter = SeparatorLineSplitter(re.compile(r"^=+ run =+$"))

    assert splitter.split(SEPARATED_LOG_LINES) == [
        ["preamble"],
        ["run adam accuracy: 0.5", ""],
        ["run sgd accuracy: 0.9"],
    ]


def test_separator_splitter_without_separator_line() -> None:
    splitter = SeparatorLineSplitter(re.compile("---"))

    assert splitter.split(["a"]) == [["a"]]
    assert splitter.split([]) == []


@pytest.mark.parametrize(
    ("separator", "splitter_type"),
    [(None, WholeFileSplitter), (re.compile("-"), SeparatorLineSplitter)],
)
def test_build_iteration_splitter(
    separator: re.Pattern[str] | None, splitter_type: type
) -> None:
    assert isinstance(build_iteration_splitter(separator), splitter_type)


def test_segmented_extractor_extracts_each_segment() -> None:
    extractor = SegmentedTextExtractor(
        SeparatorLineSplitter(re.compile(r"^=+ run =+$")),
        build_text_extractor(
            [PatternSpec(r"run (\w+) accuracy\:\s(\f)", ("opt", "acc"))],
            MatchPolicy.LAST,
        ),
    )

    assert extractor.extract_segments("\n".join(SEPARATED_LOG_LINES)) == [
        {},
        {"opt": "adam", "acc": "0.5"},
        {"opt": "sgd", "acc": "0.9"},
    ]
