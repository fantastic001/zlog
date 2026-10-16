import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from zlog.domain import GroupKey, GroupRun, IterationSource
from zlog.errors import InputError

LOGGER = logging.getLogger(__name__)

STDIN_RUN_PATH = Path("<stdin>")
STDIN_ITERATION = 0


class GroupLabelParser:
    def __init__(
        self, group_names: Sequence[str], group_separator: str
    ) -> None:
        if group_separator:
            self._group_names = tuple(group_names)
            self._group_separator = group_separator
        else:
            raise ValueError("group separator must not be empty")

    @property
    def group_names(self) -> tuple[str, ...]:
        return self._group_names

    @property
    def group_separator(self) -> str:
        return self._group_separator

    def parse(self, joined_labels: str) -> GroupKey | None:
        labels = joined_labels.split(self._group_separator)
        if len(labels) >= len(self._group_names):
            return tuple(zip(self._group_names, labels, strict=False))
        else:
            return None


class RunSource(Protocol):
    def list_runs(self) -> list[GroupRun]: ...


class RunDirectoryScanner:
    def __init__(
        self,
        group_names: Sequence[str],
        group_separator: str,
        output_extension: str,
    ) -> None:
        if output_extension:
            self._label_parser = GroupLabelParser(group_names, group_separator)
            self._output_extension = output_extension
        else:
            raise ValueError("output extension must not be empty")

    def scan(self, input_dir: Path) -> list[GroupRun]:
        runs = (
            self._build_run(directory)
            for directory in self._list_directories(input_dir)
        )
        return [run for run in runs if run is not None]

    def _list_directories(self, input_dir: Path) -> list[Path]:
        try:
            return sorted(
                entry for entry in input_dir.iterdir() if entry.is_dir()
            )
        except OSError as error:
            raise InputError(
                f"cannot list input directory {input_dir}: {error}"
            ) from error

    def _build_run(self, directory: Path) -> GroupRun | None:
        key = self._label_parser.parse(directory.name)
        if key is not None:
            return GroupRun(
                key=key,
                directory=directory,
                sources=self._list_iteration_sources(directory),
            )
        else:
            LOGGER.warning(
                "skipping %s: name has fewer than %d '%s'-separated labels",
                directory,
                len(self._label_parser.group_names),
                self._label_parser.group_separator,
            )
            return None

    def _list_iteration_sources(
        self, directory: Path
    ) -> tuple[IterationSource, ...]:
        try:
            candidates = [
                self._parse_iteration_source(entry)
                for entry in directory.iterdir()
            ]
        except OSError as error:
            raise InputError(
                f"cannot list run directory {directory}: {error}"
            ) from error
        sources = [source for source in candidates if source is not None]
        return tuple(sorted(sources, key=lambda source: source.iteration))

    def _parse_iteration_source(self, entry: Path) -> IterationSource | None:
        iteration_label = entry.name.removesuffix(self._output_extension)
        is_iteration_file = (
            entry.name.endswith(self._output_extension)
            and iteration_label.isascii()
            and iteration_label.isdigit()
            and entry.is_file()
        )
        if is_iteration_file:
            return IterationSource(int(iteration_label), entry)
        else:
            LOGGER.debug("ignoring non-iteration entry %s", entry)
            return None


class DirectoryRunSource:
    def __init__(self, scanner: RunDirectoryScanner, input_dir: Path) -> None:
        self._scanner = scanner
        self._input_dir = input_dir

    def list_runs(self) -> list[GroupRun]:
        return self._scanner.scan(self._input_dir)


class StdinRunSource:
    def __init__(self, label_parser: GroupLabelParser, labels: str) -> None:
        self._label_parser = label_parser
        self._labels = labels

    def list_runs(self) -> list[GroupRun]:
        key = self._parse_stdin_key()
        LOGGER.info("reading one run with key %s from stdin", key)
        return [
            GroupRun(
                key=key,
                directory=STDIN_RUN_PATH,
                sources=(IterationSource(STDIN_ITERATION, STDIN_RUN_PATH),),
            )
        ]

    def _parse_stdin_key(self) -> GroupKey:
        expected_count = len(self._label_parser.group_names)
        if expected_count == 0:
            return ()
        else:
            key = self._label_parser.parse(self._labels)
            if key is not None and self._labels:
                return key
            else:
                raise InputError(
                    f"stdin input needs --stdin-labels with {expected_count} "
                    f"'{self._label_parser.group_separator}'-separated labels "
                    f"for groups {', '.join(self._label_parser.group_names)}"
                )
