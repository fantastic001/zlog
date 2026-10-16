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


class MarkdownReportRenderer:
    def render(self, sections: Sequence[ReportSection]) -> str:
        return "\n\n".join(map(self._render_section, sections)) + "\n"

    @staticmethod
    def _render_section(section: ReportSection) -> str:
        heading = f"# {escape_markdown_cell(section.title)}"
        if section.rows:
            frame = build_sanitized_frame(section, escape_markdown_cell)
            return f"{heading}\n\n{frame.to_markdown(index=False)}"
        else:
            return heading


class CsvReportRenderer:
    def render(self, sections: Sequence[ReportSection]) -> str:
        return "\n".join(map(self._render_section, sections))

    @staticmethod
    def _render_section(section: ReportSection) -> str:
        heading = f"# {section.title}\n"
        if section.rows:
            frame = build_sanitized_frame(
                section, neutralize_spreadsheet_formula
            )
            return heading + frame.to_csv(index=False)
        else:
            return heading


class JsonReportRenderer:
    def render(self, sections: Sequence[ReportSection]) -> str:
        document = [
            {
                "title": section.title,
                "rows": [to_json_compatible(row) for row in section.rows],
            }
            for section in sections
        ]
        return json.dumps(document, indent=2, allow_nan=False) + "\n"


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
