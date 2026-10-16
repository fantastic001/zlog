import argparse
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO, TextIO

from zlog import __version__
from zlog.application import AnalysisApplication, AnalysisRequest
from zlog.config import SettingsLoader
from zlog.errors import ConfigurationError, ZlogError
from zlog.options import (
    CheckpointMode,
    ComparisonFilter,
    FeatureState,
    InputKind,
    MatchPolicy,
    Verbosity,
)
from zlog.plugins import EntryPointPluginLoader, PluginRegistry

LOGGER = logging.getLogger(__name__)

PROGRAM_NAME = "zlog-analyze"
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2
STDIN_INPUT_ARGUMENT = "-"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
REPORT_ENCODING = "utf-8"

CLI_SETTING_OPTIONS = (
    "output_format",
    "match_policy",
    "log_level",
    "checkpoint_file",
    "plot_directory",
)

VERBOSITY_BY_FLAG: Mapping[bool, Verbosity] = MappingProxyType(
    {False: Verbosity.QUIET, True: Verbosity.VERBOSE}
)
COMPARISON_FILTER_BY_FLAG: Mapping[bool, ComparisonFilter] = MappingProxyType(
    {
        False: ComparisonFilter.ALL,
        True: ComparisonFilter.SAME_DISTRIBUTION_ONLY,
    }
)
CHECKPOINT_MODE_BY_FLAG: Mapping[bool, CheckpointMode] = MappingProxyType(
    {False: CheckpointMode.RESUME, True: CheckpointMode.RESTART}
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description="Analyze outputs from different iterations",
    )
    parser.add_argument(
        "spec_file", type=Path, help="Specification file for the analysis"
    )
    parser.add_argument(
        "input_dir",
        help=(
            "Directory containing the output files to analyze, "
            f"or '{STDIN_INPUT_ARGUMENT}' to read one log from stdin"
        ),
    )
    parser.add_argument(
        "--stdin-labels",
        default="",
        help=(
            "Separator-joined group labels for stdin input, used in place "
            "of a directory name (e.g. adam-small)"
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print extracted values of every iteration to stderr",
    )
    parser.add_argument(
        "--same-distributions-only",
        action="store_true",
        help="Show comparisons only for groups with the same distribution",
    )
    parser.add_argument(
        "--config", type=Path, help="TOML file with a [zlog] table"
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        help="Report format: markdown, csv, json or a plugin format",
    )
    parser.add_argument(
        "--match-policy",
        choices=[policy.value for policy in MatchPolicy],
        help="Which matching line wins when a pattern matches repeatedly",
    )
    parser.add_argument("--log-level", help="Logging level, e.g. INFO")
    parser.add_argument(
        "--checkpoint",
        dest="checkpoint_file",
        help="JSON file caching extracted values for resumable runs",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Ignore the existing checkpoint and start from scratch",
    )
    parser.add_argument(
        "--output", type=Path, help="Write the report here, not stdout"
    )
    parser.add_argument(
        "--plot-dir",
        dest="plot_directory",
        help=(
            "Directory for plot images (default: the --output file's "
            "directory, or the current directory)"
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def parse_request(
    argv: Sequence[str] | None, environ: Mapping[str, str]
) -> AnalysisRequest:
    arguments = build_argument_parser().parse_args(argv)
    cli_overrides = {
        name: getattr(arguments, name)
        for name in CLI_SETTING_OPTIONS
        if getattr(arguments, name) is not None
    }
    settings = SettingsLoader().load(environ, arguments.config, cli_overrides)
    return AnalysisRequest(
        spec_file=arguments.spec_file,
        input_path=Path(arguments.input_dir),
        input_kind=select_input_kind(arguments.input_dir),
        stdin_labels=arguments.stdin_labels,
        output_file=arguments.output,
        verbosity=VERBOSITY_BY_FLAG[arguments.verbose],
        comparison_filter=COMPARISON_FILTER_BY_FLAG[
            arguments.same_distributions_only
        ],
        checkpoint_mode=CHECKPOINT_MODE_BY_FLAG[arguments.restart],
        settings=settings,
    )


def select_input_kind(input_argument: str) -> InputKind:
    if input_argument == STDIN_INPUT_ARGUMENT:
        return InputKind.STDIN
    else:
        return InputKind.DIRECTORY


def build_plugin_registry(plugins: FeatureState) -> PluginRegistry:
    registry = PluginRegistry()
    match plugins:
        case FeatureState.ENABLED:
            loaded = EntryPointPluginLoader().load_into(registry)
            LOGGER.info("loaded plugins: %s", ", ".join(loaded) or "none")
        case FeatureState.DISABLED:
            LOGGER.info("plugin loading disabled")
    return registry


def write_report(report: str, output_file: Path | None, stdout: TextIO) -> None:
    match output_file:
        case None:
            stdout.write(report)
        case Path():
            output_file.write_text(report, encoding=REPORT_ENCODING)
            LOGGER.info("wrote %d characters to %s", len(report), output_file)


def execute_request(
    request: AnalysisRequest, stdin: BinaryIO, stdout: TextIO, stderr: TextIO
) -> int:
    registry = build_plugin_registry(request.settings.plugins)
    try:
        report = AnalysisApplication(request, registry, stdin, stderr).run()
        write_report(report, request.output_file, stdout)
    except ZlogError as error:
        LOGGER.error("%s", error)
        return EXIT_USAGE_ERROR
    except OSError as error:
        LOGGER.error("I/O failure: %s", error)
        return EXIT_FAILURE
    else:
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
            request, sys.stdin.buffer, sys.stdout, sys.stderr
        )
