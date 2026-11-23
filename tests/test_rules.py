from zlog.rules import (
    Binding,
    ColumnLayout,
    ExtractionSpec,
    MatchRule,
    derive_column_layout,
)
from zlog.value_sources import GroupSource
from zlog.variable_names import VariableName


def bind(name: str, prefix: str = "") -> Binding:
    return Binding(VariableName(name, prefix), GroupSource(1))


SPEC = ExtractionSpec(
    (
        MatchRule("a", context=(bind("run"),), record=(bind("loss"),)),
        MatchRule(
            "b",
            context=(bind("epoch"), bind("run", "+")),
            record=(bind("acc"), bind("loss")),
        ),
    )
)


def test_names_keep_first_appearance_order_without_duplicates() -> None:
    assert SPEC.context_names == ("run", "epoch")
    assert SPEC.record_names == ("loss", "acc")


def test_with_additional_matches_appends_rules() -> None:
    extra = MatchRule("c", record=(bind("extra"),))

    combined = SPEC.with_additional_matches([extra])

    assert combined.matches == (*SPEC.matches, extra)
    assert combined.aliases == SPEC.aliases
    assert SPEC.record_names == ("loss", "acc")


def test_layout_header_and_arrangement() -> None:
    layout = derive_column_layout(SPEC, "path")

    assert layout == ColumnLayout("path", ("run", "epoch"), ("loss", "acc"))
    assert layout.header == ("path", "run", "epoch", "loss", "acc")
    assert layout.arrange("x.log", {"run": "adam"}, {"acc": "0.5"}) == (
        "x.log",
        "adam",
        None,
        None,
        "0.5",
    )
