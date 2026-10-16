from importlib.metadata import EntryPoint

import pytest

from zlog.errors import ConfigurationError
from zlog.plugins import EntryPointPluginLoader, PluginRegistry
from zlog.renderers import BUILTIN_OUTPUT_FORMATS

MODULE = "tests.test_plugins"


def register_sample_plugin(registry: PluginRegistry) -> None:
    registry.register_output_format(" TSV ", BUILTIN_OUTPUT_FORMATS["csv"])
    registry.register_hook("hook")
    registry.register_regex_macro(r"\i", r"\d+")


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
    assert registry.hooks == ("hook",)
    assert dict(registry.regex_macros) == {r"\i": r"\d+"}
    assert "plugin is broken" in caplog.text


def test_default_loader_discovers_installed_plugins() -> None:
    assert EntryPointPluginLoader().load_into(PluginRegistry()) == ()


def test_unknown_output_format_lists_available() -> None:
    with pytest.raises(ConfigurationError, match="csv, json, markdown"):
        PluginRegistry().find_output_format("xml")


def test_registry_rejects_empty_names() -> None:
    registry = PluginRegistry()

    with pytest.raises(ValueError):
        registry.register_output_format(" ", BUILTIN_OUTPUT_FORMATS["csv"])
    with pytest.raises(ValueError):
        registry.register_regex_macro("", "x")
