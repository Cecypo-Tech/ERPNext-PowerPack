# Copyright (c) 2024, Cecypo.Tech and contributors
# For license information, please see license.txt

"""
Document Event Handlers for Validations
"""

import frappe
from frappe import _


def prevent_etr_invoice_cancellation(doc, method=None):
    """
    Prevent cancellation of Sales Invoice or POS Invoice if ETR Invoice Number is set.

    This is triggered before_cancel event for Sales Invoice and POS Invoice.

    Args:
        doc: The document being cancelled
        method: The event method name (not used)
    """
    # Check if the feature is enabled in settings
    try:
        settings = frappe.get_cached_doc('PowerPack Settings', 'PowerPack Settings')

        if not settings.get('prevent_etr_invoice_cancellation'):
            return  # Feature disabled, allow cancellation
    except Exception:
        # If settings don't exist, skip validation
        return

    # Check if ETR Invoice Number is set
    if doc.get('etr_invoice_number'):
        frappe.throw(
            _("This {0} cannot be cancelled as it contains an ETR Invoice Number: {1}").format(
                doc.doctype,
                doc.etr_invoice_number
            ),
            title=_("ETR Invoice Cannot Be Cancelled")
        )


def carry_return_tax_id(doc, method=None):
    """validate on Sales Invoice: a return keeps the original sale's tax_id.

    Sales Invoice.tax_id is fetched from Customer.tax_id on every draft save, before
    validate hooks run. A walk-in sale is on a shared Cash Sale customer whose tax_id is
    blank, so a return made from the desk Return button lost the buyer's PIN (Sayona
    CS-X-26-00010, 2026-10-20). Only fills a blank tax_id, so a PIN that klik_pos or the
    user put on the return is left alone.
    """
    if not doc.get("is_return") or not doc.get("return_against") or doc.get("tax_id"):
        return
    tax_id = frappe.db.get_value("Sales Invoice", doc.return_against, "tax_id")
    if tax_id:
        doc.tax_id = tax_id
