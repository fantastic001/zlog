import pytest

from zlog.errors import SpecError
from zlog.regex_macros import FLOAT_REGEX, RegexMacroExpander


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("accuracy: 0.95", "0.95"),
        ("accuracy:-1.5", "-1.5"),
        ("accuracy: .5", ".5"),
        ("accuracy: nan", "nan"),
        ("accuracy: infinity", "infinity"),
        ("run 3 accuracy :  +7", "+7"),
    ],
)
def test_float_macro_captures_numbers(text: str, expected: str) -> None:
    pattern = RegexMacroExpander().compile(r"accuracy\s\:\s(\f)")

    found = pattern.search(text)

    assert found is not None
    assert found.group(1) == expected


def test_expand_replaces_float_macro() -> None:
    assert RegexMacroExpander().expand(r"(\f)") == f"({FLOAT_REGEX})"


def test_additional_macros_extend_defaults() -> None:
    expander = RegexMacroExpander().with_additional_macros({r"\i": r"\d+"})

    assert expander.expand(r"(\i) (\f)") == rf"(\d+) ({FLOAT_REGEX})"


def test_additional_macros_leave_original_untouched() -> None:
    original = RegexMacroExpander()
    original.with_additional_macros({r"\i": r"\d+"})

    assert original.expand(r"\i") == r"\i"


def test_compile_rejects_invalid_regex() -> None:
    with pytest.raises(SpecError, match="invalid regex"):
        RegexMacroExpander().compile("(unclosed")
