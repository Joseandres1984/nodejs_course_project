from __future__ import annotations

from typing import Any, Dict

import public_procurement_hunter as hunter
import public_procurement_runtime as runtime


VERSION = "1.0-adaptive-procurement-runtime"
_ORIGINAL_TICK = runtime.public_procurement_tick
_BASE_CATEGORIES = tuple(hunter.CATEGORIES)


def _ordered_categories(state: Dict[str, Any]) -> tuple[str, ...]:
    snapshot = state.get("autonomy_operating_system", {}) or {}
    weights = snapshot.get("procurement_category_weights", {}) or {}
    if not weights:
        return _BASE_CATEGORIES
    return tuple(sorted(_BASE_CATEGORIES, key=lambda x: float(weights.get(x, 1.0) or 1.0), reverse=True))


def adaptive_public_procurement_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    previous = tuple(hunter.CATEGORIES)
    ordered = _ordered_categories(state)
    hunter.CATEGORIES = ordered
    try:
        report = dict(_ORIGINAL_TICK(state) or {})
    finally:
        hunter.CATEGORIES = previous
    report["adaptive_runtime_version"] = VERSION
    report["category_order"] = list(ordered)
    report["category_weights"] = dict((state.get("autonomy_operating_system", {}) or {}).get("procurement_category_weights", {}) or {})
    return report


runtime.public_procurement_tick = adaptive_public_procurement_tick
