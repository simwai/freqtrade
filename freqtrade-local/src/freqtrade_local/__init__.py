"""freqtrade-local overlay package."""

# Python 3.10 compatibility: backport StrEnum from strenum
try:
    from enum import StrEnum
except ImportError:
    from strenum import StrEnum
    import enum
    enum.StrEnum = StrEnum

# Python 3.10 compatibility: backport UTC from datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

# Lazy plugin imports - only import when freqtrade loads this package
# This avoids Python 3.11+ dependency issues when running standalone commands
def _load_plugins():
    """Load plugins when explicitly requested (e.g., by freqtrade CLI)."""
    from freqtrade_local.plugins import __all__  # noqa: F401

# Apply config schema patch at import time so overlay-specific keys
# are accepted before freqtrade validates user configuration.
from freqtrade_local.patches import apply_config_schema_patch  # noqa: F401
apply_config_schema_patch()

__version__ = "0.1.0"
