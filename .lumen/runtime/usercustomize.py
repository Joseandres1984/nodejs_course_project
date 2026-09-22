from __future__ import annotations

"""LUMEN runtime user-level startup extensions.

Python loads this after sitecustomize when user-site customizations are enabled.
The Instagram policy only installs an import hook; failures remain fail-closed and
do not prevent the rest of LUMEN from starting.
"""

try:
    import instagram_safe_autopublish_runtime as _instagram_safe_autopublish_runtime  # noqa: F401
except Exception as exc:
    print(
        {
            "instagram_safe_autopublish": {
                "status": "install_failed_fail_closed",
                "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            }
        },
        flush=True,
    )
