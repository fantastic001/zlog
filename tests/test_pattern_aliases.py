import re

import pytest

from tests.conftest import ProcessorBuilder
from zlog.context_updates import NumericAddUpdate
from zlog.errors import SpecError
from zlog.line_processing import MatchedLine
from zlog.pattern_aliases import (
    BUILTIN_PATTERN_ALIASES,
    FLOAT_REGEX,
    INTEGER_REGEX,
    PatternAliasExpander,
    validate_pattern_alias,
)

EXPANDER = PatternAliasExpander()
FLOAT_TEXTS = [
    "0.90",
    "1.5e-3",
    "-.5",
    "+7",
    "1.",
    "1E10",
    "NaN",
    "-Infinity",
    "inf",
]


@pytest.mark.parametrize(
    ("alias", "accepted", "rejected"),
    [
        ("d", ["42", "-12", "+0"], ["1.5", "", "x"]),
        ("f", FLOAT_TEXTS, ["information", "e5", ".", "-", "1e", "nan5"]),
        ("x", ["0x1F", "ff", "0XAB", "10"], ["0x", "g1"]),
        ("s", ["lr-high", "a=b", "-"], ["a b", ""]),
        ("w", ["adam", "a_1", "7"], ["lr-high", ""]),
        ("r", ["anything at all", ""], []),
    ],
)
def test_builtin_alias_matches(
    alias: str, accepted: list[str], rejected: list[str]
) -> None:
    pattern = EXPANDER.compile(f"%{alias}")

    assert [pattern.fullmatch(text) is not None for text in accepted] == [
        True
    ] * len(accepted)
    assert [pattern.fullmatch(text) for text in rejected] == [None] * len(
        rejected
    )


def test_float_alias_finds_numbers_inside_text() -> None:
    pattern = EXPANDER.compile("loss=%f")

    assert [
        found.group(1)
        for found in map(pattern.search, ["loss=12abc", "loss=-1.5e3,"])
        if found is not None
    ] == ["12", "-1.5e3"]
    assert pattern.search("loss=information") is None


@pytest.mark.parametrize("text", FLOAT_TEXTS)
def test_lemma_float_captures_are_addable(text: str) -> None:
    found = EXPANDER.compile("%f").fullmatch(text)

    assert found is not None
    assert NumericAddUpdate(50).apply(None, found.group(1))


@pytest.mark.parametrize(
    ("pattern", "expanded"),
    [
        ("%d", f"({INTEGER_REGEX})"),
        ("%*d", f"(?:{INTEGER_REGEX})"),
        ("%(n)d", f"(?P<n>{INTEGER_REGEX})"),
        ("%{w}", r"(\w+)"),
        ("%*{w}", r"(?:\w+)"),
        ("%(n){w}", r"(?P<n>\w+)"),
        ("loss=%f", f"loss=({FLOAT_REGEX})"),
        ("100%%", "100%"),
        ("%%d", "%d"),
        (r"\%d", r"\%d"),
        (r"\\%d", rf"\\({INTEGER_REGEX})"),
        ("50% done", "50% done"),
        ("%5 %) a%", "%5 %) a%"),
        (r"(\w+)=(?P<v>\d)", r"(\w+)=(?P<v>\d)"),
    ],
)
def test_expansion(pattern: str, expanded: str) -> None:
    assert EXPANDER.expand(pattern) == expanded


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("%q", "unknown pattern alias 'q'"),
        ("%F", "unknown pattern alias 'F'"),
        ("%{nope}", "unknown pattern alias 'nope'"),
        ("%{}", "unknown pattern alias ''"),
        ("%*", r"incomplete alias '%\*' at position 0"),
        ("a %(n)", r"incomplete alias '%\(' at position 2"),
        ("%{w", r"incomplete alias '%\{'"),
        ("%*(n)d", r"incomplete alias '%\*'"),
        ("%(1n)d", "capture name '1n' in '%\\(1n\\)d' must match"),
        ("%()d", "capture name ''"),
        ("%(a)d %(a)d", "redefinition of group name 'a'"),
        ("(%d", "invalid regex"),
    ],
)
def test_invalid_alias_use_is_rejected(pattern: str, message: str) -> None:
    with pytest.raises(SpecError, match=message):
        EXPANDER.compile(pattern)


