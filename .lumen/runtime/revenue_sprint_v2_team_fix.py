from __future__ import annotations

"""Revenue Sprint 2.0 Mission Team activation hardening.

The legacy Mission Team builder truncates persisted rows after building its active set. Revenue
Sprint 2.1 already preserves focus-team references when they exist, but a First Cash opportunity
that has never had a persisted team has no object reference to recover. This shim seeds bounded,
empty team shells for the three First Cash focus opportunities before the existing Sprint wrapper
runs. The normal Mission Team engine then fills roster/objective/stage and applies all original
canonical/evidence gates.
"""

from typing import Any, Dict

import mission_team_runtime
import revenue_sprint_v2_runtime as sprint

VERSION = "2.2-first-cash-team-activation"
_ORIGINAL_PREPARE = mission_team_runtime._prepare_teams


def _prepare_with_seeded_first_cash(state: Dict[str, Any]) -> Dict[str, Any]:
    focus = list(sprint._focus_opportunity_ids(state) or [])[: sprint.MAX_FIRST_CASH_TEAMS]
    current = [x for x in state.get("mission_teams", []) or [] if isinstance(x, dict)]
    known = {str(x.get("opportunity_id") or "") for x in current}
    seeded = 0

    for oid in focus:
        if not oid or oid in known:
            continue
        current.append({
            "id": f"TEAM-SPRINT-{oid}",
            "opportunity_id": oid,
            "status": "reserve",
            "stage": "REQUIREMENT",
            "stagnant_cycles": 0,
            "members": [],
            "handoffs": [],
            "sprint_seeded": True,
        })
        known.add(oid)
        seeded += 1

    if seeded:
        state["mission_teams"] = current

    report = dict(_ORIGINAL_PREPARE(state) or {})
    active = [x for x in state.get("mission_teams", []) or [] if isinstance(x, dict) and x.get("status") == "active"]
    focus_set = set(focus)
    active_focus = [x for x in active if str(x.get("opportunity_id") or "") in focus_set]

    report["revenue_sprint_team_activation"] = True
    report["first_cash_focus_opportunity_ids"] = focus
    report["first_cash_team_shells_seeded"] = seeded
    report["active_focus_teams"] = len(active_focus)

    control = state.get("mission_team_control", {}) or {}
    control["revenue_sprint_team_activation"] = True
    control["first_cash_focus_opportunity_ids"] = focus
    control["first_cash_team_shells_seeded"] = seeded
    control["active_focus_teams"] = len(active_focus)
    state["mission_team_control"] = control
    return report


if not getattr(mission_team_runtime, "_lumen_revenue_sprint_team_activation_installed", False):
    mission_team_runtime._prepare_teams = _prepare_with_seeded_first_cash
    mission_team_runtime._lumen_revenue_sprint_team_activation_installed = True

print({
    "revenue_sprint_v2_team_fix": {
        "version": VERSION,
        "status": "installed",
        "max_first_cash_teams": sprint.MAX_FIRST_CASH_TEAMS,
        "authority_changed": False,
        "spend_changed": False,
    }
}, flush=True)

# Install the next conversion layer only after the First Cash team activation wrapper exists.
# It binds those teams to concrete cases, supports exact multi-source requirement completion,
# and restricts follow-ups to verified-delivery/no-reply contacts without changing any cap.
import revenue_sprint_v21_conversion_runtime  # noqa: E402,F401
