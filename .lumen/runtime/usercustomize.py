from __future__ import annotations

"""Post-import activation for Autonomous Director in LUMEN Zero.

Python's site module loads usercustomize after sitecustomize in the runtime working
directory. The hook is inert until adaptive_operator_runtime is imported, then it
activates autonomous_director_runtime immediately after the established Adaptive
Operator bootstrap completes. This preserves the existing worker import order.
"""

import importlib
import importlib.abc
import importlib.machinery
import sys
from types import ModuleType
from typing import Any

_TARGET = "adaptive_operator_runtime"
_EXTENSION = "autonomous_director_runtime"


class _PostImportLoader(importlib.abc.Loader):
    def __init__(self, wrapped: Any, finder: "_AdaptivePostImportFinder") -> None:
        self.wrapped = wrapped
        self.finder = finder

    def create_module(self, spec: Any) -> ModuleType | None:
        create = getattr(self.wrapped, "create_module", None)
        return create(spec) if callable(create) else None

    def exec_module(self, module: ModuleType) -> None:
        self.wrapped.exec_module(module)
        try:
            sys.meta_path.remove(self.finder)
        except ValueError:
            pass
        importlib.import_module(_EXTENSION)


class _AdaptivePostImportFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname != _TARGET:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return None
        spec.loader = _PostImportLoader(spec.loader, self)
        return spec


if _TARGET in sys.modules:
    importlib.import_module(_EXTENSION)
elif not any(type(x).__name__ == "_AdaptivePostImportFinder" for x in sys.meta_path):
    sys.meta_path.insert(0, _AdaptivePostImportFinder())
