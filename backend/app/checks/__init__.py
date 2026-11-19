"""Importing this package registers every check in it.

Each module (other than registry/common) is imported automatically, so a new
check module only has to exist in this folder.
"""

import importlib
import pkgutil

from .registry import CHECKS, CannotScan, Check, ScanContext, register

_SKIP = {"registry", "common"}

for _mod in pkgutil.iter_modules(__path__):
    if _mod.name not in _SKIP:
        importlib.import_module(f"{__name__}.{_mod.name}")

__all__ = ["CHECKS", "CannotScan", "Check", "ScanContext", "register"]
