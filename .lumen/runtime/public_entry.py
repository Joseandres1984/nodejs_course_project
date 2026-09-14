from __future__ import annotations

from fastapi import Request

# Import the real production application first so all existing protected routes,
# middleware, outbound integrations and command-center behavior stay intact.
from outbound_web import app

# Register the existing public landing routes (/lumen and /about) on the same app.
from landing_public import _render as render_public_landing  # noqa: E402

# Register the Instagram integration routes. The connector reads its token only
# from Railway environment variables and never exposes it in responses.
import instagram_connector  # noqa: E402,F401

# Ensure the connected Instagram professional account is subscribed at account
# level to the webhook fields selected in Meta's dashboard.
import instagram_subscription_runtime  # noqa: E402,F401

# Register the Instagram Operator: inbox, classification, CRM promotion and
# human-approved replies. This also bridges successful webhooks into the inbox.
import instagram_operator  # noqa: E402,F401

# Surface Instagram Operator directly inside the owner Command Center.
import command_center_instagram_runtime  # noqa: E402,F401


@app.middleware("http")
async def public_root_landing(request: Request, call_next):
    """Serve the public LUMEN landing at GET/HEAD / without weakening admin auth."""
    if request.url.path == "/" and request.method in {"GET", "HEAD"}:
        return render_public_landing()
    return await call_next(request)