def test_unknown_alias_lists_available_aliases() -> None:
    with pytest.raises(SpecError, match="available: d, f, r, s, w, x;"):
        EXPANDER.expand("%q")


@pytest.mark.parametrize(
    ("pattern", "own_groups", "capturing_tokens"),
    [
        ("plain", 0, 0),
        ("%d %f %s", 0, 3),
        ("%*d %*{w}", 0, 0),
        (r"(\w+)=%d", 1, 1),
        (r"(?:a)(b)(?P<c>c) %(n)d %*f %{w}", 2, 2),
        (r"\(%d\) %%d", 0, 1),
    ],
)
def test_lemma_group_numbering(
    pattern: str, own_groups: int, capturing_tokens: int
) -> None:
    assert EXPANDER.compile(pattern).groups == own_groups + capturing_tokens


def test_alias_groups_are_numbered_left_to_right() -> None:
    pattern = EXPANDER.compile(r"(\w+)=%d %*f %(tag)s")

    found = pattern.search("lr=3 0.5 high")

    assert found is not None
    assert found.groups() == ("lr", "3", "high")
    assert pattern.groupindex == {"tag": 3}


def test_lemma_expansions_are_not_rescanned() -> None:
    expander = EXPANDER.with_additional_aliases({"p": "%d"})

    assert expander.expand("%{p}") == "(%d)"
    assert expander.compile("%{p}").fullmatch("%d") is not None


def test_additional_aliases_extend_and_override() -> None:
    expander = EXPANDER.with_additional_aliases({"d": r"\d+", "ts": r"\d+:\d+"})

    assert expander.expand("%d %{ts}") == r"(\d+) (\d+:\d+)"
    assert EXPANDER.expand("%d") == f"({INTEGER_REGEX})"


@pytest.mark.parametrize(("name", "regex"), [("ts", r"\d+"), ("_e", "")])
def test_valid_aliases_are_accepted(name: str, regex: str) -> None:
    validate_pattern_alias(name, regex)

    assert PatternAliasExpander({name: regex}).expand(f"%{{{name}}}") == (
        f"({regex})"
    )


@pytest.mark.parametrize(
    ("name", "regex", "message"),
    [
        ("", "a", "pattern alias name '' must match"),
        ("1a", "a", "pattern alias name '1a'"),
        ("a-b", "a", "pattern alias name 'a-b'"),
        ("a", "(", "pattern alias 'a': invalid regex"),
        ("a", "(b)", "has 1 capturing groups"),
        ("a", "(?P<n>b)(c)", "has 2 capturing groups"),
    ],
)
def test_invalid_aliases_are_rejected(
    name: str, regex: str, message: str
) -> None:
    with pytest.raises(SpecError, match=message):
        validate_pattern_alias(name, regex)
    with pytest.raises(SpecError, match=message):
        PatternAliasExpander({name: regex})


def test_builtin_aliases_are_valid() -> None:
    assert all(
        re.compile(regex).groups == 0
        for regex in BUILTIN_PATTERN_ALIASES.values()
    )


def test_named_captures_bind_by_name(
    build_processor: ProcessorBuilder,
) -> None:
    processor = build_processor(
        "matches:\n"
        "  - pattern: 'step %(step)d loss=%(loss)f'\n"
        "    context: {+steps: step}\n"
        "    record: {loss: loss}\n"
    )

    assert processor.process("step 3 loss=0.5") == MatchedLine(
        0, {"steps": "3"}, {"loss": "0.5"}
    )
