import logging
import re
from collections.abc import Callable, Iterable, Mapping
from importlib.metadata import EntryPoint, entry_points
from types import MappingProxyType

from zlog.context_updates import BUILTIN_CONTEXT_UPDATES, ContextUpdateFactory
from zlog.errors import ConfigurationError, SpecError
from zlog.pattern_aliases import (
    BUILTIN_PATTERN_ALIASES,
    validate_pattern_alias,
)
from zlog.writers import BUILTIN_OUTPUT_FORMATS, RowWriterFactory

LOGGER = logging.getLogger(__name__)

PLUGIN_ENTRY_POINT_GROUP = "zlog.plugins"
FORBIDDEN_PREFIX_CHARACTERS = re.compile(r"[A-Za-z0-9_.:=()\s]")

EntryPointProvider = Callable[[], Iterable[EntryPoint]]


def is_valid_context_prefix(prefix: str) -> bool:
    return bool(prefix) and FORBIDDEN_PREFIX_CHARACTERS.search(prefix) is None


class PluginRegistry:
    def __init__(
        self,
        output_formats: Mapping[str, RowWriterFactory] = BUILTIN_OUTPUT_FORMATS,
        context_updates: Mapping[
            str, ContextUpdateFactory
        ] = BUILTIN_CONTEXT_UPDATES,
        pattern_aliases: Mapping[str, str] = BUILTIN_PATTERN_ALIASES,
    ) -> None:
        self._output_formats = dict(output_formats)
        self._context_updates = dict(context_updates)
        self._hooks: list[object] = []
        self._pattern_aliases = dict(pattern_aliases)

    def register_output_format(
        self, name: str, factory: RowWriterFactory
    ) -> None:
        normalized_name = name.strip().lower()
        if normalized_name:
            self._output_formats[normalized_name] = factory
            LOGGER.info("registered output format %r", normalized_name)
        else:
            raise ValueError("output format name must not be empty")

    def register_context_update(
        self, prefix: str, factory: ContextUpdateFactory
    ) -> None:
        if is_valid_context_prefix(prefix):
            self._context_updates[prefix] = factory
            LOGGER.info("registered context update prefix %r", prefix)
        else:
            raise ValueError(
                f"context update prefix {prefix!r} must be non-empty and "
                f"must not contain {FORBIDDEN_PREFIX_CHARACTERS.pattern}"
            )

    def register_hook(self, hook: object) -> None:
        self._hooks.append(hook)
        LOGGER.info("registered hook %r", hook)

    def register_pattern_alias(self, name: str, regex: str) -> None:
        try:
            validate_pattern_alias(name, regex)
        except SpecError as error:
            raise ValueError(str(error)) from error
        else:
            self._pattern_aliases[name] = regex
            LOGGER.info("registered pattern alias %r", name)

    def find_output_format(self, name: str) -> RowWriterFactory:
        try:
            return self._output_formats[name]
        except KeyError as error:
            available = ", ".join(sorted(self._output_formats))
            raise ConfigurationError(
                f"unknown output format {name!r}; available: {available}"
            ) from error

    @property
    def context_updates(self) -> Mapping[str, ContextUpdateFactory]:
        return MappingProxyType(dict(self._context_updates))

    @property
    def hooks(self) -> tuple[object, ...]:
        return tuple(self._hooks)

    @property
    def pattern_aliases(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self._pattern_aliases))


class EntryPointPluginLoader:
    def __init__(
        self,
        provider: EntryPointProvider = lambda: entry_points(
            group=PLUGIN_ENTRY_POINT_GROUP
        ),
    ) -> None:
        self._provider = provider

    def load_into(self, registry: PluginRegistry) -> tuple[str, ...]:
        loaded = (
            self._load_plugin(entry_point, registry)
            for entry_point in self._provider()
        )
        return tuple(name for name in loaded if name is not None)

    @staticmethod
    def _load_plugin(
        entry_point: EntryPoint, registry: PluginRegistry
    ) -> str | None:
        try:
            register = entry_point.load()
            register(registry)
        except Exception:
            LOGGER.exception("failed to load plugin %r", entry_point.name)
            return None
        else:
            LOGGER.info("loaded plugin %r", entry_point.name)
            return entry_point.name
