# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Tests for the status pill on the public short-link page.

The pill exists to explain an absence: when the page offers no Pay button and
no receipt, the document's status is the only thing that says why. These tests
pin the label and the tone for each state a payer can actually land on.
"""

import unittest
from unittest.mock import patch

import frappe

from cecypo_powerpack.pay_by_link import document_status


def _status(doctype="Quotation", status="Open", docstatus=1, settled=False):
    """Run document_status against a stubbed document."""
    row = frappe._dict({"status": status, "docstatus": docstatus})

    with patch("frappe.db.get_value", return_value=row), patch(
        "cecypo_powerpack.pay_by_link._settled_by_a_previous_request",
        return_value=settled,
    ):
        return document_status(doctype, "TEST-001")


class TestDocumentStatus(unittest.TestCase):
    # ------------------------------------------------------------------
    # The case that prompted this: a quotation with nothing to pay
    # ------------------------------------------------------------------

    def test_expired_quotation_reads_expired_and_closed(self):
        self.assertEqual(
            _status("Quotation", "Expired"),
            {"label": "Expired", "tone": "closed"},
        )

    def test_lost_quotation_is_closed(self):
        self.assertEqual(_status("Quotation", "Lost")["tone"], "closed")

    def test_ordered_quotation_is_closed(self):
        """Converted to an order - nothing to do here, so it reads closed."""
        self.assertEqual(_status("Quotation", "Ordered")["tone"], "closed")

    def test_open_quotation_is_open(self):
        self.assertEqual(
            _status("Quotation", "Open"),
            {"label": "Open", "tone": "open"},
        )

    # ------------------------------------------------------------------
    # docstatus outranks the status field
    # ------------------------------------------------------------------

    def test_draft_beats_whatever_status_says(self):
        result = _status("Quotation", status="Open", docstatus=0)
        self.assertEqual(result, {"label": "Draft", "tone": "closed"})

    def test_cancelled_beats_whatever_status_says(self):
        """A cancelled document keeps the status it held when cancelled."""
        result = _status("Sales Invoice", status="Overdue", docstatus=2)
        self.assertEqual(result, {"label": "Cancelled", "tone": "closed"})

    # ------------------------------------------------------------------
    # A quotation carries no payment state, so the request is the evidence
    # ------------------------------------------------------------------

    def test_quotation_settled_by_express_request_reads_paid(self):
        result = _status("Quotation", status="Open", settled=True)
        self.assertEqual(result, {"label": "Paid", "tone": "paid"})

    def test_settled_lookup_is_not_consulted_for_a_draft(self):
        """Nothing can have been paid against a document never submitted."""
        result = _status("Quotation", status="Open", docstatus=0, settled=True)
        self.assertEqual(result["label"], "Draft")

    def test_sales_order_is_not_second_guessed_by_express_requests(self):
        """A Sales Order has real payment state; only quotations need the lookup."""
        result = _status("Sales Order", status="To Deliver and Bill", settled=True)
        self.assertEqual(result, {"label": "To Deliver and Bill", "tone": "open"})

    # ------------------------------------------------------------------
    # Live and settled invoices / orders
    # ------------------------------------------------------------------

    def test_overdue_invoice_is_open(self):
        self.assertEqual(
            _status("Sales Invoice", "Overdue"),
            {"label": "Overdue", "tone": "open"},
        )

    def test_partly_paid_invoice_is_open(self):
        self.assertEqual(_status("Sales Invoice", "Partly Paid")["tone"], "open")

    def test_paid_invoice_is_paid(self):
        self.assertEqual(
            _status("Sales Invoice", "Paid"),
            {"label": "Paid", "tone": "paid"},
        )

    def test_completed_order_is_paid(self):
        self.assertEqual(_status("Sales Order", "Completed")["tone"], "paid")

    def test_closed_order_is_closed(self):
        self.assertEqual(_status("Sales Order", "Closed")["tone"], "closed")

    def test_credit_note_issued_is_closed(self):
        self.assertEqual(_status("Sales Invoice", "Credit Note Issued")["tone"], "closed")

    def test_unknown_status_falls_back_to_open_rather_than_vanishing(self):
        """An ERPNext upgrade adding a status must not blank the pill."""
        self.assertEqual(
            _status("Sales Invoice", "Some Future Status"),
            {"label": "Some Future Status", "tone": "open"},
        )

    # ------------------------------------------------------------------
    # Nothing to show
    # ------------------------------------------------------------------

    def test_unsupported_doctype_returns_none(self):
        self.assertIsNone(_status("Purchase Order", "To Receive"))

    def test_missing_document_returns_none(self):
        with patch("frappe.db.get_value", return_value=None):
            self.assertIsNone(document_status("Quotation", "NOPE-001"))

    def test_blank_status_returns_none_rather_than_an_empty_pill(self):
        self.assertIsNone(_status("Sales Invoice", status=""))


if __name__ == "__main__":
    unittest.main()
