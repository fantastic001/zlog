import pytest

from zlog.group_labels import GroupLabeler, find_varying_groups

ABC = (("g1", "a"), ("g2", "b"), ("g3", "c"))
ADF = (("g1", "a"), ("g2", "d"), ("g3", "f"))
ABF = (("g1", "a"), ("g2", "b"), ("g3", "f"))


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        ([ABC, ADF], ("g2", "g3")),
        ([ABC, ABF], ("g3",)),
        ([ABC], ()),
        ([], ()),
    ],
)
def test_find_varying_groups_keeps_declaration_order(
    groups: list[tuple[tuple[str, str], ...]], expected: tuple[str, ...]
) -> None:
    assert find_varying_groups(groups) == expected


def test_labeler_shows_only_varying_groups() -> None:
    labeler = GroupLabeler.for_varying_groups([ABC, ADF])

    assert labeler.label(ABC) == "b, c"
    assert labeler.without("g2").label(ABC) == "c"
    assert labeler.without(None).label(ADF) == "d, f"
    assert labeler.find_hidden_names([ABC, ADF]) == frozenset({"g1"})
