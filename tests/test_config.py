from dataclasses import fields
from pathlib import Path
from typing import cast

import pytest

from tests.conftest import EXAMPLES_DIRECTORY
from zlog.config import (
    SETTING_PARSERS,
    Settings,
    SettingsLoader,
    is_known_encoding,
    is_known_error_handler,
    is_valid_csv_delimiter,
    parse_feature_state,
)
from zlog.errors import ConfigurationError
from zlog.options import FeatureState, FormulaEscaping


def test_every_setting_has_a_parser() -> None:
    assert set(SETTING_PARSERS) == {field.name for field in fields(Settings)}


def test_defaults_without_any_source() -> None:
    assert SettingsLoader().load({}, None, {}) == Settings()


def test_layers_override_in_order(tmp_path: Path) -> None:
    config_file = tmp_path / "zlog.toml"
    config_file.write_text(
        "[zlog]\nconcat_separator = '|'\noutput_format = 'json'\n"
        "plugins = false\ndecimal_precision = 20\n"
    )
    environ = {
        "ZLOG_OUTPUT_FORMAT": "JSONL",
        "ZLOG_FORMULA_ESCAPING": "Tab",
        "UNRELATED": "x",
    }

    settings = SettingsLoader().load(
        environ, config_file, {"log_level": "debug", "csv_delimiter": ";"}
    )

    assert settings.concat_separator == "|"
    assert settings.output_format == "jsonl"
    assert settings.formula_escaping is FormulaEscaping.TAB
    assert settings.log_level == "DEBUG"
    assert settings.csv_delimiter == ";"
    assert settings.decimal_precision == 20
    assert settings.plugins is FeatureState.DISABLED


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
        SettingsLoader().read_config_file(cast("Path", "zlog.toml"))


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("ZLOG_FILE_ENCODING", "no-such-codec"),
        ("ZLOG_OUTPUT_ENCODING", "no-such-codec"),
        ("ZLOG_DECODE_ERRORS", "shrug"),
        ("ZLOG_MAX_LINE_LENGTH", "0"),
        ("ZLOG_MAX_LINE_LENGTH", "many"),
        ("ZLOG_OUTPUT_FORMAT", " "),
        ("ZLOG_CSV_DELIMITER", ",,"),
        ("ZLOG_CSV_DELIMITER", '"'),
        ("ZLOG_DECIMAL_PRECISION", "0"),
        ("ZLOG_DECIMAL_PRECISION", "10001"),
        ("ZLOG_FORMULA_ESCAPING", "sometimes"),
        ("ZLOG_PATH_COLUMN", "1path"),
        ("ZLOG_STDIN_PATH", ""),
        ("ZLOG_LOG_LEVEL", "chatty"),
        ("ZLOG_PLUGINS", "maybe"),
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


def test_codec_and_delimiter_checks() -> None:
    assert is_known_encoding("latin-1")
    assert not is_known_encoding("klingon")
    assert is_known_error_handler("backslashreplace")
    assert not is_known_error_handler("ignore-politely")
    assert is_valid_csv_delimiter("\t")
    assert not is_valid_csv_delimiter("\n")


def test_example_config_lists_every_default() -> None:
    example = EXAMPLES_DIRECTORY / "zlog.toml"

    assert SettingsLoader().read_config_file(example).keys() == set(
        SETTING_PARSERS
    )
    assert SettingsLoader().load({}, example, {}) == Settings()
