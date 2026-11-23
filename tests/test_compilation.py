import pytest

from tests.conftest import compile_spec, parse_yaml_spec
from zlog.context_updates import ConcatenateUpdate, NumericAddUpdate
from zlog.errors import SpecError
from zlog.pattern_aliases import FLOAT_REGEX


def test_compile_resolves_updates_resets_and_aliases() -> None:
    rules = compile_spec(
        parse_yaml_spec(
            "aliases: {d: '\\d+'}\n"
            "matches:\n"
            "  - {pattern: 'a %d %f', context: {+n: 1, '@w': 2}}\n"
            "  - {pattern: b, reset: all, context: {x: 0}}\n"
            "  - {pattern: c, reset: [n], record: {y: 0}}\n"
            "  - {pattern: d}\n"
        )
    )

    first, second, third, fourth = rules
    assert first.regex.pattern == rf"a (\d+) ({FLOAT_REGEX})"
    assert isinstance(first.context[0].update, NumericAddUpdate)
    assert isinstance(first.context[1].update, ConcatenateUpdate)
    assert second.reset == frozenset({"n", "w", "x"})
    assert third.reset == frozenset({"n"})
    assert third.record[0].name == "y"
    assert fourth.reset == frozenset()
    assert [rule.index for rule in rules] == [0, 1, 2, 3]


@pytest.mark.parametrize(
    ("spec_text", "message"),
    [
        ("matches: [{pattern: 'a(b)', record: {x: 2}}]", "has no group 2"),
        ("matches: [{pattern: 'a(b)', context: {x: n}}]", "has no group 'n'"),
        ("matches: [{pattern: 'a(', record: {x: 0}}]", "invalid regex"),
        (
            "matches: [{pattern: a, context: {+n: {value: one}}}]",
            "context variable \\+n: cannot add 'one'",
        ),
    ],
)
def test_invalid_rules_are_rejected(spec_text: str, message: str) -> None:
    with pytest.raises(SpecError, match=message):
        compile_spec(parse_yaml_spec(spec_text))


def test_numeric_constants_are_accepted_for_add() -> None:
    (rule,) = compile_spec(
        parse_yaml_spec("matches: [{pattern: a, context: {+n: {value: 2}}}]")
    )

    assert rule.context[0].name == "n"
