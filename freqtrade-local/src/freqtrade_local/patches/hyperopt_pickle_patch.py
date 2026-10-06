"""Runtime patch restricting hyperopt's pickle-by-value registrations.

Freqtrade's ``HyperOptimizer.hyperopt_pickle_magic`` walks a strategy's base
classes and registers each base's module with ``cloudpickle`` for pickling *by
value*, so worker processes can reconstruct strategy classes they cannot import.
The traversal recurses into ``__bases__`` without stopping, so it reaches
``object`` -- whose ``__module__`` is ``builtins`` -- and registers the entire
builtins module by value.

Serializing builtins by value is unbounded, so the payload cannot be pickled at
any recursion limit: joblib fails in the parent's feeder thread with
``PicklingError: Could not pickle the task to send it to the workers``, raised
from a ``RecursionError``.

This patch keeps the traversal shape but restricts registration to modules that
genuinely need by-value pickling. Stdlib and freqtrade modules (``builtins``,
``abc``, ``freqtrade.*``) are installed in every worker already, so workers
re-import them; only user strategy modules must travel by value.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def _needs_pickle_by_value(module_name: str) -> bool:
    """
    Report whether a module must be shipped to workers by value.

    Only user strategy modules qualify: they live under ``user_data`` and are
    generally not importable from a worker's working directory. Anything from
    the stdlib or from freqtrade itself resolves by reference in the worker, and
    registering those by value is what makes the payload unbounded.
    """
    return module_name == "user_data" or module_name.startswith("user_data.")


def _register_recursive(bases: tuple[type, ...], visited: set[type]) -> None:
    """
    Register the user modules reachable from a base-class chain.

    Mirrors the upstream traversal but leaves framework and stdlib modules to be
    re-imported by the worker. ``visited`` guards the repeated ``object`` base
    that appears under several branches of a typical strategy MRO.
    """
    from joblib.externals import cloudpickle

    for klass in bases:
        if klass in visited:
            continue
        visited.add(klass)

        module_name = getattr(klass, "__module__", None)
        if module_name and _needs_pickle_by_value(module_name):
            if (mod := sys.modules.get(module_name)) is not None:
                cloudpickle.register_pickle_by_value(mod)

        _register_recursive(klass.__bases__, visited)


def apply_hyperopt_pickle_patch() -> None:
    """
    Restrict ``hyperopt_pickle_magic`` to user strategy modules.

    Without this, registering ``builtins`` by value leaves hyperopt unpicklable
    for any strategy inheriting from ``IStrategy``.
    """
    try:
        from freqtrade.optimize.hyperopt.hyperopt_optimizer import HyperOptimizer
    except Exception as e:
        logger.warning("Failed to apply hyperopt pickle patch: %s", e)
        return

    if getattr(HyperOptimizer, "_hyperopt_pickle_patched", False):
        return

    original = HyperOptimizer.hyperopt_pickle_magic

    def hyperopt_pickle_magic(self: Any, bases: tuple[type, ...]) -> None:
        _register_recursive(bases, set())

    HyperOptimizer.hyperopt_pickle_magic = hyperopt_pickle_magic
    HyperOptimizer._hyperopt_pickle_original_magic = original  # type: ignore[attr-defined]
    HyperOptimizer._hyperopt_pickle_patched = True  # type: ignore[attr-defined]
    logger.debug("Restricted hyperopt pickle-by-value registration to user modules.")
