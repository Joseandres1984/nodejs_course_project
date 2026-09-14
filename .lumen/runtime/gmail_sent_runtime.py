from __future__ import annotations

from typing import Any, Dict

import gmail_sent_archiver
import mail_connector


VERSION = "1.0-gmail-sent-runtime"
_ORIGINAL_SEND_PENDING = mail_connector.send_pending


def send_pending_with_gmail_sent(state: Dict[str, Any], live_outbound: bool):
    # Preserve the existing outbound sender, approval gates and delivery semantics first.
    stats = _ORIGINAL_SEND_PENDING(state, live_outbound)

    # Only after the provider has confirmed a send do we append a copy to Gmail Sent.
    # The archiver also safely catches previously-confirmed Brevo sends that predate this runtime.
    archive_stats = gmail_sent_archiver.backfill_confirmed_sends(state, limit=5)
    state["gmail_sent_runtime"] = {
        "version": VERSION,
        "archive_stats": archive_stats,
        "policy": "post_provider_confirmation_only_no_resend_dedupe_by_outbox_id",
    }
    return stats


mail_connector.send_pending = send_pending_with_gmail_sent
