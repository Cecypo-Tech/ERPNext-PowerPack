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
