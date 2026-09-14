from __future__ import annotations

import executive_secretary as _secretary

_ORIGINAL_TICK = _secretary.secretary_tick


def _logged_secretary_tick(state):
    snapshot = _ORIGINAL_TICK(state)
    print({
        "executive_secretary_private_bridge": {
            "status": snapshot.get("status"),
            "updated_at": snapshot.get("updated_at"),
            "brief": snapshot.get("brief"),
            "counts": snapshot.get("counts") or {},
            "deltas": snapshot.get("deltas") or {},
            "news": snapshot.get("news") or [],
            "pending": snapshot.get("pending") or [],
            "decisions": snapshot.get("decisions") or [],
            "deadlines": snapshot.get("deadlines") or [],
            "admin_attention": snapshot.get("admin_attention") or [],
            "resolved": snapshot.get("resolved") or [],
        }
    }, flush=True)
    return snapshot


_secretary.secretary_tick = _logged_secretary_tick
