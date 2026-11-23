from importlib.metadata import EntryPoint

import pytest

from zlog.config import Settings
from zlog.context_updates import ReplaceUpdate
from zlog.errors import ConfigurationError
from zlog.pattern_aliases import BUILTIN_PATTERN_ALIASES
from zlog.plugins import (
    EntryPointPluginLoader,
    PluginRegistry,
    is_valid_context_prefix,
)
from zlog.writers import BUILTIN_OUTPUT_FORMATS

MODULE = "tests.test_plugins"


class MaximumUpdate:
    def apply(self, previous: str | None, value: str) -> str:
        return max(previous or value, value, key=float)


def register_sample_plugin(registry: PluginRegistry) -> None:
    registry.register_output_format(" TSV ", BUILTIN_OUTPUT_FORMATS["csv"])
    registry.register_context_update("^", lambda settings: MaximumUpdate())
    registry.register_hook("hook")
    registry.register_pattern_alias("ts", r"\d+:\d+")


def broken_plugin(registry: PluginRegistry) -> None:
    raise RuntimeError("plugin is broken")


def make_entry_point(name: str, attribute: str) -> EntryPoint:
    return EntryPoint(name, f"{MODULE}:{attribute}", "zlog.plugins")


def test_loader_registers_plugins_and_survives_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry_points = [
        make_entry_point("sample", "register_sample_plugin"),
        make_entry_point("broken", "broken_plugin"),
        make_entry_point("missing", "no_such_attribute"),
    ]
    registry = PluginRegistry()

    loaded = EntryPointPluginLoader(lambda: entry_points).load_into(registry)

    assert loaded == ("sample",)
    assert registry.find_output_format("tsv") is BUILTIN_OUTPUT_FORMATS["csv"]
    assert set(registry.context_updates) == {"", "+", "@", "^"}
    update = registry.context_updates["^"](Settings())
    assert update.apply("3", "2") == "3"
    assert registry.hooks == ("hook",)
    assert dict(registry.pattern_aliases) == {
        **BUILTIN_PATTERN_ALIASES,
        "ts": r"\d+:\d+",
    }
    assert "plugin is broken" in caplog.text


def test_default_loader_discovers_installed_plugins() -> None:
    assert EntryPointPluginLoader().load_into(PluginRegistry()) == ()


def test_unknown_output_format_lists_available() -> None:
    with pytest.raises(ConfigurationError, match="csv, json, jsonl"):
        PluginRegistry().find_output_format("xml")


@pytest.mark.parametrize(
    "prefix", ["", "a", "_", ".", "=", ":", " ", "^1", "(", "<)"]
)
def test_invalid_context_prefixes_are_rejected(prefix: str) -> None:
    assert not is_valid_context_prefix(prefix)
    with pytest.raises(ValueError, match="context update prefix"):
        PluginRegistry().register_context_update(
            prefix, lambda settings: ReplaceUpdate()
        )


def test_registry_rejects_empty_names() -> None:
    registry = PluginRegistry()

    with pytest.raises(ValueError, match="output format"):
        registry.register_output_format(" ", BUILTIN_OUTPUT_FORMATS["csv"])
    with pytest.raises(ValueError, match="pattern alias name"):
        registry.register_pattern_alias("", "x")
    with pytest.raises(ValueError, match="capturing groups"):
        registry.register_pattern_alias("pair", "(a)")
    assert dict(registry.pattern_aliases) == BUILTIN_PATTERN_ALIASES
