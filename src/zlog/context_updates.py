import logging
from collections.abc import Callable, Mapping
from decimal import (
    Context,
    Decimal,
    DecimalException,
    Inexact,
    InvalidOperation,
    Overflow,
)
from types import MappingProxyType
from typing import Protocol

from zlog.config import Settings
from zlog.errors import InvalidValueError
from zlog.variable_names import REPLACE_PREFIX

LOGGER = logging.getLogger(__name__)

ADD_PREFIX = "+"
CONCATENATE_PREFIX = "@"
DECIMAL_OUTPUT_FORMAT = "f"
TRAPPED_DECIMAL_SIGNALS = (Inexact, InvalidOperation, Overflow)


class ContextUpdate(Protocol):
    def apply(self, previous: str | None, value: str) -> str: ...


class ReplaceUpdate:
    def apply(self, previous: str | None, value: str) -> str:
        return value


class ConcatenateUpdate:
    def __init__(self, separator: str) -> None:
        self._separator = separator

    def apply(self, previous: str | None, value: str) -> str:
        match previous:
            case None:
                return value
            case str():
                return f"{previous}{self._separator}{value}"


class NumericAddUpdate:
    def __init__(self, precision: int) -> None:
        if precision > 0:
            self._context = Context(
                prec=precision, traps=list(TRAPPED_DECIMAL_SIGNALS)
            )
        else:
            raise ValueError("decimal precision must be positive")

    def apply(self, previous: str | None, value: str) -> str:
        try:
            total = self._context.add(
                self._parse_number(previous), self._parse_number(value)
            )
        except DecimalException as error:
            raise InvalidValueError(
                f"cannot add {value!r} to {previous!r}: "
                f"{type(error).__name__} at precision {self._context.prec}"
            ) from error
        else:
            return format(total, DECIMAL_OUTPUT_FORMAT)

    def _parse_number(self, text: str | None) -> Decimal:
        match text:
            case None:
                return Decimal(0)
            case str():
                return self._context.create_decimal(text)


ContextUpdateFactory = Callable[[Settings], ContextUpdate]

BUILTIN_CONTEXT_UPDATES: Mapping[str, ContextUpdateFactory] = MappingProxyType(
    {
        REPLACE_PREFIX: lambda settings: ReplaceUpdate(),
        ADD_PREFIX: lambda settings: NumericAddUpdate(
            settings.decimal_precision
        ),
        CONCATENATE_PREFIX: lambda settings: ConcatenateUpdate(
            settings.concat_separator
        ),
    }
)


def build_context_updates(
    factories: Mapping[str, ContextUpdateFactory], settings: Settings
) -> Mapping[str, ContextUpdate]:
    updates = {prefix: create(settings) for prefix, create in factories.items()}
    LOGGER.debug("context update prefixes: %s", sorted(updates))
    return MappingProxyType(updates)
