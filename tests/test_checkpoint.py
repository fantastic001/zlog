import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from zlog.checkpoint import (
    CHECKPOINT_FORMAT_VERSION,
    CheckpointedExtractor,
    JsonCheckpointStore,
    NullCheckpointStore,
    fingerprint_extraction,
)
from zlog.extraction import CompiledPattern
from zlog.options import CheckpointMode, MatchPolicy

FINGERPRINT = "fingerprint"


class CountingExtractor:
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, source: Path) -> list[dict[str, str]]:
        self.calls += 1
        return [{"value": source.read_text()}]


def open_store(
    checkpoint_file: Path,
    mode: CheckpointMode = CheckpointMode.RESUME,
    fingerprint: str = FINGERPRINT,
    flush_interval: int = 100,
) -> JsonCheckpointStore:
    return JsonCheckpointStore(
        checkpoint_file, fingerprint, mode, flush_interval
    )


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "0.out"
    path.write_text("1.5")
    return path


def test_resume_reuses_unchanged_files(tmp_path: Path, source: Path) -> None:
    checkpoint_file = tmp_path / "checkpoint.json"
    first_run, second_run = CountingExtractor(), CountingExtractor()

    with open_store(checkpoint_file) as store:
        CheckpointedExtractor(first_run, store).extract(source)
    with open_store(checkpoint_file) as store:
        values = CheckpointedExtractor(second_run, store).extract(source)

    assert values == [{"value": "1.5"}]
    assert (first_run.calls, second_run.calls) == (1, 0)


def test_modified_file_is_re_extracted(tmp_path: Path, source: Path) -> None:
    checkpoint_file = tmp_path / "checkpoint.json"
    with open_store(checkpoint_file) as store:
        CheckpointedExtractor(CountingExtractor(), store).extract(source)
    source.write_text("22.5")
    extractor = CountingExtractor()

    with open_store(checkpoint_file) as store:
        values = CheckpointedExtractor(extractor, store).extract(source)

    assert values == [{"value": "22.5"}]
    assert extractor.calls == 1


@pytest.mark.parametrize(
    ("mode", "fingerprint"),
    [
        (CheckpointMode.RESTART, FINGERPRINT),
        (CheckpointMode.RESUME, "other"),
    ],
)
def test_restart_or_changed_fingerprint_ignores_checkpoint(
    tmp_path: Path, source: Path, mode: CheckpointMode, fingerprint: str
) -> None:
    checkpoint_file = tmp_path / "checkpoint.json"
    with open_store(checkpoint_file) as store:
        store.record(source, [{"value": "cached"}])

    with open_store(checkpoint_file, mode, fingerprint) as store:
        assert store.lookup(source) is None


def test_flushes_periodically(tmp_path: Path, source: Path) -> None:
    checkpoint_file = tmp_path / "checkpoint.json"
    store = open_store(checkpoint_file, flush_interval=1).__enter__()

    store.record(source, [{"value": "1.5"}])

    document = json.loads(checkpoint_file.read_text())
    assert document["version"] == CHECKPOINT_FORMAT_VERSION
    assert document["fingerprint"] == FINGERPRINT
    assert len(document["entries"]) == 1


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[1, 2]",
        '{"version": 2, "entries": []}',
        '{"version": 1, "fingerprint": "fingerprint", "entries": {}}',
    ],
)
def test_corrupt_checkpoint_starts_fresh(
    tmp_path: Path, source: Path, content: str
) -> None:
    checkpoint_file = tmp_path / "checkpoint.json"
    checkpoint_file.write_text(content)

    with open_store(checkpoint_file) as store:
        assert store.lookup(source) is None


@pytest.mark.parametrize(
    "build_entry",
    [
        lambda stamp: {"stamp": "bad"},
        lambda stamp: {"stamp": stamp, "segments": ["not a mapping"]},
        lambda stamp: {"stamp": stamp, "values": {"value": "1"}},
    ],
)
def test_malformed_entry_is_a_miss(
    tmp_path: Path, source: Path, build_entry: Callable[[list[int]], object]
) -> None:
    checkpoint_file = tmp_path / "checkpoint.json"
    status = source.stat()
    entry = build_entry([status.st_mtime_ns, status.st_size])
    checkpoint_file.write_text(
        json.dumps(
            {
                "version": CHECKPOINT_FORMAT_VERSION,
                "fingerprint": FINGERPRINT,
                "entries": {str(source.resolve()): entry},
            }
        )
    )

    with open_store(checkpoint_file) as store:
        assert store.lookup(source) is None


def test_unreadable_checkpoint_starts_fresh(
    tmp_path: Path, source: Path, caplog: pytest.LogCaptureFixture
) -> None:
    checkpoint_directory = tmp_path / "checkpoint.json"
    checkpoint_directory.mkdir()

    with open_store(checkpoint_directory) as store:
        assert store.lookup(source) is None
        store.record(source, [{"value": "1"}])

    assert "cannot write checkpoint" in caplog.text


def test_record_of_missing_source_is_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with open_store(tmp_path / "checkpoint.json") as store:
        store.record(tmp_path / "missing.out", [{"value": "1"}])

    assert "not checkpointed" in caplog.text
    assert not (tmp_path / "checkpoint.json").exists()


def test_rejects_invalid_flush_interval(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        open_store(tmp_path / "checkpoint.json", flush_interval=0)


def test_null_store_never_caches(source: Path) -> None:
    extractor = CountingExtractor()

    with NullCheckpointStore() as store:
        checkpointed = CheckpointedExtractor(extractor, store)
        checkpointed.extract(source)
        checkpointed.extract(source)

    assert extractor.calls == 2


def test_fingerprint_depends_on_patterns_separator_and_policy() -> None:
    patterns = (CompiledPattern(re.compile("(a)"), ("a",)),)
    other_patterns = (CompiledPattern(re.compile("(b)"), ("a",)),)
    separator = re.compile("^---$")

    baseline = fingerprint_extraction(patterns, None, MatchPolicy.LAST)

    assert baseline == fingerprint_extraction(patterns, None, MatchPolicy.LAST)
    assert baseline != fingerprint_extraction(patterns, None, MatchPolicy.FIRST)
    assert baseline != fingerprint_extraction(
        other_patterns, None, MatchPolicy.LAST
    )
    assert baseline != fingerprint_extraction(
        patterns, separator, MatchPolicy.LAST
    )
