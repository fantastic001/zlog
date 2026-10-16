import logging
from collections.abc import Callable, Iterable, Mapping
from importlib.metadata import EntryPoint, entry_points
from types import MappingProxyType

from zlog.errors import ConfigurationError
from zlog.list_statistics import LIST_STATISTICS, ListStatistic
from zlog.renderers import BUILTIN_OUTPUT_FORMATS, OutputFormatPlugin

LOGGER = logging.getLogger(__name__)

PLUGIN_ENTRY_POINT_GROUP = "zlog.plugins"

EntryPointProvider = Callable[[], Iterable[EntryPoint]]


class PluginRegistry:
    def __init__(
        self,
        output_formats: Mapping[
            str, OutputFormatPlugin
        ] = BUILTIN_OUTPUT_FORMATS,
    ) -> None:
        self._output_formats = dict(output_formats)
        self._hooks: list[object] = []
        self._regex_macros: dict[str, str] = {}
        self._list_statistics: dict[str, ListStatistic] = dict(LIST_STATISTICS)

    def register_output_format(
        self, name: str, plugin: OutputFormatPlugin
    ) -> None:
        normalized_name = name.strip().lower()
        if normalized_name:
            self._output_formats[normalized_name] = plugin
            LOGGER.info("registered output format %r", normalized_name)
        else:
            raise ValueError("output format name must not be empty")

    def register_hook(self, hook: object) -> None:
        self._hooks.append(hook)
        LOGGER.info("registered hook %r", hook)

    def register_regex_macro(self, macro: str, replacement: str) -> None:
        if macro:
            self._regex_macros[macro] = replacement
            LOGGER.info("registered regex macro %r", macro)
        else:
            raise ValueError("regex macro must not be empty")

    def register_list_statistic(
        self, name: str, statistic: ListStatistic
    ) -> None:
        if name:
            self._list_statistics[name] = statistic
            LOGGER.info("registered list statistic %r", name)
        else:
            raise ValueError("list statistic name must not be empty")

    def find_output_format(self, name: str) -> OutputFormatPlugin:
        try:
            return self._output_formats[name]
        except KeyError as error:
            available = ", ".join(sorted(self._output_formats))
            raise ConfigurationError(
                f"unknown output format {name!r}; available: {available}"
            ) from error

    @property
    def hooks(self) -> tuple[object, ...]:
        return tuple(self._hooks)

    @property
    def regex_macros(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self._regex_macros))

    @property
    def list_statistics(self) -> Mapping[str, ListStatistic]:
        return MappingProxyType(dict(self._list_statistics))


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
