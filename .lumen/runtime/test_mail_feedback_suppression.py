from __future__ import annotations

import unittest
from email.message import EmailMessage
from unittest.mock import patch
from pathlib import Path

import mail_connector


class MailFeedbackSafety(unittest.TestCase):
    def test_respect_courteous_decline_even_with_positive_quoted_history(self):
        new = "Gracias por la información. Por el momento preferimos no avanzar."
        old = "---- On Fri, 09 Oct 2026 15:10:00 -0300 Sales wrote ----\n> Estamos interesados. ¿Podemos avanzar?"
        result = mail_connector.classify_reply("Re: propuesta", new + "\n\n" + old)
        self.assertEqual(result["kind"], "opt_out")

    def test_quoted_optout_must_not_override_new_positive_request(self):
        new = "Hola, sí, podemos avanzar con una propuesta actualizada."
        old = "On Fri, 09 Oct 2026 12:00:00 -0300 Buyer wrote:\n> No contactar"
        result = mail_connector.classify_reply("Re: consulta", new + "\n" + old)
        self.assertEqual(result["kind"], "buyer_interest")

    def test_decline_blocks_exact_recipient_and_pending_mail(self):
        state = {
            "opt_out": [], "email_suppression": [],
            "commercial_relationships": [
                {"commercial_email": "buyer@example.org", "relationship_state": "follow_up_due", "follow_up_due": True},
                {"commercial_email": "other@example.org", "relationship_state": "follow_up_due", "follow_up_due": True}
            ],
            "outbox": [
                {"contact": "buyer@example.org", "status": "ready"},
                {"contact": "other@example.org", "status": "ready"},
            ]
        }
        self.assertTrue(mail_connector.register_declined_recipient(state, "Buyer@Example.org", "declined"))
        self.assertTrue(mail_connector.is_suppressed(state, "buyer@example.org"))
        self.assertFalse(mail_connector.is_suppressed(state, "other@example.org"))
        self.assertEqual(state["outbox"][0]["status"], "blocked")
        self.assertEqual(state["outbox"][1]["status"], "ready")
        self.assertFalse(state["commercial_relationships"][0]["follow_up_due"])
        self.assertEqual(state["commercial_relationships"][0]["relationship_state"], "do_not_contact")
        # The suppression event must be idempotent.
        mail_connector.register_declined_recipient(state, "buyer@example.org", "declined")
        self.assertEqual(len(state["email_suppression"]), 1)

    def test_read_message_is_processed_once_and_blocks_queued_followup(self):
        msg = EmailMessage()
        msg["From"] = "Buyer <buyer@example.org>"
        msg["Subject"] = "Re: Propuesta"
        msg["Message-ID"] = "<synthetic-001@example.org>"
        msg.set_content("Gracias. Por el momento preferimos no avanzar con la evaluación.")
        raw = msg.as_bytes()

        class FakeImap:
            def login(self, *_): return "OK", []
            def select(self, mailbox, readonly=False):
                self.readonly = readonly
                return "OK", [b"1"]
            def search(self, *_):
                return "OK", [b"9"]
            def fetch(self, _id, query):
                self.query = query
                return "OK", [(b"9", raw)]
            def logout(self): return "BYE", []

        client = FakeImap()
        state = {"inbox": [], "opt_out": [], "outbox": [
            {"contact": "buyer@example.org", "status": "ready"}
        ]}
        with patch.object(mail_connector, "IMAP_HOST", "imap.example.org"), \
             patch.object(mail_connector, "IMAP_USER", "bot@example.org"), \
             patch.object(mail_connector, "IMAP_PASSWORD", "synthetic"), \
             patch.object(mail_connector.imaplib, "IMAP4_SSL", return_value=client), \
             patch.object(mail_connector, "ingest_email_attachments", return_value=[]):
            first = mail_connector.fetch_unseen(state)
            second = mail_connector.fetch_unseen(state)
        self.assertEqual(first["received"], 1)
        self.assertEqual(second["received"], 0)
        self.assertEqual(len(state["inbox"]), 1)
        self.assertEqual(state["outbox"][0]["status"], "blocked")
        self.assertTrue(mail_connector.is_suppressed(state, "buyer@example.org"))
        self.assertTrue(client.readonly)
        self.assertEqual(client.query, "(BODY.PEEK[])")

    def test_all_three_send_routes_check_shared_suppression(self):
        root = Path(__file__).parent
        for filename, marker in [
            ("mail_connector.py", "is_suppressed(state, target)"),
            ("mail_resilience.py", "mail_connector.is_suppressed(state, target)"),
            ("https_mail_transport.py", "mail_connector.is_suppressed(state, target)"),
        ]:
            with self.subTest(filename=filename):
                self.assertIn(marker, (root / filename).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
