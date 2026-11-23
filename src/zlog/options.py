from enum import Enum


class FeatureState(Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class FormulaEscaping(Enum):
    OFF = "off"
    QUOTE = "quote"
    TAB = "tab"


class ResetScope(Enum):
    NONE = "none"
    ALL = "all"
    LISTED = "listed"


class BindingSection(Enum):
    CONTEXT = "context"
    RECORD = "record"
