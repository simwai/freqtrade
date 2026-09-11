"""
Python 3.10 compatibility polyfills.

This module must be imported first, before any other freqtrade modules.
It patches builtins with 3.11+ features that are missing in 3.10.
"""

import builtins
import importlib
import sys


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
        enum_mod.StrEnum = _StrEnum  # type: ignore[attr-defined]
        builtins.StrEnum = _StrEnum  # type: ignore[attr-defined]

    # UTC from datetime (3.11+)
    if not hasattr(builtins, 'UTC'):
        datetime_mod = importlib.import_module('datetime')
        # Create UTC timezone
        from datetime import timedelta, timezone
        builtins.UTC = timezone(timedelta(0))  # type: ignore[attr-defined]

    # Self, Required, NotRequired from typing (3.11+)
    typing_mod = importlib.import_module('typing')
    if not hasattr(typing_mod, 'Self'):
        try:
            from typing_extensions import Self
            typing_mod.Self = Self  # type: ignore[attr-defined]
            builtins.Self = Self  # type: ignore[attr-defined]
        except ImportError:
            pass
    if not hasattr(typing_mod, 'Required'):
        try:
            from typing_extensions import Required
            typing_mod.Required = Required  # type: ignore[attr-defined]
            builtins.Required = Required  # type: ignore[attr-defined]
        except ImportError:
            pass
    if not hasattr(typing_mod, 'NotRequired'):
        try:
            from typing_extensions import NotRequired
            typing_mod.NotRequired = NotRequired  # type: ignore[attr-defined]
            builtins.NotRequired = NotRequired  # type: ignore[attr-defined]
        except ImportError:
            pass
