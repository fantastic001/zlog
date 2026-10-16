import pytest

from zlog.capture_names import CaptureTarget, parse_capture_name
from zlog.options import AssignmentMode


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("loss", CaptureTarget("loss", AssignmentMode.REPLACE)),
        ("+loss", CaptureTarget("loss", AssignmentMode.APPEND)),
        ("a+b", CaptureTarget("a+b", AssignmentMode.REPLACE)),
    ],
)
def test_parse_capture_name(raw_name: str, expected: CaptureTarget) -> None:
    assert parse_capture_name(raw_name) == expected


@pytest.mark.parametrize("raw_name", ["", "+"])
def test_rejects_empty_name(raw_name: str) -> None:
    with pytest.raises(ValueError):
        parse_capture_name(raw_name)
