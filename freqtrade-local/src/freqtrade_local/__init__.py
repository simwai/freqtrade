"""freqtrade-local overlay package."""

from freqtrade_local.patches import apply_config_schema_patch  # noqa: F401
from freqtrade_local.plugins import __all__  # noqa: F401

__version__ = "0.1.0"

# Apply config schema patch at import time so overlay-specific keys
# are accepted before freqtrade validates user configuration.
apply_config_schema_patch()
