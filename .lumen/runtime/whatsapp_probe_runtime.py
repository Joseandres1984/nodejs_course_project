from __future__ import annotations

from notification_router import public_status

VERSION = "1.0-whatsapp-probe"

status = dict(public_status() or {})
# Never print secrets or recipient identifiers; public_status already exposes booleans only.
print({"whatsapp_probe": {"version": VERSION, **status}}, flush=True)
