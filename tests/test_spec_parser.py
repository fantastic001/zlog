import pytest

from tests.conftest import create_rule_factory, parse_yaml_spec
from zlog.errors import SpecError
from zlog.options import ResetScope
from zlog.rules import Binding, ResetSelection
from zlog.spec_parser import SpecParser, format_constant, parse_value_source
from zlog.value_sources import ConstantSource, GroupSource
from zlog.variable_names import VariableName


def test_parse_full_rule() -> None:
    spec = parse_yaml_spec(
        "aliases: {ts: '\\d+:\\d+'}\n"
        "matches:\n"
        "  - pattern: 'run (\\w+)'\n"
        "    reset: [n]\n"
        "    context: {run: 1, +n: {value: 1}, '@w': name}\n"
        "    record: {event: {value: start}}\n"
        "  - pattern: other\n"
        "    reset: all\n"
    )

    first, second = spec.matches
    assert spec.aliases == {"ts": r"\d+:\d+"}
    assert first.pattern == r"run (\w+)"
    assert first.reset == ResetSelection(ResetScope.LISTED, ("n",))
    assert first.context == (
        Binding(VariableName("run"), GroupSource(1)),
        Binding(VariableName("n", "+"), ConstantSource("1")),
        Binding(VariableName("w", "@"), GroupSource("name")),
    )
    assert first.record == (
        Binding(VariableName("event"), ConstantSource("start")),
    )
    assert second.reset == ResetSelection(ResetScope.ALL)
    assert second.context == second.record == ()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, GroupSource(0)),
        (2, GroupSource(2)),
        ("name", GroupSource("name")),
        ({"value": "text"}, ConstantSource("text")),
        ({"value": 7}, ConstantSource("7")),
        ({"value": 0.5}, ConstantSource("0.5")),
        ({"value": ""}, ConstantSource("")),
    ],
)
def test_parse_value_source(raw: object, expected: object) -> None:
    assert parse_value_source(raw, "field") == expected


@pytest.mark.parametrize(
    "raw",
    [True, -1, "", None, [1], {}, {"value": 1, "group": 2}, {"group": 1}],
)
def test_invalid_value_sources_are_rejected(raw: object) -> None:
    with pytest.raises(SpecError, match="field"):
        parse_value_source(raw, "field")


@pytest.mark.parametrize("raw", [True, None, [1], {"a": 1}])
def test_invalid_constants_are_rejected(raw: object) -> None:
    with pytest.raises(SpecError, match="field: constant"):
        format_constant(raw, "field")


def test_bool_constant_suggests_quoting() -> None:
    with pytest.raises(SpecError, match="quote it"):
        parse_yaml_spec("matches: [{pattern: a, record: {x: {value: yes}}}]")


@pytest.mark.parametrize(
    ("spec_text", "message"),
    [
        ("[1, 2]", "must be a mapping with 'matches'"),
        ("{}", "must be a mapping with 'matches'"),
        ("{groups: [a], patterns: []}", "old zlog specification"),
        ("{matches: []}", "non-empty list"),
        ("{matches: {pattern: a}}", "non-empty list"),
        ("{matches: [{pattern: a}], extra: 1}", "unknown keys extra"),
        ("{matches: [{pattern: a, names: [x]}]}", "unknown keys names"),
        ("{matches: [a]}", r"matches\[0\] must be a mapping"),
        ("{matches: [{regex: a}]}", "needs a 'pattern' string"),
        ("{matches: [{pattern: 3}]}", "needs a 'pattern' string"),
        ("{matches: [{pattern: a, context: [x]}]}", "context must map"),
        ("{matches: [{pattern: a, record: {1: 1}}]}", "record must map"),
        ("{matches: [{pattern: a, reset: x}]}", "reset must be 'all'"),
        ("{matches: [{pattern: a, reset: []}]}", "reset must be 'all'"),
        ("{matches: [{pattern: a, reset: [1]}]}", "reset must be 'all'"),
        ("{matches: [{pattern: a}], aliases: [x]}", "'aliases' must map"),
        ("{matches: [{pattern: a}], aliases: {x: 1}}", "'aliases' must map"),
        ("{matches: [{pattern: a}], macros: {x: y}}", "unknown keys macros"),
    ],
)
def test_invalid_specs_are_rejected(spec_text: str, message: str) -> None:
    with pytest.raises(SpecError, match=message):
        parse_yaml_spec(spec_text)


def test_parser_uses_the_given_factory_prefixes() -> None:
    parser = SpecParser(create_rule_factory())

    spec = parser.parse({"matches": [{"pattern": "a", "context": {"+n": 0}}]})

    assert spec.matches[0].context[0].variable == VariableName("n", "+")
