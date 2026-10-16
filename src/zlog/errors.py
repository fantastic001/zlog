class ZlogError(Exception):
    pass


class ConfigurationError(ZlogError):
    pass


class SpecError(ZlogError):
    pass


class InputError(ZlogError):
    pass


class ExtractionError(ZlogError):
    pass
