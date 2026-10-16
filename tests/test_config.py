from dataclasses import fields
from pathlib import Path

import pytest

from zlog.config import (
    SETTING_PARSERS,
    Settings,
    SettingsLoader,
    is_known_encoding,
    parse_feature_state,
)
from zlog.errors import ConfigurationError
from zlog.options import FeatureState, MatchPolicy


def test_every_setting_has_a_parser() -> None:
    assert set(SETTING_PARSERS) == {field.name for field in fields(Settings)}


def test_defaults_without_any_source() -> None:
    assert SettingsLoader().load({}, None, {}) == Settings()


def test_layers_override_in_order(tmp_path: Path) -> None:
    config_file = tmp_path / "zlog.toml"
    config_file.write_text(
        "[zlog]\nsignificance_level = 0.01\noutput_format = 'csv'\n"
        "plugins = false\nmatch_policy = 'first'\n"
    )
    environ = {"ZLOG_OUTPUT_FORMAT": "json", "UNRELATED": "x"}

    settings = SettingsLoader().load(
        environ, config_file, {"log_level": "debug"}
    )

    assert settings.significance_level == 0.01
    assert settings.output_format == "json"
    assert settings.log_level == "DEBUG"
    assert settings.plugins is FeatureState.DISABLED
    assert settings.match_policy is MatchPolicy.FIRST


def test_config_file_without_section_uses_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / "zlog.toml"
    config_file.write_text("[other]\nkey = 1\n")

    assert SettingsLoader().load({}, config_file, {}) == Settings()


@pytest.mark.parametrize(
    "content", ["zlog = 3\n", "[zlog\nbroken", "[zlog]\nunknown_key = 1\n"]
)
def test_invalid_config_file_is_rejected(tmp_path: Path, content: str) -> None:
    config_file = tmp_path / "zlog.toml"
    config_file.write_text(content)

    with pytest.raises(ConfigurationError):
        SettingsLoader().load({}, config_file, {})


def test_missing_config_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="cannot read"):
        SettingsLoader().load({}, tmp_path / "absent.toml", {})


def test_non_path_config_file_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="must be a path"):
        SettingsLoader().read_config_file("zlog.toml")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("ZLOG_SIGNIFICANCE_LEVEL", "abc"),
        ("ZLOG_SIGNIFICANCE_LEVEL", "1.5"),
        ("ZLOG_SIGNIFICANCE_LEVEL", "nan"),
        ("ZLOG_MINIMUM_SAMPLE_SIZE", "0"),
        ("ZLOG_GROUP_SEPARATOR", ""),
        ("ZLOG_FILE_ENCODING", "no-such-codec"),
        ("ZLOG_LOG_LEVEL", "chatty"),
        ("ZLOG_MATCH_POLICY", "middle"),
        ("ZLOG_PLUGINS", "maybe"),
        ("ZLOG_CHECKPOINT_INTERVAL", "0"),
    ],
)
def test_invalid_environment_values_are_rejected(
    variable: str, value: str
) -> None:
    with pytest.raises(ConfigurationError):
        SettingsLoader().load({variable: value}, None, {})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("on", FeatureState.ENABLED),
        (" TRUE ", FeatureState.ENABLED),
        ("0", FeatureState.DISABLED),
        ("disabled", FeatureState.DISABLED),
    ],
)
def test_parse_feature_state(raw: str, expected: FeatureState) -> None:
    assert parse_feature_state(raw) is expected


def test_is_known_encoding() -> None:
    assert is_known_encoding("latin-1")
    assert not is_known_encoding("klingon")
