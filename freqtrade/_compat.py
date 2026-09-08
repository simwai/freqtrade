"""
Python 3.10 compatibility polyfills.

This module must be imported first, before any other freqtrade modules.
It patches builtins with 3.11+ features that are missing in 3.10.
"""

import sys
import importlib
import builtins

if sys.version_info < (3, 11):
    # StrEnum from enum (3.11+) - patch the enum module directly
    enum_mod = importlib.import_module('enum')
    if not hasattr(enum_mod, 'StrEnum'):
        # Create a simple StrEnum implementation for 3.10
        class _StrEnum(str, enum_mod.Enum):
            """Backport of StrEnum for Python 3.10"""
            def __new__(cls, value):
                if not isinstance(value, str):
                    raise TypeError(f"Value must be a string, got {type(value).__name__}")
                return super().__new__(cls, value)
            def __str__(self):
                return self.value
        enum_mod.StrEnum = _StrEnum
        builtins.StrEnum = _StrEnum

    # UTC from datetime (3.11+)
    if not hasattr(builtins, 'UTC'):
        datetime_mod = importlib.import_module('datetime')
        # Create UTC timezone
        from datetime import timezone, timedelta
        builtins.UTC = timezone(timedelta(0))

    # Self, Required, NotRequired from typing (3.11+)
    typing_mod = importlib.import_module('typing')
    if not hasattr(builtins, 'Self'):
        builtins.Self = getattr(typing_mod, 'Self', None)
    if not hasattr(builtins, 'Required'):
        builtins.Required = getattr(typing_mod, 'Required', None)
    if not hasattr(builtins, 'NotRequired'):
        builtins.NotRequired = getattr(typing_mod, 'NotRequired', None)