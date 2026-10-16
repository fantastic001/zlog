import codecs
import logging
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from zlog.errors import ConfigurationError
from zlog.options import FeatureState, MatchPolicy

LOGGER = logging.getLogger(__name__)

ENVIRONMENT_PREFIX = "ZLOG_"
CONFIG_FILE_SECTION = "zlog"
DEFAULT_MAX_INPUT_FILE_BYTES = 256 * 1024 * 1024

ENABLED_WORDS = frozenset({"1", "true", "yes", "on", "enabled"})
DISABLED_WORDS = frozenset({"0", "false", "no", "off", "disabled"})


@dataclass(frozen=True)
class Settings:
    significance_level: float = 0.05
    minimum_sample_size: int = 2
    std_ddof: int = 0
    group_separator: str = "-"
    output_extension: str = ".out"
    file_encoding: str = "utf-8"
    max_input_file_bytes: int = DEFAULT_MAX_INPUT_FILE_BYTES
    match_policy: MatchPolicy = MatchPolicy.LAST
    output_format: str = "markdown"
    log_level: str = "WARNING"
    plugins: FeatureState = FeatureState.ENABLED
    checkpoint_file: str = ""
    checkpoint_interval: int = 100


def parse_feature_state(raw: str) -> FeatureState:
    normalized = raw.strip().lower()
    if normalized in ENABLED_WORDS:
        return FeatureState.ENABLED
    elif normalized in DISABLED_WORDS:
        return FeatureState.DISABLED
    else:
        raise ValueError(f"not a feature state: {raw!r}")


def is_known_encoding(name: str) -> bool:
    try:
        codecs.lookup(name)
    except LookupError:
        return False
    else:
        return True


SettingParser = Callable[[str], Any]
SettingValidator = Callable[[Any], bool]

SETTING_PARSERS: Mapping[str, SettingParser] = MappingProxyType(
    {
        "significance_level": float,
        "minimum_sample_size": int,
        "std_ddof": int,
        "group_separator": str,
        "output_extension": str,
        "file_encoding": str,
        "max_input_file_bytes": int,
        "match_policy": lambda raw: MatchPolicy(raw.strip().lower()),
        "output_format": lambda raw: raw.strip().lower(),
        "log_level": lambda raw: raw.strip().upper(),
        "plugins": parse_feature_state,
        "checkpoint_file": str,
        "checkpoint_interval": int,
    }
)

SETTING_VALIDATORS: Mapping[str, tuple[SettingValidator, str]] = (
    MappingProxyType(
        {
            "significance_level": (
                lambda value: 0.0 < value < 1.0,
                "must lie strictly between 0 and 1",
            ),
            "minimum_sample_size": (
                lambda value: value >= 1,
                "must be at least 1",
            ),
            "std_ddof": (lambda value: value >= 0, "must not be negative"),
            "group_separator": (
                lambda value: len(value) > 0,
                "must not be empty",
            ),
            "output_extension": (
                lambda value: len(value) > 0,
                "must not be empty",
            ),
            "file_encoding": (is_known_encoding, "must name a known codec"),
            "max_input_file_bytes": (
                lambda value: value > 0,
                "must be positive",
            ),
            "output_format": (
                lambda value: len(value) > 0,
                "must not be empty",
            ),
            "log_level": (
                lambda value: value in logging.getLevelNamesMapping(),
                "must be a logging level name",
            ),
            "checkpoint_interval": (
                lambda value: value >= 1,
                "must be at least 1",
            ),
        }
    )
)


class SettingsLoader:
    def __init__(
        self,
        parsers: Mapping[str, SettingParser] = SETTING_PARSERS,
        validators: Mapping[
            str, tuple[SettingValidator, str]
        ] = SETTING_VALIDATORS,
        environment_prefix: str = ENVIRONMENT_PREFIX,
    ) -> None:
        self._parsers = parsers
        self._validators = validators
        self._environment_prefix = environment_prefix

    def load(
        self,
        environ: Mapping[str, str],
        config_file: Path | None,
        cli_overrides: Mapping[str, object],
    ) -> Settings:
        layers = (
            self.read_config_file(config_file),
            self.read_environment(environ),
            cli_overrides,
        )
        settings = Settings()
        for layer in layers:
            settings = self.apply_overrides(settings, layer)
        self.validate(settings)
        return settings

    def read_config_file(
        self, config_file: Path | None
    ) -> Mapping[str, object]:
        match config_file:
            case None:
                return {}
            case Path():
                return self._read_toml_section(config_file)
            case _:
                raise ConfigurationError(
                    f"config file must be a path, got {config_file!r}"
                )

    def read_environment(self, environ: Mapping[str, str]) -> dict[str, str]:
        variable_names = {
            name: f"{self._environment_prefix}{name.upper()}"
            for name in self._parsers
        }
        return {
            name: environ[variable]
            for name, variable in variable_names.items()
            if variable in environ
        }

    def apply_overrides(
        self, settings: Settings, overrides: Mapping[str, object]
    ) -> Settings:
        unknown_names = sorted(set(overrides) - set(self._parsers))
        if not unknown_names:
            parsed = {
                name: self._parse_setting_value(name, raw_value)
                for name, raw_value in overrides.items()
            }
            return replace(settings, **parsed)
        else:
            raise ConfigurationError(
                f"unknown settings: {', '.join(unknown_names)}"
            )

    def validate(self, settings: Settings) -> None:
        violations = [
            f"{name} {message}"
            for name, (is_valid, message) in self._validators.items()
            if not is_valid(getattr(settings, name))
        ]
        if not violations:
            LOGGER.debug("validated settings: %s", settings)
        else:
            raise ConfigurationError("; ".join(violations))

    def _parse_setting_value(self, name: str, raw_value: object) -> Any:
        try:
            return self._parsers[name](str(raw_value))
        except ValueError as error:
            raise ConfigurationError(
                f"invalid value {raw_value!r} for setting {name!r}: {error}"
            ) from error

    def _read_toml_section(self, config_file: Path) -> Mapping[str, object]:
        try:
            with config_file.open("rb") as handle:
                document = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ConfigurationError(
                f"cannot read config file {config_file}: {error}"
            ) from error
        match document.get(CONFIG_FILE_SECTION, {}):
            case dict() as section:
                return section
            case _:
                raise ConfigurationError(
                    f"[{CONFIG_FILE_SECTION}] in {config_file} must be a table"
                )
