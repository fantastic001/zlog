import logging
from collections.abc import Sequence
from pathlib import Path

from zlog.domain import GroupKey, GroupRun, IterationSource
from zlog.errors import InputError

LOGGER = logging.getLogger(__name__)


class RunDirectoryScanner:
    def __init__(
        self,
        group_names: Sequence[str],
        group_separator: str,
        output_extension: str,
    ) -> None:
        if group_separator and output_extension:
            self._group_names = tuple(group_names)
            self._group_separator = group_separator
            self._output_extension = output_extension
        else:
            raise ValueError("separator and extension must not be empty")

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
        key = self._parse_group_key(directory.name)
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
                len(self._group_names),
                self._group_separator,
            )
            return None

    def _parse_group_key(self, directory_name: str) -> GroupKey | None:
        labels = directory_name.split(self._group_separator)
        if len(labels) >= len(self._group_names):
            return tuple(zip(self._group_names, labels, strict=False))
        else:
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
