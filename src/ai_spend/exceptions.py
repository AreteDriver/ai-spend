"""Exception hierarchy for ai-spend."""


class AiSpendError(Exception):
    """Base exception for all ai-spend errors."""


class StoreError(AiSpendError):
    """Database/storage operation failed."""


class ConfigError(AiSpendError):
    """Configuration file read/write/validation failed."""


class ProviderError(AiSpendError):
    """Provider API communication failed."""


class BudgetError(AiSpendError):
    """Budget operation failed."""


class SyncError(AiSpendError):
    """Data sync operation failed."""


class LicenseError(AiSpendError):
    """License validation failed."""


class ExportError(AiSpendError):
    """Data export operation failed."""
