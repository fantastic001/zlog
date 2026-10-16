from enum import Enum


class MatchPolicy(Enum):
    FIRST = "first"
    LAST = "last"


class ComparisonFilter(Enum):
    ALL = "all"
    SAME_DISTRIBUTION_ONLY = "same-distribution-only"


class FeatureState(Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class CheckpointMode(Enum):
    RESUME = "resume"
    RESTART = "restart"


class Verbosity(Enum):
    QUIET = "quiet"
    VERBOSE = "verbose"
