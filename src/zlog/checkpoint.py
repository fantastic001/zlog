import hashlib
import json
import logging
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, Self

from zlog.domain import ExtractedValue
from zlog.extraction import CompiledPattern, SegmentValues, ValueExtractor
from zlog.options import CheckpointMode, MatchPolicy

LOGGER = logging.getLogger(__name__)

CHECKPOINT_FORMAT_VERSION = 2
TEMPORARY_SUFFIX = ".tmp"

SourceStamp = list[int]


def describe_separator(separator: re.Pattern[str] | None) -> str | None:
    match separator:
        case None:
            return None
        case re.Pattern():
            return separator.pattern


def is_stored_value(value: object) -> bool:
    match value:
        case str():
            return True
        case list():
            return all(isinstance(item, str) for item in value)
        case _:
            return False


def is_segment_list(segments: list[Any]) -> bool:
    return all(
        isinstance(segment, dict)
        and all(map(is_stored_value, segment.values()))
        for segment in segments
    )


def decode_stored_value(value: str | list[str]) -> ExtractedValue:
    match value:
        case str():
            return value
        case list():
            return tuple(value)


def encode_stored_value(value: ExtractedValue) -> str | list[str]:
    match value:
        case str():
            return value
        case tuple():
            return list(value)


def fingerprint_extraction(
    patterns: Sequence[CompiledPattern],
    separator: re.Pattern[str] | None,
    match_policy: MatchPolicy,
) -> str:
    description = {
        "patterns": [
            [pattern.regex.pattern, list(pattern.names)] for pattern in patterns
        ],
        "iteration_separator": describe_separator(separator),
        "match_policy": match_policy.value,
    }
    encoded = json.dumps(description, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CheckpointStore(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def lookup(self, source: Path) -> SegmentValues | None: ...

    def record(
        self, source: Path, segments: Sequence[Mapping[str, ExtractedValue]]
    ) -> None: ...


class NullCheckpointStore:
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        LOGGER.debug("checkpointing disabled; nothing to flush")

    def lookup(self, source: Path) -> SegmentValues | None:
        return None

    def record(
        self, source: Path, segments: Sequence[Mapping[str, ExtractedValue]]
    ) -> None:
        LOGGER.debug("checkpointing disabled; not recording %s", source)


class JsonCheckpointStore:
    def __init__(
        self,
        checkpoint_file: Path,
        fingerprint: str,
        mode: CheckpointMode,
        flush_interval: int,
    ) -> None:
        if flush_interval >= 1:
            self._checkpoint_file = checkpoint_file
            self._fingerprint = fingerprint
            self._mode = mode
            self._flush_interval = flush_interval
            self._entries: dict[str, Any] = {}
            self._pending_records = 0
        else:
            raise ValueError("flush_interval must be at least 1")

    def __enter__(self) -> Self:
        self._entries = self._load_entries()
        LOGGER.info(
            "using %d checkpoint entries from %s",
            len(self._entries),
            self._checkpoint_file,
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.flush()

    def lookup(self, source: Path) -> SegmentValues | None:
        current_stamp = self._stamp_source(source)
        match self._entries.get(self._entry_key(source)):
            case {
                "stamp": list() as recorded,
                "segments": list() as segments,
            } if (
                current_stamp is not None
                and recorded == current_stamp
                and is_segment_list(segments)
            ):
                return [
                    {
                        str(key): decode_stored_value(value)
                        for key, value in segment.items()
                    }
                    for segment in segments
                ]
            case _:
                return None

    def record(
        self, source: Path, segments: Sequence[Mapping[str, ExtractedValue]]
    ) -> None:
        stamp = self._stamp_source(source)
        if stamp is not None:
            self._entries[self._entry_key(source)] = {
                "stamp": stamp,
                "segments": [
                    {
                        name: encode_stored_value(value)
                        for name, value in segment.items()
                    }
                    for segment in segments
                ],
            }
            self._pending_records += 1
            self._flush_when_interval_reached()
        else:
            LOGGER.warning("cannot stat %s; not checkpointed", source)

    def flush(self) -> None:
        if self._pending_records > 0:
            self._write_entries()
        else:
            LOGGER.debug("no new checkpoint entries to flush")

    def _flush_when_interval_reached(self) -> None:
        if self._pending_records >= self._flush_interval:
            self.flush()
        else:
            LOGGER.debug("%d checkpoint records pending", self._pending_records)

    def _write_entries(self) -> None:
        document = {
            "version": CHECKPOINT_FORMAT_VERSION,
            "fingerprint": self._fingerprint,
            "entries": self._entries,
        }
        temporary_file = self._checkpoint_file.with_name(
            self._checkpoint_file.name + TEMPORARY_SUFFIX
        )
        try:
            self._checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
            temporary_file.write_text(json.dumps(document), encoding="utf-8")
            os.replace(temporary_file, self._checkpoint_file)
        except OSError as error:
            LOGGER.error(
                "cannot write checkpoint %s: %s", self._checkpoint_file, error
            )
        else:
            LOGGER.info(
                "wrote %d checkpoint entries to %s",
                len(self._entries),
                self._checkpoint_file,
            )
            self._pending_records = 0

    def _load_entries(self) -> dict[str, Any]:
        match self._mode:
            case CheckpointMode.RESTART:
                LOGGER.info("restart requested; ignoring existing checkpoint")
                return {}
            case CheckpointMode.RESUME:
                return self._read_matching_entries()

    def _read_matching_entries(self) -> dict[str, Any]:
        document = self._read_document()
        entries = document.get("entries")
        is_compatible = (
            document.get("version") == CHECKPOINT_FORMAT_VERSION
            and document.get("fingerprint") == self._fingerprint
            and isinstance(entries, dict)
        )
        if is_compatible and isinstance(entries, dict):
            return entries
        else:
            LOGGER.info(
                "checkpoint %s absent or stale; starting fresh",
                self._checkpoint_file,
            )
            return {}

    def _read_document(self) -> Mapping[str, Any]:
        try:
            text = self._checkpoint_file.read_text(encoding="utf-8")
            document = json.loads(text)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            LOGGER.error(
                "cannot read checkpoint %s: %s", self._checkpoint_file, error
            )
            return {}
        match document:
            case dict():
                return document
            case _:
                LOGGER.error(
                    "checkpoint %s is malformed", self._checkpoint_file
                )
                return {}

    @staticmethod
    def _entry_key(source: Path) -> str:
        return str(source.resolve())

    @staticmethod
    def _stamp_source(source: Path) -> SourceStamp | None:
        try:
            status = source.stat()
        except OSError:
            return None
        else:
            return [status.st_mtime_ns, status.st_size]


class CheckpointedExtractor:
    def __init__(self, inner: ValueExtractor, store: CheckpointStore) -> None:
        self._inner = inner
        self._store = store

    def extract(self, source: Path) -> SegmentValues:
        cached = self._store.lookup(source)
        if cached is None:
            segments = self._inner.extract(source)
            self._store.record(source, segments)
            return segments
        else:
            LOGGER.debug("checkpoint hit for %s", source)
            return cached
