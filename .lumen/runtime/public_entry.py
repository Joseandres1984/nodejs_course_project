from __future__ import annotations

from fastapi import Request

# Import the real production application first so all existing protected routes,
# middleware, outbound integrations and command-center behavior stay intact.
from outbound_web import app

# Register the existing public landing routes (/lumen and /about) on the same app.
from landing_public import _render as render_public_landing  # noqa: E402


@app.middleware("http")
async def public_root_landing(request: Request, call_next):
    """Serve the public LUMEN landing at GET/HEAD / without weakening admin auth."""
    if request.url.path == "/" and request.method in {"GET", "HEAD"}:
        return render_public_landing()
    return await call_next(request)
