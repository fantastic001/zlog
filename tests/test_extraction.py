from pathlib import Path

import pytest

from zlog.domain import PatternSpec
from zlog.errors import ExtractionError
from zlog.extraction import (
    FileValueExtractor,
    TextValueExtractor,
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
    extractor = FileValueExtractor(
        build_text_extractor(
            [PatternSpec(r"loss=(\f)", ("loss",))], MatchPolicy.LAST
        ),
        "utf-8",
        1024,
    )

    assert extractor.extract(source) == {"loss": "1"}


def test_file_extractor_rejects_oversized_file(tmp_path: Path) -> None:
    source = tmp_path / "0.out"
    source.write_text(LOG_TEXT)
    extractor = FileValueExtractor(
        build_text_extractor([], MatchPolicy.LAST), "utf-8", 5
    )

    with pytest.raises(ExtractionError, match="limit"):
        extractor.extract(source)


def test_file_extractor_reports_missing_file(tmp_path: Path) -> None:
    extractor = FileValueExtractor(
        build_text_extractor([], MatchPolicy.LAST), "utf-8", 5
    )

    with pytest.raises(ExtractionError, match="cannot read"):
        extractor.extract(tmp_path / "missing.out")


def test_file_extractor_requires_positive_limit() -> None:
    with pytest.raises(ValueError):
        FileValueExtractor(
            build_text_extractor([], MatchPolicy.LAST), "utf-8", 0
        )
