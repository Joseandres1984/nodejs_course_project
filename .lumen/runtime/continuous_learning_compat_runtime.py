from __future__ import annotations

"""Compatibility guard for Continuous Learning state shapes.

Some production state versions persist acquisition_campaigns as a list of campaign rows, while the
learning metric snapshot expects the aggregate acquisition report mapping. Normalize only for the
metric read, preserving the original state shape and all existing authority boundaries.
"""

from typing import Any, Dict

import continuous_learning_runtime as _learning

_ORIGINAL_METRIC_SNAPSHOT = _learning._metric_snapshot


def _aggregate_acquisition(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, list):
        return {}

    clicks = 0.0
    leads = 0.0
    for row in value:
        if not isinstance(row, dict):
            continue
        try:
            clicks += float(row.get("clicks") or 0)
        except (TypeError, ValueError):
            pass
        try:
            leads += float(row.get("leads") or 0)
        except (TypeError, ValueError):
            pass
    rate = (leads / clicks * 100.0) if clicks > 0 else 0.0
    return {"clicks": clicks, "leads": leads, "click_to_lead_rate": rate}


def _safe_metric_snapshot(state: Dict[str, Any]) -> Dict[str, float]:
    raw = state.get("acquisition_campaigns")
    if isinstance(raw, dict):
        return _ORIGINAL_METRIC_SNAPSHOT(state)
    shadow = dict(state)
    shadow["acquisition_campaigns"] = _aggregate_acquisition(raw)
    return _ORIGINAL_METRIC_SNAPSHOT(shadow)


_learning._metric_snapshot = _safe_metric_snapshot
print({"continuous_learning_compat_runtime": {"status": "active", "normalizes": "acquisition_campaigns_list_to_read_only_aggregate"}}, flush=True)
