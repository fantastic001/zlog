import html
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

import pandas as pd

from zlog.reporting import (
    MetricCellFormatter,
    ReportSection,
    StructuredMetricCellFormatter,
    TextMetricCellFormatter,
)

SPREADSHEET_FORMULA_TRIGGERS = ("=", "@", "\t", "\r")
SPREADSHEET_ESCAPE_PREFIX = "'"
MARKDOWN_PIPE = "|"
MARKDOWN_ESCAPED_PIPE = "\\|"
CSV_COMMENT_PREFIX = "# "
CSV_ATTACHMENT_PREFIX = "# attachment: "


class ReportRenderer(Protocol):
    def render(self, sections: Sequence[ReportSection]) -> str: ...


def escape_markdown_cell(value: object) -> object:
    match value:
        case str():
            escaped = html.escape(value, quote=False)
            return escaped.replace(MARKDOWN_PIPE, MARKDOWN_ESCAPED_PIPE)
        case _:
            return value


def neutralize_spreadsheet_formula(value: object) -> object:
    match value:
        case str() if value.startswith(SPREADSHEET_FORMULA_TRIGGERS):
            return SPREADSHEET_ESCAPE_PREFIX + value
        case _:
            return value


def to_json_compatible(value: object) -> object:
    match value:
        case float() if not math.isfinite(value):
            return None
        case Mapping():
            return {
                str(key): to_json_compatible(item)
                for key, item in value.items()
            }
        case _:
            return value


def build_sanitized_frame(
    section: ReportSection, sanitize_cell: Callable[[object], object]
) -> pd.DataFrame:
    frame = pd.DataFrame([dict(row) for row in section.rows])
    frame.columns = [str(sanitize_cell(column)) for column in frame.columns]
    return frame.map(sanitize_cell)


def flatten_to_line(text: str) -> str:
    return " ".join(text.split())


class MarkdownReportRenderer:
    def render(self, sections: Sequence[ReportSection]) -> str:
        return "\n\n".join(map(self._render_section, sections)) + "\n"

    def _render_section(self, section: ReportSection) -> str:
        blocks = (
            f"# {escape_markdown_cell(section.title)}",
            *self._render_description(section),
            *self._render_attachments(section),
            *self._render_rows(section),
        )
        return "\n\n".join(blocks)

    @staticmethod
    def _render_description(section: ReportSection) -> tuple[str, ...]:
        match section.description.strip():
            case "":
                return ()
            case description:
                return (html.escape(description, quote=False),)

    @staticmethod
    def _render_attachments(section: ReportSection) -> tuple[str, ...]:
        alt_text = html.escape(flatten_to_line(section.title), quote=False)
        return tuple(
            f"![{alt_text}](<{html.escape(link)}>)"
            for link in section.attachments
        )

    @staticmethod
    def _render_rows(section: ReportSection) -> tuple[str, ...]:
        if section.rows:
            frame = build_sanitized_frame(section, escape_markdown_cell)
            return (frame.to_markdown(index=False),)
        else:
            return ()


class CsvReportRenderer:
    def render(self, sections: Sequence[ReportSection]) -> str:
        return "\n".join(map(self._render_section, sections))

    def _render_section(self, section: ReportSection) -> str:
        attachment_lines = tuple(
            f"{CSV_ATTACHMENT_PREFIX}{link}\n" for link in section.attachments
        )
        heading = "".join(
            (
                f"# {section.title}\n",
                *self._render_description_lines(section),
                *attachment_lines,
            )
        )
        if section.rows:
            frame = build_sanitized_frame(
                section, neutralize_spreadsheet_formula
            )
            return heading + frame.to_csv(index=False)
        else:
            return heading

    @staticmethod
    def _render_description_lines(section: ReportSection) -> tuple[str, ...]:
        match flatten_to_line(section.description):
            case "":
                return ()
            case description:
                return (f"{CSV_COMMENT_PREFIX}{description}\n",)


class JsonReportRenderer:
    def render(self, sections: Sequence[ReportSection]) -> str:
        document = list(map(self._describe_section, sections))
        return json.dumps(document, indent=2, allow_nan=False) + "\n"

    @staticmethod
    def _describe_section(section: ReportSection) -> dict[str, object]:
        optional_fields = {
            "description": section.description,
            "attachments": list(section.attachments),
        }
        return {
            "title": section.title,
            **{name: value for name, value in optional_fields.items() if value},
            "rows": [to_json_compatible(row) for row in section.rows],
        }


@dataclass(frozen=True)
class OutputFormatPlugin:
    create_renderer: Callable[[], ReportRenderer]
    create_cell_formatter: Callable[[], MetricCellFormatter]


BUILTIN_OUTPUT_FORMATS: Mapping[str, OutputFormatPlugin] = MappingProxyType(
    {
        "markdown": OutputFormatPlugin(
            MarkdownReportRenderer, TextMetricCellFormatter
        ),
        "csv": OutputFormatPlugin(CsvReportRenderer, TextMetricCellFormatter),
        "json": OutputFormatPlugin(
            JsonReportRenderer, StructuredMetricCellFormatter
        ),
    }
)
