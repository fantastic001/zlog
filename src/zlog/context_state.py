import logging
from collections.abc import Collection, Mapping
from types import MappingProxyType

from zlog.context_updates import ContextUpdate

LOGGER = logging.getLogger(__name__)


class ContextState:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def clear(self) -> None:
        self._values.clear()
        LOGGER.debug("context cleared")

    def reset(self, names: Collection[str]) -> None:
        for name in names:
            self._values.pop(name, None)

    def update(self, name: str, update: ContextUpdate, value: str) -> None:
        self._values[name] = update.apply(self._values.get(name), value)

    def snapshot(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self._values))
