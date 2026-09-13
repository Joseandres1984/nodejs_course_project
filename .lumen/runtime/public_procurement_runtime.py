from __future__ import annotations

from typing import Any, Dict

import scout_connector
from public_procurement_hunter import public_procurement_tick


VERSION = "1.0-public-procurement-runtime"
_ORIGINAL_SCOUT_TICK = scout_connector.scout_tick


def procurement_first_scout_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    procurement = dict(public_procurement_tick(state) or {})
    base = dict(_ORIGINAL_SCOUT_TICK(state) or {})
    base["public_procurement_hunter"] = procurement
    base["public_procurement_runtime_version"] = VERSION
    return base


scout_connector.scout_tick = procurement_first_scout_tick
