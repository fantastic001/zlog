import argparse
from collections.abc import Sequence

import pytest

from tests.conftest import (
    EXAMPLES_DIRECTORY,
    create_rule_factory,
    parse_yaml_spec,
)
from zlog.cli_rules import (
    PendingCliRule,
    add_rule_arguments,
    build_cli_rules,
    parse_group_reference,
)
from zlog.errors import SpecError
from zlog.options import BindingSection, ResetScope
from zlog.rules import Binding, MatchRule, ResetSelection
from zlog.value_sources import ConstantSource, GroupSource
from zlog.variable_names import VariableName


def parse_rules(argv: Sequence[str]) -> tuple[MatchRule, ...]:
    parser = argparse.ArgumentParser()
    add_rule_arguments(parser)
    parser.add_argument("inputs", nargs="*")
    arguments = parser.parse_intermixed_args(argv)
    return build_cli_rules(arguments.cli_rules or [], create_rule_factory())


def test_bindings_take_groups_in_order_across_sections() -> None:
    (first, second) = parse_rules(
        ["-p", "P1", "-r", "A", "-r", "B", "-c", "C"]
        + ["-p", "P2", "-r", "A", "-c", "+C"]
    )

    assert first.record == (
        Binding(VariableName("A"), GroupSource(1)),
        Binding(VariableName("B"), GroupSource(2)),
    )
    assert first.context == (Binding(VariableName("C"), GroupSource(3)),)
    assert second.record == (Binding(VariableName("A"), GroupSource(1)),)
    assert second.context == (Binding(VariableName("C", "+"), GroupSource(2)),)


def test_explicit_references_and_constants_do_not_advance() -> None:
    (rule,) = parse_rules(
        ["-p", "x", "-c", "a=3", "-r", "tag:=a=b", "-r", "b", "-r", "n=name"]
        + ["-c", "@d"]
    )

    assert rule.context == (
        Binding(VariableName("a"), GroupSource(3)),
        Binding(VariableName("d", "@"), GroupSource(2)),
    )
    assert rule.record == (
        Binding(VariableName("tag"), ConstantSource("a=b")),
        Binding(VariableName("b"), GroupSource(1)),
        Binding(VariableName("n"), GroupSource("name")),
    )


def test_resets_attach_to_the_current_rule() -> None:
    rules = parse_rules(
        ["-p", "a", "--reset", "x", "--reset", "y", "-c", "x", "-c", "y"]
        + ["-p", "b", "--reset-all", "--reset-all", "-p", "c"]
    )

    assert [rule.reset for rule in rules] == [
        ResetSelection(ResetScope.LISTED, ("x", "y")),
        ResetSelection(ResetScope.ALL),
        ResetSelection(),
    ]


def test_inputs_may_be_interleaved_with_rules() -> None:
    parser = argparse.ArgumentParser()
    add_rule_arguments(parser)
    parser.add_argument("inputs", nargs="*")

    arguments = parser.parse_intermixed_args(
        ["a.log", "-p", "x", "-r", "v", "b.log", "-p", "y"]
    )

    assert arguments.inputs == ["a.log", "b.log"]
    assert len(arguments.cli_rules) == 2


def test_pattern_with_a_leading_dash_uses_equals_form() -> None:
    (rule,) = parse_rules(["--pattern=-x (\\d)", "-r", "v"])

    assert rule.pattern == "-x (\\d)"


@pytest.mark.parametrize(
    "argv",
    [
        ["-c", "x"],
        ["-r", "x", "-p", "a"],
        ["--reset", "x"],
        ["--reset-all"],
        ["-p", "a", "-c", "=x"],
        ["-p", "a", "-c", "x="],
        ["-p", "a", "-r", "x:y"],
        ["-p", "a", "--reset", "x", "--reset-all"],
        ["-p", "a", "--reset-all", "--reset", "x"],
    ],
)
def test_invalid_rule_options_are_usage_errors(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        parse_rules(argv)

    assert raised.value.code == 2


def test_invalid_names_surface_when_rules_are_built() -> None:
    with pytest.raises(SpecError, match="invalid variable name"):
        parse_rules(["-p", "a", "-c", "1x"])


@pytest.mark.parametrize(
    ("operand", "expected"), [("2", 2), ("0", 0), ("name", "name")]
)
def test_parse_group_reference(operand: str, expected: int | str) -> None:
    assert parse_group_reference(operand) == expected


def test_parse_group_reference_rejects_empty_operand() -> None:
    with pytest.raises(SpecError, match="must not be empty"):
        parse_group_reference("")


def test_pending_rule_rejects_unknown_operator() -> None:
    rule = PendingCliRule("a")

    with pytest.raises(SpecError, match="unknown binding operator"):
        rule._build_source("~", "x")

    rule.add_binding(BindingSection.RECORD, "x")
    assert rule.to_rule(create_rule_factory()).record == (
        Binding(VariableName("x"), GroupSource(1)),
    )


def test_cli_form_of_the_example_equals_the_yaml_spec() -> None:
    yaml_spec = parse_yaml_spec(
        (EXAMPLES_DIRECTORY / "train.yaml").read_text(encoding="utf-8")
    )
    cli_rules = parse_rules(
        ["-p", "^=+ run %w", "--reset", "epoch", "--reset", "samples"]
        + ["--reset", "warnings", "-c", "run", "-c", "+run_index:=1"]
        + ["-r", "event:=start"]
        + ["-p", "epoch %d loss=%f acc=%f", "-c", "epoch"]
        + ["-r", "event:=epoch", "-r", "loss", "-r", "acc"]
        + ["-p", "processed %d samples", "-c", "+samples"]
        + ["-r", "event:=progress"]
        + ["-p", "warning: %s", "-c", "@warnings"]
        + ["-r", "event:=warning"]
    )

    assert cli_rules == yaml_spec.matches
