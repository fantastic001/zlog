import argparse
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from zlog import __version__
from zlog.application import (
    STDIN_ARGUMENT,
    ExtractionApplication,
    ExtractionRequest,
    StandardStreams,
)
from zlog.cli_rules import add_rule_arguments
from zlog.config import SettingsLoader
from zlog.errors import (
    ConfigurationError,
    ExtractionError,
    InputError,
    SpecError,
    ZlogError,
)
from zlog.options import FeatureState, FormulaEscaping
from zlog.plugins import EntryPointPluginLoader, PluginRegistry

LOGGER = logging.getLogger(__name__)

PROGRAM_NAME = "zlog"
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

CLI_SETTING_OPTIONS = (
    "output_format",
    "log_level",
    "concat_separator",
    "csv_delimiter",
    "formula_escaping",
    "file_encoding",
)

EXIT_CODES_BY_ERROR: tuple[tuple[type[Exception], int], ...] = (
    (ConfigurationError, EXIT_USAGE_ERROR),
    (SpecError, EXIT_USAGE_ERROR),
    (InputError, EXIT_FAILURE),
    (ExtractionError, EXIT_FAILURE),
    (ZlogError, EXIT_FAILURE),
    (OSError, EXIT_FAILURE),
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description=(
            "Match log lines with regex rules and write one CSV or JSON row "
            "per matched line, with persistent context variables and "
            "per-line record variables."
        ),
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        metavar="INPUT",
        help=f"log files to read; '{STDIN_ARGUMENT}' or none reads stdin",
    )
    parser.add_argument(
        "-s", "--spec", type=Path, help="YAML or JSON specification file"
    )
    add_rule_arguments(parser)
    add_output_arguments(parser)
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def add_output_arguments(parser: argparse.ArgumentParser) -> None:
    output = parser.add_argument_group("output and settings")
    output.add_argument(
        "-o", "--output", type=Path, help="write here instead of stdout"
    )
    output.add_argument(
        "--format", dest="output_format", help="csv, json, jsonl or a plugin"
    )
    output.add_argument(
        "--concat-separator", help="text between values joined with @"
    )
    output.add_argument("--csv-delimiter", help="one character, e.g. ';'")
    output.add_argument(
        "--formula-escaping",
        choices=[escaping.value for escaping in FormulaEscaping],
        help="prefix cells that a spreadsheet would run as formulas",
    )
    output.add_argument(
        "--encoding", dest="file_encoding", help="encoding of the inputs"
    )
    output.add_argument("--config", type=Path, help="TOML file with [zlog]")
    output.add_argument("--log-level", help="logging level, e.g. INFO")


def parse_request(
    argv: Sequence[str] | None, environ: Mapping[str, str]
) -> ExtractionRequest:
    arguments = build_argument_parser().parse_intermixed_args(argv)
    cli_overrides = {
        name: getattr(arguments, name)
        for name in CLI_SETTING_OPTIONS
        if getattr(arguments, name) is not None
    }
    settings = SettingsLoader().load(environ, arguments.config, cli_overrides)
    return ExtractionRequest(
        spec_file=arguments.spec,
        cli_rules=tuple(arguments.cli_rules or ()),
        inputs=tuple(arguments.inputs),
        output_file=arguments.output,
        settings=settings,
    )


def build_plugin_registry(plugins: FeatureState) -> PluginRegistry:
    registry = PluginRegistry()
    match plugins:
        case FeatureState.ENABLED:
            loaded = EntryPointPluginLoader().load_into(registry)
            LOGGER.info("loaded plugins: %s", ", ".join(loaded) or "none")
        case FeatureState.DISABLED:
            LOGGER.info("plugin loading disabled")
    return registry


def exit_code_for(error: Exception) -> int:
    return next(
        (
            code
            for error_type, code in EXIT_CODES_BY_ERROR
            if isinstance(error, error_type)
        ),
        EXIT_FAILURE,
    )


def execute_request(
    request: ExtractionRequest, streams: StandardStreams
) -> int:
    registry = build_plugin_registry(request.settings.plugins)
    try:
        summary = ExtractionApplication(request, registry, streams).run()
    except (ZlogError, OSError) as error:
        LOGGER.error("%s", error)
        return exit_code_for(error)
    else:
        LOGGER.info(
            "wrote %d rows from %d lines",
            summary.rows_written,
            summary.lines_read,
        )
        return EXIT_SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    try:
        request = parse_request(argv, os.environ)
    except ConfigurationError as error:
        print(f"{PROGRAM_NAME}: {error}", file=sys.stderr)
        return EXIT_USAGE_ERROR
    else:
        logging.basicConfig(
            level=request.settings.log_level,
            format=LOG_FORMAT,
            stream=sys.stderr,
            force=True,
        )
        return execute_request(
            request, StandardStreams(sys.stdin.buffer, sys.stdout.buffer)
        )
