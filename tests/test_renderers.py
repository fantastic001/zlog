import json
import math

from zlog.renderers import (
    BUILTIN_OUTPUT_FORMATS,
    CsvReportRenderer,
    JsonReportRenderer,
    MarkdownReportRenderer,
    escape_markdown_cell,
    neutralize_spreadsheet_formula,
    to_json_compatible,
)
from zlog.reporting import ReportSection

SECTIONS = (
    ReportSection(
        "Summary",
        (
            {"group": "a|b", "acc": "1.0 +- 0.0 (N=2)"},
            {"group": "=cmd()", "acc": "<b>"},
        ),
    ),
    ReportSection("Empty"),
)


def test_markdown_renders_escaped_table() -> None:
    report = MarkdownReportRenderer().render(SECTIONS)

    assert report.startswith("# Summary\n\n| group")
    assert "a\\|b" in report
    assert "&lt;b&gt;" in report
    assert report.endswith("# Empty\n")


def test_csv_neutralizes_formulas() -> None:
    report = CsvReportRenderer().render(SECTIONS)

    assert "'=cmd()" in report
    assert report.splitlines()[0] == "# Summary"
    assert report.splitlines()[1] == "group,acc"
    assert report.endswith("# Empty\n")


def test_json_converts_non_finite_values() -> None:
    sections = (
        ReportSection("S", ({"mean": math.nan, "cell": {"std": math.inf}},)),
    )

    document = json.loads(JsonReportRenderer().render(sections))

    assert document == [
        {"title": "S", "rows": [{"mean": None, "cell": {"std": None}}]}
    ]


def test_cell_sanitizers_leave_non_strings_untouched() -> None:
    assert escape_markdown_cell(1.5) == 1.5
    assert neutralize_spreadsheet_formula(None) is None
    assert neutralize_spreadsheet_formula("-1.5") == "-1.5"
    assert to_json_compatible(True) is True


def test_builtin_formats_are_registered() -> None:
    assert set(BUILTIN_OUTPUT_FORMATS) == {"markdown", "csv", "json"}


DESCRIBED_SECTIONS = (
    ReportSection(
        "Loss <plot>",
        ({"partition": "adam", "mean": 1.0},),
        description="Loss of\nadam & sgd",
        attachments=("plots/loss plot.png",),
    ),
)


def test_markdown_renders_description_and_attachments() -> None:
    report = MarkdownReportRenderer().render(DESCRIBED_SECTIONS)

    assert report.startswith(
        "# Loss &lt;plot&gt;\n\n"
        "Loss of\nadam &amp; sgd\n\n"
        "![Loss &lt;plot&gt;](<plots/loss plot.png>)\n\n"
        "| partition"
    )


def test_csv_renders_description_and_attachments_as_comments() -> None:
    lines = CsvReportRenderer().render(DESCRIBED_SECTIONS).splitlines()

    assert lines[:4] == [
        "# Loss <plot>",
        "# Loss of adam & sgd",
        "# attachment: plots/loss plot.png",
        "partition,mean",
    ]


def test_json_includes_only_present_optional_fields() -> None:
    document = json.loads(
        JsonReportRenderer().render((*DESCRIBED_SECTIONS, ReportSection("E")))
    )

    assert document[0]["description"] == "Loss of\nadam & sgd"
    assert document[0]["attachments"] == ["plots/loss plot.png"]
    assert document[1] == {"title": "E", "rows": []}
