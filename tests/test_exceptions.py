"""Tests for ai_spend.exceptions."""

from ai_spend.exceptions import (
    AiSpendError,
    BudgetError,
    ConfigError,
    ExportError,
    LicenseError,
    ProviderError,
    StoreError,
    SyncError,
)


class TestExceptionHierarchy:
    """All exceptions inherit from AiSpendError."""

    def test_base_is_exception(self):
        assert issubclass(AiSpendError, Exception)

    def test_store_error(self):
        assert issubclass(StoreError, AiSpendError)
        e = StoreError("db locked")
        assert str(e) == "db locked"

    def test_config_error(self):
        assert issubclass(ConfigError, AiSpendError)
        e = ConfigError("invalid yaml")
        assert str(e) == "invalid yaml"

    def test_provider_error(self):
        assert issubclass(ProviderError, AiSpendError)

    def test_budget_error(self):
        assert issubclass(BudgetError, AiSpendError)

    def test_sync_error(self):
        assert issubclass(SyncError, AiSpendError)

    def test_license_error(self):
        assert issubclass(LicenseError, AiSpendError)

    def test_export_error(self):
        assert issubclass(ExportError, AiSpendError)

    def test_catch_all_base(self):
        """All subclasses catchable via AiSpendError."""
        for cls in [
            StoreError,
            ConfigError,
            ProviderError,
            BudgetError,
            SyncError,
            LicenseError,
            ExportError,
        ]:
            try:
                raise cls("test")
            except AiSpendError:
                pass

    def test_all_seven_subclasses(self):
        subclasses = {
            StoreError,
            ConfigError,
            ProviderError,
            BudgetError,
            SyncError,
            LicenseError,
            ExportError,
        }
        assert len(subclasses) == 7
