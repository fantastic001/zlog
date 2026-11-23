import argparse
import logging
import re
from collections.abc import Sequence
from typing import Any

from zlog.errors import SpecError
from zlog.options import BindingSection, ResetScope
from zlog.rule_factory import RawBinding, RuleFactory
from zlog.rules import MatchRule, ResetSelection
from zlog.value_sources import (
    ConstantSource,
    GroupReference,
    GroupSource,
    UnnamedGroupSource,
    ValueSource,
)

LOGGER = logging.getLogger(__name__)

CLI_RULES_DESTINATION = "cli_rules"
GROUP_OPERATOR = "="
CONSTANT_OPERATOR = ":="
BINDING_ARGUMENT_PATTERN = re.compile(
    r"(?P<name>[^:=]+)(?:(?P<operator>:=|=)(?P<operand>.*))?", re.DOTALL
)


def parse_group_reference(operand: str) -> GroupReference:
    if operand.isascii() and operand.isdigit():
        return int(operand)
    elif operand:
        return operand
    else:
        raise SpecError("a group reference after '=' must not be empty")


class PendingCliRule:
    def __init__(self, pattern: str) -> None:
        self._pattern = pattern
        self._reset_scope = ResetScope.NONE
        self._reset_names: list[str] = []
        self._bindings: dict[BindingSection, list[RawBinding]] = {
            section: [] for section in BindingSection
        }
        self._bare_name_count = 0

    def add_binding(self, section: BindingSection, argument: str) -> None:
        found = BINDING_ARGUMENT_PATTERN.fullmatch(argument)
        if found is not None:
            source = self._build_source(
                found.group("operator"), found.group("operand")
            )
            self._bindings[section].append((found.group("name"), source))
        else:
            raise SpecError(
                f"invalid binding {argument!r}: expected NAME, "
                f"NAME{GROUP_OPERATOR}GROUP or NAME{CONSTANT_OPERATOR}VALUE"
            )

    def add_reset_name(self, name: str) -> None:
        match self._reset_scope:
            case ResetScope.ALL:
                raise SpecError("--reset cannot be combined with --reset-all")
            case ResetScope.NONE | ResetScope.LISTED:
                self._reset_scope = ResetScope.LISTED
                self._reset_names.append(name)

    def reset_all(self) -> None:
        match self._reset_scope:
            case ResetScope.LISTED:
                raise SpecError("--reset-all cannot be combined with --reset")
            case ResetScope.NONE | ResetScope.ALL:
                self._reset_scope = ResetScope.ALL

    def to_rule(self, factory: RuleFactory) -> MatchRule:
        return factory.create(
            self._pattern,
            ResetSelection(self._reset_scope, tuple(self._reset_names)),
            tuple(self._bindings[BindingSection.CONTEXT]),
            tuple(self._bindings[BindingSection.RECORD]),
        )

    def _build_source(self, operator: str | None, operand: str) -> ValueSource:
        match operator:
            case None:
                self._bare_name_count += 1
                return UnnamedGroupSource(self._bare_name_count)
            case "=":
                return GroupSource(parse_group_reference(operand))
            case ":=":
                return ConstantSource(operand)
            case _:
                raise SpecError(f"unknown binding operator {operator!r}")


class PatternAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[object] | None,
        option_string: str | None = None,
    ) -> None:
        rules = list(getattr(namespace, CLI_RULES_DESTINATION, None) or [])
        rules.append(PendingCliRule(str(values)))
        setattr(namespace, CLI_RULES_DESTINATION, rules)


class RuleModifierAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[object] | None,
        option_string: str | None = None,
    ) -> None:
        rules = getattr(namespace, CLI_RULES_DESTINATION, None)
        if rules:
            self._modify_rule_or_report(parser, rules[-1], str(values))
        else:
            parser.error(f"{option_string} must follow --pattern")

    def _modify_rule_or_report(
        self,
        parser: argparse.ArgumentParser,
        rule: PendingCliRule,
        value: str,
    ) -> None:
        try:
            self.modify_rule(rule, value)
        except SpecError as error:
            parser.error(str(error))

    def modify_rule(self, rule: PendingCliRule, value: str) -> None:
        raise NotImplementedError


class ContextBindingAction(RuleModifierAction):
    def modify_rule(self, rule: PendingCliRule, value: str) -> None:
        rule.add_binding(BindingSection.CONTEXT, value)


class RecordBindingAction(RuleModifierAction):
    def modify_rule(self, rule: PendingCliRule, value: str) -> None:
        rule.add_binding(BindingSection.RECORD, value)


class ResetNameAction(RuleModifierAction):
    def modify_rule(self, rule: PendingCliRule, value: str) -> None:
        rule.add_reset_name(value)


class ResetAllAction(RuleModifierAction):
    def __init__(
        self, option_strings: Sequence[str], dest: str, **options: Any
    ) -> None:
        super().__init__(option_strings, dest, nargs=0, **options)

    def modify_rule(self, rule: PendingCliRule, value: str) -> None:
        rule.reset_all()


def build_cli_rules(
    pending_rules: Sequence[PendingCliRule], factory: RuleFactory
) -> tuple[MatchRule, ...]:
    rules = tuple(pending.to_rule(factory) for pending in pending_rules)
    LOGGER.debug("built %d rules from the command line", len(rules))
    return rules


def add_rule_arguments(parser: argparse.ArgumentParser) -> None:
    rules = parser.add_argument_group(
        "rules",
        "Each --pattern starts a rule; the options after it modify that rule. "
        "A binding is NAME (next unnamed group), NAME=GROUP (index or group "
        "name) or NAME:=VALUE (constant). Context names may start with + "
        "(add) or @ (concatenate). In REGEX, %d %f %x %s %w %r capture an "
        "integer, a number, a hex number, a non-space token, a word or the "
        "rest of the line; %*f skips the group and %% is a literal %. "
        "%(NAME)f binds the record variable NAME, and %(=NAME)f, %(+NAME)f "
        "and %(@NAME)f bind the context variable NAME (replace, add, "
        "concatenate).",
    )
    rules.add_argument(
        "-p",
        "--pattern",
        action=PatternAction,
        dest=CLI_RULES_DESTINATION,
        metavar="REGEX",
        help="start a rule matching REGEX (use --pattern=-... for a "
        "leading dash)",
    )
    rules.add_argument(
        "-c",
        "--context",
        action=ContextBindingAction,
        default=argparse.SUPPRESS,
        metavar="BINDING",
        help="set a context variable, kept across lines",
    )
    rules.add_argument(
        "-r",
        "--record",
        action=RecordBindingAction,
        default=argparse.SUPPRESS,
        metavar="BINDING",
        help="set a record variable for the matched line only",
    )
    rules.add_argument(
        "--reset",
        action=ResetNameAction,
        default=argparse.SUPPRESS,
        metavar="NAME",
        help="clear a context variable before this rule's updates",
    )
    rules.add_argument(
        "--reset-all",
        action=ResetAllAction,
        default=argparse.SUPPRESS,
        help="clear every context variable before this rule's updates",
    )
